"""Inicio de sesión, recuperación de contraseña, segundo factor (TOTP) y sesiones."""
from __future__ import annotations

import base64
from datetime import timedelta

import segno
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import CONFIG
from ..db import obtener_bd
from ..esquemas import CodigoIn, LoginIn, NuevaContrasenaIn, OlvideIn, TokenIn
from ..modelos import Sesion, Usuario, ahora
from ..seguridad import contrasenas, sesiones, totp
from ..seguridad.limites import limitar
from ..seguridad.permisos import ROLES, permisos_de
from ..servicios import auditoria, correo, usuarios
from ..servicios.semilla import CONTRASENA_DEMO, USUARIOS_DEMO

r = APIRouter(prefix="/api/auth", tags=["Identidad"])
MAX_INTENTOS = 5
BLOQUEO_MIN = 15
GENERICO = "Correo o contraseña incorrectos."


def usuario_dict(u: Usuario, s: Sesion | None = None) -> dict:
    return {"id": u.id, "correo": u.correo, "nombre": u.nombre, "cargo": u.cargo, "rol": u.rol,
            "rol_nombre": ROLES.get(u.rol, {}).get("nombre", u.rol), "mfa_activo": u.mfa_activo,
            "permisos": permisos_de(u.rol), "csrf": s.csrf if s else None}


def _fallo(bd: Session, u: Usuario, ip: str, motivo: str) -> None:
    """Cuenta un intento fallido (contraseña o código) y bloquea la cuenta al llegar al máximo."""
    u.intentos_fallidos += 1
    if u.intentos_fallidos >= MAX_INTENTOS:
        u.bloqueado_hasta = ahora() + timedelta(minutes=BLOQUEO_MIN)
        u.intentos_fallidos = 0
        auditoria.registrar(bd, "seguridad.bloqueo_cuenta", "Sistema", "usuario", str(u.id),
                            f"Cuenta {u.correo} bloqueada {BLOQUEO_MIN} min por {MAX_INTENTOS} intentos fallidos ({motivo}).",
                            {"ip": ip})
    bd.commit()


@r.post("/login")
def login(datos: LoginIn, request: Request, response: Response, bd: Session = Depends(obtener_bd)):
    ip = sesiones.ip_de(request)
    limitar(f"login-ip:{ip}", 10, 60)
    limitar(f"login-cuenta:{datos.correo.lower()}", 8, 900)
    u = bd.execute(select(Usuario).where(func.lower(Usuario.correo) == datos.correo.lower())).scalar_one_or_none()
    ok = contrasenas.verificar(u.hash_contrasena if u else None, datos.contrasena)  # mismo tiempo exista o no
    if not u or not u.activo:
        raise HTTPException(401, GENERICO)
    bloqueada = bool(u.bloqueado_hasta and u.bloqueado_hasta > ahora())
    if not ok:
        if not bloqueada:                     # durante el bloqueo no se cuenta ni se revela nada nuevo
            _fallo(bd, u, ip, "contraseña")
        raise HTTPException(401, GENERICO)
    if bloqueada:                             # solo quien sabe la contraseña se entera del bloqueo
        raise HTTPException(423, "Cuenta bloqueada temporalmente por intentos fallidos. Intente en unos minutos "
                                 "o restablezca su contraseña.")
    if u.mfa_activo:
        if not datos.codigo:
            return {"mfa_requerido": True}
        paso = totp.verificar_codigo(u.totp_cifrado, u.id, datos.codigo, u.totp_ultimo_paso)
        if paso is None:
            _fallo(bd, u, ip, "código de verificación")
            raise HTTPException(401, "Código de verificación incorrecto o ya usado.")
        u.totp_ultimo_paso = paso
    if contrasenas.necesita_rehash(u.hash_contrasena):
        u.hash_contrasena = contrasenas.hashear(datos.contrasena)
    u.intentos_fallidos, u.bloqueado_hasta, u.ultimo_acceso = 0, None, ahora()
    sesiones.revocar_actual(bd, request)      # la sesión anterior de este navegador no sobrevive al nuevo inicio
    s = sesiones.crear(bd, u, request, response)
    if u.mfa_activo:
        s.mfa_verificada_en = ahora()
    auditoria.registrar(bd, "seguridad.inicio_sesion", u.nombre, "usuario", str(u.id),
                        f"Inicio de sesión de {u.correo}" + (" con segundo factor" if u.mfa_activo else ""), {"ip": ip})
    bd.commit()
    return {"usuario": usuario_dict(u, s)}


@r.post("/logout")
def logout(request: Request, response: Response, bd: Session = Depends(obtener_bd)):
    sesiones.cerrar(bd, request, response)
    bd.commit()
    return {"ok": True}


@r.get("/yo")
def yo(ctx: sesiones.Contexto = Depends(sesiones.contexto)):
    return {"usuario": usuario_dict(ctx.usuario, ctx.sesion), "modo": CONFIG.modo, "version": CONFIG.version}


@r.get("/config")
def config_publica():
    """Lo que la pantalla de inicio necesita saber antes de entrar (nada sensible)."""
    return {"modo": CONFIG.modo, "entrega_correo": correo.entrega(), "acceso_demo": CONFIG.acceso_demo,
            "largo_minimo": contrasenas.LARGO_MINIMO}


@r.get("/demo")
def demo():
    """Cuentas de demostración. Apagado salvo en modo demo con KAUTA_ACCESO_DEMO=1."""
    if not CONFIG.acceso_demo:
        raise HTTPException(404)
    return {"contrasena": CONTRASENA_DEMO,
            "usuarios": [{"correo": c, "nombre": n, "cargo": g, "rol": r_, "rol_nombre": ROLES[r_]["nombre"]}
                         for c, n, g, r_ in USUARIOS_DEMO]}


@r.post("/olvide")
def olvide(datos: OlvideIn, request: Request, tareas: BackgroundTasks, bd: Session = Depends(obtener_bd)):
    """
    Pide un enlace para restablecer la contraseña. La respuesta es SIEMPRE la misma, exista o no la cuenta,
    y el correo se envía después de responder: así no se puede averiguar quién tiene cuenta.
    """
    ip = sesiones.ip_de(request)
    limitar(f"olvide-ip:{ip}", 5, 900)
    limitar(f"olvide-correo:{datos.correo.lower()}", 3, 3600)
    mensaje = usuarios.solicitar_restablecimiento(bd, datos.correo, ip)
    if mensaje:
        tareas.add_task(correo.enviar, *mensaje)
    return {"ok": True, "entrega": correo.entrega(),
            "mensaje": "Si el correo corresponde a una cuenta activa, en unos minutos recibirá un enlace para "
                       f"restablecer la contraseña. El enlace vence en {usuarios.MINUTOS_RESTABLECER} minutos."}


@r.post("/enlace")
def ver_enlace(datos: TokenIn, request: Request, bd: Session = Depends(obtener_bd)):
    """Comprueba un enlace de restablecimiento o activación antes de mostrar el formulario."""
    limitar(f"enlace-ip:{sesiones.ip_de(request)}", 20, 900)
    t = usuarios.token_valido(bd, datos.token)
    if not t:
        raise HTTPException(410, "El enlace no es válido, ya se usó o venció. Pida uno nuevo.")
    return {"tipo": t.tipo, "nombre": t.usuario.nombre, "correo": t.usuario.correo, "rol_nombre": ROLES.get(t.usuario.rol, {}).get("nombre")}


@r.post("/restablecer")
def restablecer(datos: NuevaContrasenaIn, request: Request, tareas: BackgroundTasks, bd: Session = Depends(obtener_bd)):
    """Fija la contraseña con un enlace de un solo uso (restablecer o activar). Cierra todas las sesiones."""
    ip = sesiones.ip_de(request)
    limitar(f"restablecer-ip:{ip}", 10, 900)
    try:
        u = usuarios.usar_token(bd, datos.token, datos.contrasena, ip)
    except usuarios.ErrorUsuarios as e:
        raise HTTPException(409, str(e)) from None
    if u.ultimo_acceso:                       # en una cuenta recién activada no hace falta el aviso
        tareas.add_task(correo.enviar, *usuarios.aviso_cambio_contrasena(u))
    return {"ok": True, "correo": u.correo, "mensaje": "Contraseña guardada. Ya puede iniciar sesión con ella."}


@r.post("/mfa/iniciar")
def mfa_iniciar(ctx: sesiones.Contexto = Depends(sesiones.contexto)):
    u = ctx.usuario
    if u.mfa_activo:
        raise HTTPException(409, "El segundo factor ya está activo.")
    secreto = totp.nuevo_secreto()
    u.totp_cifrado = totp.cifrar_secreto(secreto, u.id)
    ctx.bd.commit()
    uri = totp.uri(secreto, u.correo)
    svg = segno.make(uri, error="m").svg_inline(scale=5, dark="#0B1B3F", light="#FFFFFF")
    return {"uri": uri, "secreto": secreto, "qr": "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()}


@r.post("/mfa/confirmar")
def mfa_confirmar(datos: CodigoIn, ctx: sesiones.Contexto = Depends(sesiones.contexto)):
    u = ctx.usuario
    if not u.totp_cifrado:
        raise HTTPException(409, "Primero inicie la activación.")
    paso = totp.verificar_codigo(u.totp_cifrado, u.id, datos.codigo, u.totp_ultimo_paso)
    if paso is None:
        raise HTTPException(400, "El código no coincide. Revise la hora del teléfono e intente de nuevo.")
    u.mfa_activo, u.totp_ultimo_paso = True, paso
    ctx.sesion.mfa_verificada_en = ahora()
    auditoria.registrar(ctx.bd, "seguridad.mfa_activado", ctx.actor, "usuario", str(u.id), f"{u.correo} activó el segundo factor (TOTP).", {})
    ctx.bd.commit()
    return {"ok": True}


@r.post("/mfa/desactivar")
def mfa_desactivar(datos: CodigoIn, ctx: sesiones.Contexto = Depends(sesiones.contexto)):
    u = ctx.usuario
    if not u.mfa_activo:
        raise HTTPException(409, "El segundo factor no está activo.")
    if totp.verificar_codigo(u.totp_cifrado, u.id, datos.codigo, u.totp_ultimo_paso) is None:
        raise HTTPException(400, "Código incorrecto.")
    u.mfa_activo, u.totp_cifrado, u.totp_ultimo_paso = False, None, None
    auditoria.registrar(ctx.bd, "seguridad.mfa_desactivado", ctx.actor, "usuario", str(u.id), f"{u.correo} desactivó el segundo factor.", {})
    ctx.bd.commit()
    return {"ok": True}


@r.get("/sesiones")
def mis_sesiones(ctx: sesiones.Contexto = Depends(sesiones.contexto)):
    filas = ctx.bd.execute(select(Sesion).where(Sesion.usuario_id == ctx.usuario.id, Sesion.revocada.is_(False))
                           .order_by(Sesion.ultima_actividad.desc())).scalars().all()
    t = ahora()
    return [{"id": s.id[:12], "ip": s.ip, "navegador": (s.agente_usuario or "")[:90], "creada_en": s.creada_en.isoformat() + "Z",
             "ultima_actividad": s.ultima_actividad.isoformat() + "Z", "actual": s.id == ctx.sesion.id}
            for s in filas if s.expira_en > t]


@r.delete("/sesiones/{prefijo}")
def revocar(prefijo: str, ctx: sesiones.Contexto = Depends(sesiones.contexto)):
    for s in ctx.bd.execute(select(Sesion).where(Sesion.usuario_id == ctx.usuario.id)).scalars():
        if s.id.startswith(prefijo) and len(prefijo) >= 8:
            s.revocada = True
            auditoria.registrar(ctx.bd, "seguridad.sesion_revocada", ctx.actor, "usuario", str(ctx.usuario.id), "Sesión revocada por el usuario.", {})
    ctx.bd.commit()
    return {"ok": True}
