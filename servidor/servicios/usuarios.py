"""
Alta y gestión de personas: invitación, solicitud de acceso, recuperación de contraseña, roles y desactivación.

Cómo entra una persona en una empresa (y por qué no es registro abierto). Hay dos caminos y en
ninguno la persona elige su propio rol:

  A. Invitación. Administración define correo, nombre, cargo y **rol**; Kauta genera un código de un
     solo uso (caduca a los 7 días) que se entrega por otro canal. La persona lo usa en «Crear cuenta».
  B. Solicitud. La persona pide acceso con su nombre y su correo. No entra hasta que administración la
     aprueba y le asigna un rol; entonces recibe en ese correo un enlace para crear su contraseña.

Códigos y enlaces se guardan solo como hash (Argon2id los códigos cortos, SHA-256 los tokens de 256 bits):
si alguien se lleva la base de datos, no puede usarlos. Todo queda en el registro de auditoría.
"""
from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..modelos import Aprobacion, Factura, Invitacion, Sesion, SolicitudAcceso, TokenAcceso, Usuario
from ..modelos import ahora as ahora_bd
from ..seguridad import contrasenas
from ..seguridad.permisos import ROLES, etiqueta, permisos_de
from . import BLOQUEO, auditoria, correo as servicio_correo

DIAS_INVITACION = 7
MAX_INTENTOS_CODIGO = 8
MINUTOS_RESTABLECER = 60          # enlace pedido por la propia persona
HORAS_RESTABLECER_ADMIN = 24      # enlace que envía administración
HORAS_ACTIVAR = 72                # enlace para crear la contraseña de una cuenta aprobada
# Quien se registra solo entra con este rol sin esperar aprobación (Finanzas: el rol que paga las facturas). El
# Administrador lo puede cambiar después. KAUTA_REGISTRO_ROL vacío vuelve al alta con aprobación de administración.
ROL_REGISTRO = os.environ.get("KAUTA_REGISTRO_ROL", "finanzas").strip()
ALFABETO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # sin letras ni dígitos que se confundan al dictarlos

Correo = tuple[str, str, str]     # (destino, asunto, texto) para enviar después de responder


class ErrorUsuarios(Exception):
    pass


def ahora() -> datetime:
    return datetime.now(timezone.utc)


def _aware(f: datetime | None) -> datetime | None:
    return f if f is None or f.tzinfo else f.replace(tzinfo=timezone.utc)


def generar_codigo() -> str:
    """Código de 12 caracteres, en tres grupos, fácil de dictar por teléfono: KAU7-3BQX-9MFD."""
    cuerpo = "".join(secrets.choice(ALFABETO) for _ in range(8))
    return f"KAU{secrets.choice(ALFABETO)}-{cuerpo[:4]}-{cuerpo[4:]}"


def normalizar_correo(correo: str) -> str:
    return (correo or "").strip().lower()


# ---------------------------------------------------------------------------
# Invitaciones
# ---------------------------------------------------------------------------
def invitar(bd: Session, correo: str, nombre: str, cargo: str, rol: str, actor: str) -> tuple[Invitacion, str]:
    """Crea la invitación y devuelve el código en claro: se muestra una sola vez."""
    correo = normalizar_correo(correo)
    if rol not in ROLES:
        raise ErrorUsuarios(f"El rol «{rol}» no existe.")
    if not correo or "@" not in correo:
        raise ErrorUsuarios("Escriba un correo válido.")
    if not (nombre or "").strip():
        raise ErrorUsuarios("Escriba el nombre de la persona.")
    with BLOQUEO:
        if bd.execute(select(Usuario).where(func.lower(Usuario.correo) == correo)).scalar_one_or_none():
            raise ErrorUsuarios("Ya existe una cuenta con ese correo.")
        abierta = bd.execute(select(Invitacion).where(Invitacion.correo == correo, Invitacion.usada_en.is_(None),
                                                      Invitacion.revocada.is_(False))).scalars().all()
        for i in abierta:                       # una invitación nueva reemplaza a la anterior
            i.revocada = True
        codigo = generar_codigo()
        inv = Invitacion(correo=correo, nombre=nombre.strip(), cargo=(cargo or "").strip() or "Sin cargo", rol=rol,
                         hash_codigo=contrasenas.hashear(codigo), prefijo=codigo[:4], creada_por=actor,
                         expira_en=ahora() + timedelta(days=DIAS_INVITACION))
        bd.add(inv)
        bd.flush()
        auditoria.registrar(bd, "usuario.invitado", actor, "usuario", correo,
                            f"Invitación para {nombre} ({correo}) con el rol {ROLES[rol]['nombre']}.",
                            {"rol": rol, "prefijo": inv.prefijo, "expira_en": inv.expira_en.isoformat()})
        bd.commit()
    return inv, codigo


def revocar_invitacion(bd: Session, inv_id: int, actor: str) -> Invitacion:
    with BLOQUEO:
        inv = bd.get(Invitacion, inv_id)
        if not inv:
            raise ErrorUsuarios("La invitación no existe.")
        if inv.usada_en:
            raise ErrorUsuarios("Esa invitación ya se usó.")
        inv.revocada = True
        auditoria.registrar(bd, "usuario.invitacion_revocada", actor, "usuario", inv.correo,
                            f"Invitación de {inv.correo} revocada.", {"prefijo": inv.prefijo})
        bd.commit()
    return inv


def registrar(bd: Session, codigo: str, correo: str, contrasena: str, ip: str | None = None) -> Usuario:
    """Crea la cuenta a partir de una invitación. La persona elige su contraseña; el rol ya viene dado."""
    correo = normalizar_correo(correo)
    codigo = (codigo or "").strip().upper()
    with BLOQUEO:
        inv = bd.execute(select(Invitacion).where(Invitacion.correo == correo, Invitacion.usada_en.is_(None),
                                                  Invitacion.revocada.is_(False))
                         .order_by(Invitacion.id.desc())).scalars().first()
        generico = "La invitación no es válida, ya se usó o está vencida."
        if not inv:
            raise ErrorUsuarios(generico)
        if _aware(inv.expira_en) < ahora():
            raise ErrorUsuarios(generico)
        if inv.intentos >= MAX_INTENTOS_CODIGO:
            inv.revocada = True
            bd.commit()
            raise ErrorUsuarios("Demasiados intentos con el código: la invitación quedó bloqueada. Pida una nueva.")
        if not contrasenas.verificar(inv.hash_codigo, codigo):
            inv.intentos += 1
            auditoria.registrar(bd, "usuario.codigo_incorrecto", correo, "usuario", correo,
                                f"Código de invitación incorrecto para {correo} (intento {inv.intentos}).", {"ip": ip})
            bd.commit()
            raise ErrorUsuarios(generico)
        problemas = contrasenas.problemas_politica(contrasena, correo)
        if problemas:
            raise ErrorUsuarios(" ".join(problemas))
        if bd.execute(select(Usuario).where(func.lower(Usuario.correo) == correo)).scalar_one_or_none():
            raise ErrorUsuarios("Ya existe una cuenta con ese correo.")
        u = Usuario(correo=correo, nombre=inv.nombre, cargo=inv.cargo, rol=inv.rol,
                    hash_contrasena=contrasenas.hashear(contrasena))
        bd.add(u)
        inv.usada_en = ahora()
        bd.flush()
        auditoria.registrar(bd, "usuario.creado", correo, "usuario", correo,
                            f"{u.nombre} creó su cuenta con el rol {ROLES[u.rol]['nombre']} usando la invitación "
                            f"{inv.prefijo}…", {"rol": u.rol, "ip": ip})
        bd.commit()
    return u


# ---------------------------------------------------------------------------
# Gestión
# ---------------------------------------------------------------------------
def cambiar_rol(bd: Session, usuario_id: int, rol: str, actor: str) -> Usuario:
    if rol not in ROLES:
        raise ErrorUsuarios(f"El rol «{rol}» no existe.")
    with BLOQUEO:
        u = bd.get(Usuario, usuario_id)
        if not u:
            raise ErrorUsuarios("La persona no existe.")
        if u.rol == rol:
            return u
        if u.rol == "admin" and rol != "admin" and _admins(bd) <= 1:
            raise ErrorUsuarios("Debe quedar al menos una persona en administración.")
        antes, u.rol = u.rol, rol
        auditoria.registrar(bd, "usuario.rol_cambiado", actor, "usuario", u.correo,
                            f"{u.nombre}: rol {ROLES[antes]['nombre']} → {ROLES[rol]['nombre']}.",
                            {"antes": antes, "despues": rol})
        bd.commit()
    return u


def activar(bd: Session, usuario_id: int, activo: bool, actor: str) -> Usuario:
    """Desactivar cierra además todas sus sesiones: el acceso se corta de inmediato."""
    with BLOQUEO:
        u = bd.get(Usuario, usuario_id)
        if not u:
            raise ErrorUsuarios("La persona no existe.")
        if not activo and u.rol == "admin" and _admins(bd) <= 1:
            raise ErrorUsuarios("Debe quedar al menos una persona en administración.")
        u.activo = activo
        if not activo:
            u.bloqueado_hasta = None
            u.intentos_fallidos = 0
            _cerrar_sesiones(bd, u)
            _anular_tokens(bd, u)
        auditoria.registrar(bd, "usuario.activo" if activo else "usuario.desactivado", actor, "usuario", u.correo,
                            f"{u.nombre} quedó {'activa' if activo else 'desactivada'}.", {"rol": u.rol})
        bd.commit()
    return u


def desbloquear(bd: Session, usuario_id: int, actor: str) -> Usuario:
    with BLOQUEO:
        u = bd.get(Usuario, usuario_id)
        if not u:
            raise ErrorUsuarios("La persona no existe.")
        u.intentos_fallidos, u.bloqueado_hasta = 0, None
        auditoria.registrar(bd, "usuario.desbloqueado", actor, "usuario", u.correo,
                            f"{u.nombre} quedó desbloqueada tras intentos fallidos.", {})
        bd.commit()
    return u


def cambiar_contrasena(bd: Session, u: Usuario, actual: str, nueva: str, sesion_actual: str | None = None) -> Usuario:
    """La propia persona cambia su contraseña; se cierran sus demás sesiones (las de otros dispositivos)."""
    if not contrasenas.verificar(u.hash_contrasena, actual):
        raise ErrorUsuarios("La contraseña actual no coincide.")
    if actual == nueva:
        raise ErrorUsuarios("La contraseña nueva debe ser distinta de la actual.")
    problemas = contrasenas.problemas_politica(nueva, u.correo)
    if problemas:
        raise ErrorUsuarios(" ".join(problemas))
    with BLOQUEO:
        u.hash_contrasena = contrasenas.hashear(nueva)
        cerradas = _cerrar_sesiones(bd, u, excepto=sesion_actual)
        _anular_tokens(bd, u)
        auditoria.registrar(bd, "usuario.contrasena_cambiada", f"{u.nombre} ({u.cargo})", "usuario", u.correo,
                            f"{u.nombre} cambió su contraseña; se cerraron {cerradas} sesiones en otros dispositivos.", {})
        bd.commit()
    return u


def _cerrar_sesiones(bd: Session, u: Usuario, excepto: str | None = None) -> int:
    n = 0
    for s in bd.execute(select(Sesion).where(Sesion.usuario_id == u.id, Sesion.revocada.is_(False))).scalars():
        if s.id != excepto:
            s.revocada = True
            n += 1
    return n


# ---------------------------------------------------------------------------
# Enlaces de un solo uso: restablecer la contraseña y activar una cuenta aprobada
# ---------------------------------------------------------------------------
def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _anular_tokens(bd: Session, u: Usuario) -> None:
    """Un enlace nuevo, un cambio de contraseña o una desactivación invalidan los enlaces anteriores."""
    for t in bd.execute(select(TokenAcceso).where(TokenAcceso.usuario_id == u.id, TokenAcceso.usado_en.is_(None))).scalars():
        t.usado_en = ahora_bd()


def _crear_token(bd: Session, u: Usuario, tipo: str, vigencia: timedelta, ip: str | None) -> str:
    _anular_tokens(bd, u)
    token = secrets.token_urlsafe(32)                       # 256 bits: no se puede adivinar ni probar a ciegas
    bd.add(TokenAcceso(tipo=tipo, hash=_hash_token(token), usuario_id=u.id, expira_en=ahora_bd() + vigencia, ip=ip))
    return token


def _correo_restablecer(u: Usuario, token: str, vigencia: str, por_admin: bool = False) -> Correo:
    origen = "Administración pidió" if por_admin else "Se pidió"
    return (u.correo, "Kauta · Restablezca su contraseña",
            f"Hola, {u.nombre}:\n\n{origen} restablecer la contraseña de su cuenta de Kauta. Para elegir una nueva, abra este enlace:\n\n"
            f"{servicio_correo.enlace('restablecer/' + token)}\n\n"
            f"El enlace sirve una sola vez y vence en {vigencia}. Al usarlo se cierran todas sus sesiones abiertas.\n"
            "Si usted no lo pidió, ignore este mensaje: su contraseña actual sigue funcionando.")


def solicitar_restablecimiento(bd: Session, correo: str, ip: str | None) -> Correo | None:
    """Devuelve el correo que hay que enviar, o None si no hay una cuenta activa (la respuesta HTTP es la misma)."""
    correo = normalizar_correo(correo)
    with BLOQUEO:
        u = bd.execute(select(Usuario).where(func.lower(Usuario.correo) == correo)).scalar_one_or_none()
        if not u or not u.activo:
            return None
        token = _crear_token(bd, u, "restablecer", timedelta(minutes=MINUTOS_RESTABLECER), ip)
        auditoria.registrar(bd, "seguridad.restablecer_pedido", u.correo, "usuario", u.correo,
                            f"Se pidió un enlace para restablecer la contraseña de {u.correo}.", {"ip": ip})
        bd.commit()
    return _correo_restablecer(u, token, f"{MINUTOS_RESTABLECER} minutos")


def restablecer_por_admin(bd: Session, usuario_id: int, actor: str, ip: str | None) -> Correo:
    with BLOQUEO:
        u = bd.get(Usuario, usuario_id)
        if not u:
            raise ErrorUsuarios("La persona no existe.")
        if not u.activo:
            raise ErrorUsuarios("La cuenta está desactivada: actívela antes de enviar el enlace.")
        token = _crear_token(bd, u, "restablecer", timedelta(hours=HORAS_RESTABLECER_ADMIN), ip)
        auditoria.registrar(bd, "seguridad.restablecer_enviado", actor, "usuario", u.correo,
                            f"Administración envió a {u.correo} un enlace para restablecer su contraseña.", {"ip": ip})
        bd.commit()
    return _correo_restablecer(u, token, f"{HORAS_RESTABLECER_ADMIN} horas", por_admin=True)


def token_valido(bd: Session, token: str) -> TokenAcceso | None:
    t = bd.execute(select(TokenAcceso).where(TokenAcceso.hash == _hash_token(token or ""))).scalar_one_or_none()
    if not t or t.usado_en is not None or t.expira_en < ahora_bd() or not t.usuario.activo:
        return None
    return t


def usar_token(bd: Session, token: str, contrasena: str, ip: str | None) -> Usuario:
    """Fija la contraseña con un enlace válido. Desbloquea la cuenta y cierra todas sus sesiones."""
    with BLOQUEO:
        t = token_valido(bd, token)
        if not t:
            raise ErrorUsuarios("El enlace no es válido, ya se usó o venció. Pida uno nuevo desde «¿Olvidó su contraseña?».")
        u = t.usuario
        problemas = contrasenas.problemas_politica(contrasena, u.correo)
        if problemas:
            raise ErrorUsuarios(" ".join(problemas))
        if t.tipo == "restablecer" and contrasenas.verificar(u.hash_contrasena, contrasena):
            raise ErrorUsuarios("La contraseña nueva debe ser distinta de la anterior.")
        u.hash_contrasena = contrasenas.hashear(contrasena)
        u.intentos_fallidos, u.bloqueado_hasta = 0, None
        _anular_tokens(bd, u)                                # incluye este: el enlace ya no sirve
        cerradas = _cerrar_sesiones(bd, u)
        if t.tipo == "activar":
            auditoria.registrar(bd, "usuario.cuenta_activada", u.correo, "usuario", u.correo,
                                f"{u.nombre} activó su cuenta y creó su contraseña.", {"ip": ip, "rol": u.rol})
        else:
            auditoria.registrar(bd, "seguridad.contrasena_restablecida", u.correo, "usuario", u.correo,
                                f"{u.nombre} restableció su contraseña con un enlace de un solo uso; "
                                f"se cerraron {cerradas} sesiones.", {"ip": ip})
        bd.commit()
    return u


def aviso_cambio_contrasena(u: Usuario) -> Correo:
    return (u.correo, "Kauta · Su contraseña cambió",
            f"Hola, {u.nombre}:\n\nLa contraseña de su cuenta de Kauta acaba de cambiar y se cerraron sus sesiones abiertas.\n"
            "Si no fue usted, avise de inmediato a administración y restablézcala desde "
            f"{servicio_correo.enlace('olvide')}.")


# ---------------------------------------------------------------------------
# Registro y solicitudes de acceso (alta sin invitación)
# ---------------------------------------------------------------------------
def solicitar_acceso(bd: Session, correo: str, nombre: str, cargo: str, mensaje: str, ip: str | None) -> list[Correo]:
    """
    Registra la solicitud y devuelve los correos a enviar. La respuesta HTTP es igual exista o no la cuenta:
    si ya existe, a esa persona se le avisa por correo en lugar de crear una solicitud duplicada.
    """
    correo = normalizar_correo(correo)
    nombre = " ".join((nombre or "").split())
    with BLOQUEO:
        u = bd.execute(select(Usuario).where(func.lower(Usuario.correo) == correo)).scalar_one_or_none()
        if u:
            return [(u.correo, "Kauta · Ya tiene una cuenta",
                     f"Hola, {u.nombre}:\n\nAlguien pidió acceso a Kauta con este correo, pero usted ya tiene una cuenta.\n"
                     f"Si olvidó su contraseña, restablézcala aquí: {servicio_correo.enlace('olvide')}\n"
                     "Si no fue usted, puede ignorar este mensaje.")]
        abierta = bd.execute(select(SolicitudAcceso).where(SolicitudAcceso.correo == correo,
                                                           SolicitudAcceso.estado == "pendiente")).scalars().first()
        if abierta:
            return []
        s = SolicitudAcceso(correo=correo, nombre=nombre, cargo=(cargo or "").strip() or "Sin cargo",
                            mensaje=(mensaje or "").strip(), ip=ip)
        bd.add(s)
        bd.flush()
        if ROL_REGISTRO in ROLES:
            return _registro_automatico(bd, s, ip)
        auditoria.registrar(bd, "usuario.acceso_solicitado", correo, "usuario", correo,
                            f"{nombre} ({correo}) pidió acceso a Kauta.", {"ip": ip, "solicitud": s.id})
        admins = bd.execute(select(Usuario).where(Usuario.rol == "admin", Usuario.activo.is_(True))).scalars().all()
        bd.commit()
    aviso = (f"{nombre} ({correo}) pidió acceso a Kauta como «{s.cargo}».\n"
             + (f"Mensaje: {s.mensaje}\n" if s.mensaje else "")
             + f"\nRevise la solicitud y asigne un rol en «Personas y roles»: {servicio_correo.enlace('personas')}\n"
             "Antes de aprobarla, confirme por un canal independiente que la persona trabaja en la empresa.")
    return [(a.correo, "Kauta · Nueva solicitud de acceso", aviso) for a in admins]


def _registro_automatico(bd: Session, s: SolicitudAcceso, ip: str | None) -> list[Correo]:
    """
    Alta sin aprobación: la cuenta queda con el rol de registro (Finanzas) y la persona recibe en SU correo el enlace
    para crear la contraseña. Probar que el correo es suyo es el único requisito; nadie más tiene que aprobar.
    """
    rol = ROL_REGISTRO
    u = Usuario(correo=s.correo, nombre=s.nombre, cargo=s.cargo, rol=rol,
                hash_contrasena=contrasenas.hashear(secrets.token_urlsafe(32)))
    bd.add(u)
    bd.flush()
    token = _crear_token(bd, u, "activar", timedelta(hours=HORAS_ACTIVAR), ip)
    s.estado, s.rol, s.resuelta_por, s.resuelta_en = "aprobada", rol, "Registro automático", ahora_bd()
    auditoria.registrar(bd, "usuario.registro", s.correo, "usuario", s.correo,
                        f"{s.nombre} ({s.correo}) se registró y quedó con el rol {ROLES[rol]['nombre']} sin aprobación; "
                        "se envió el enlace de activación a su correo.", {"rol": rol, "solicitud": s.id, "ip": ip})
    admins = bd.execute(select(Usuario).where(Usuario.rol == "admin", Usuario.activo.is_(True))).scalars().all()
    bd.commit()
    bienvenida = (s.correo, "Kauta · Active su cuenta",
                  f"Hola, {s.nombre}:\n\nSu cuenta de Kauta quedó creada con el rol «{ROLES[rol]['nombre']}»: "
                  f"{ROLES[rol]['descripcion']}\n\nPara activarla, cree su contraseña aquí:\n\n"
                  f"{servicio_correo.enlace('activar/' + token)}\n\nEl enlace sirve una sola vez y vence en {HORAS_ACTIVAR} horas.\n"
                  "Si usted no se registró, ignore este mensaje: sin la contraseña nadie puede entrar.")
    aviso = (f"{s.nombre} ({s.correo}) se registró en Kauta y quedó con el rol «{ROLES[rol]['nombre']}» automáticamente.\n"
             f"Si debe tener otro rol, o ninguno, cámbielo en «Personas y roles»: {servicio_correo.enlace('personas')}")
    return [bienvenida, *[(a.correo, "Kauta · Nueva persona registrada", aviso) for a in admins]]


def aprobar_solicitud(bd: Session, sid: int, rol: str, actor: str, ip: str | None) -> tuple[SolicitudAcceso, Correo]:
    if rol not in ROLES:
        raise ErrorUsuarios(f"El rol «{rol}» no existe.")
    with BLOQUEO:
        s = bd.get(SolicitudAcceso, sid)
        if not s or s.estado != "pendiente":
            raise ErrorUsuarios("La solicitud no existe o ya se resolvió.")
        if bd.execute(select(Usuario).where(func.lower(Usuario.correo) == s.correo)).scalar_one_or_none():
            raise ErrorUsuarios("Ya existe una cuenta con ese correo.")
        # Sin contraseña utilizable hasta que la persona abra el enlace de activación que llega a su correo
        u = Usuario(correo=s.correo, nombre=s.nombre, cargo=s.cargo, rol=rol,
                    hash_contrasena=contrasenas.hashear(secrets.token_urlsafe(32)))
        bd.add(u)
        bd.flush()
        token = _crear_token(bd, u, "activar", timedelta(hours=HORAS_ACTIVAR), ip)
        s.estado, s.rol, s.resuelta_por, s.resuelta_en = "aprobada", rol, actor, ahora_bd()
        auditoria.registrar(bd, "usuario.solicitud_aprobada", actor, "usuario", s.correo,
                            f"Solicitud de {s.nombre} ({s.correo}) aprobada con el rol {ROLES[rol]['nombre']}; "
                            "se envió el enlace de activación.", {"rol": rol, "solicitud": s.id})
        bd.commit()
    return s, (s.correo, "Kauta · Su acceso fue aprobado",
               f"Hola, {s.nombre}:\n\nSu acceso a Kauta fue aprobado con el rol «{ROLES[rol]['nombre']}».\n"
               f"Para activar la cuenta, cree su contraseña aquí:\n\n{servicio_correo.enlace('activar/' + token)}\n\n"
               f"El enlace sirve una sola vez y vence en {HORAS_ACTIVAR} horas.")


def rechazar_solicitud(bd: Session, sid: int, motivo: str, actor: str) -> tuple[SolicitudAcceso, Correo]:
    with BLOQUEO:
        s = bd.get(SolicitudAcceso, sid)
        if not s or s.estado != "pendiente":
            raise ErrorUsuarios("La solicitud no existe o ya se resolvió.")
        s.estado, s.motivo, s.resuelta_por, s.resuelta_en = "rechazada", (motivo or "").strip() or None, actor, ahora_bd()
        auditoria.registrar(bd, "usuario.solicitud_rechazada", actor, "usuario", s.correo,
                            f"Solicitud de acceso de {s.nombre} ({s.correo}) rechazada." + (f" Motivo: {s.motivo}" if s.motivo else ""),
                            {"solicitud": s.id})
        bd.commit()
    return s, (s.correo, "Kauta · Su solicitud de acceso",
               f"Hola, {s.nombre}:\n\nSu solicitud de acceso a Kauta no fue aprobada."
               + (f"\nMotivo: {s.motivo}" if s.motivo else "") + "\nSi cree que es un error, comuníquese con su área de administración.")


def _admins(bd: Session) -> int:
    return bd.execute(select(func.count()).select_from(Usuario)
                      .where(Usuario.rol == "admin", Usuario.activo.is_(True))).scalar_one()


# ---------------------------------------------------------------------------
# Lecturas para la pantalla
# ---------------------------------------------------------------------------
def _iso(f: datetime | None) -> str | None:
    f = _aware(f)
    return f.isoformat(timespec="seconds") if f else None


def usuario_dict(bd: Session, u: Usuario) -> dict[str, Any]:
    rol = ROLES.get(u.rol, {})
    cargadas = bd.execute(select(func.count()).select_from(Factura).where(Factura.cargada_por == u.correo)).scalar_one()
    firmas = bd.execute(select(func.count()).select_from(Aprobacion).where(Aprobacion.usuario_id == u.id)).scalar_one()
    sesiones = bd.execute(select(func.count()).select_from(Sesion)
                          .where(Sesion.usuario_id == u.id, Sesion.revocada.is_(False))).scalar_one()
    return {"id": u.id, "correo": u.correo, "nombre": u.nombre, "cargo": u.cargo, "rol": u.rol,
            "rol_nombre": rol.get("nombre", u.rol), "rol_descripcion": rol.get("descripcion", ""),
            "activo": u.activo, "mfa_activo": u.mfa_activo, "creado_en": _iso(u.creado_en),
            "ultimo_acceso": _iso(u.ultimo_acceso), "bloqueado": bool(u.bloqueado_hasta and _aware(u.bloqueado_hasta) > ahora()),
            "intentos_fallidos": u.intentos_fallidos, "facturas_cargadas": cargadas, "firmas": firmas,
            "sesiones_abiertas": sesiones}


def invitacion_dict(inv: Invitacion) -> dict[str, Any]:
    estado = ("usada" if inv.usada_en else "revocada" if inv.revocada
              else "vencida" if _aware(inv.expira_en) < ahora() else "pendiente")
    return {"id": inv.id, "correo": inv.correo, "nombre": inv.nombre, "cargo": inv.cargo, "rol": inv.rol,
            "rol_nombre": ROLES.get(inv.rol, {}).get("nombre", inv.rol), "prefijo": inv.prefijo, "estado": estado,
            "creada_por": inv.creada_por, "creada_en": _iso(inv.creada_en), "expira_en": _iso(inv.expira_en),
            "usada_en": _iso(inv.usada_en), "intentos": inv.intentos}


def solicitud_dict(s: SolicitudAcceso) -> dict[str, Any]:
    return {"id": s.id, "correo": s.correo, "nombre": s.nombre, "cargo": s.cargo, "mensaje": s.mensaje, "estado": s.estado,
            "creada_en": _iso(s.creada_en), "resuelta_en": _iso(s.resuelta_en), "resuelta_por": s.resuelta_por,
            "rol": s.rol, "rol_nombre": ROLES.get(s.rol or "", {}).get("nombre"), "motivo": s.motivo}


def listar(bd: Session) -> dict[str, Any]:
    usuarios = bd.execute(select(Usuario).order_by(Usuario.nombre)).scalars().all()
    invitaciones = bd.execute(select(Invitacion).order_by(Invitacion.id.desc()).limit(40)).scalars().all()
    solicitudes = bd.execute(select(SolicitudAcceso).order_by(SolicitudAcceso.id.desc()).limit(40)).scalars().all()
    por_rol: dict[str, int] = {}
    for u in usuarios:
        if u.activo:
            por_rol[u.rol] = por_rol.get(u.rol, 0) + 1
    return {
        "usuarios": [usuario_dict(bd, u) for u in usuarios],
        "invitaciones": [invitacion_dict(i) for i in invitaciones],
        "solicitudes": [solicitud_dict(s) for s in solicitudes],
        "entrega_correo": servicio_correo.entrega(),
        "roles": [{"id": k, "nombre": v["nombre"], "descripcion": v["descripcion"],
                   "permisos": ([etiqueta(x) for x in sorted(v["permisos"]) if x != "*"] or ["Todos los permisos"]),
                   "claves": permisos_de(k),
                   "personas": por_rol.get(k, 0)} for k, v in ROLES.items()],
        "politica_contrasena": {"largo_minimo": contrasenas.LARGO_MINIMO,
                                "texto": f"Al menos {contrasenas.LARGO_MINIMO} caracteres. Sin reglas de composición "
                                         "ni caducidad forzada (NIST SP 800-63B-4); se rechazan las contraseñas comunes."},
        "dias_invitacion": DIAS_INVITACION,
    }
