"""Personas de la empresa: invitación, solicitud de acceso, registro con código, roles y estado de cada cuenta."""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..db import obtener_bd
from ..esquemas import (ActivoIn, AprobarSolicitudIn, CambioContrasenaIn, InvitarIn, RechazarSolicitudIn, RegistroIn, RolIn,
                        SolicitudAccesoIn)
from ..seguridad.limites import limitar
from ..seguridad.sesiones import Contexto, contexto, ip_de, requiere
from ..servicios import correo, usuarios
from ..servicios.usuarios import ErrorUsuarios

r = APIRouter(prefix="/api", tags=["Personas"])


def _error(e: ErrorUsuarios) -> HTTPException:
    return HTTPException(409, str(e))


@r.get("/personas")
def listar(ctx: Contexto = Depends(requiere("usuarios.ver"))):
    """Lista de personas, invitaciones, solicitudes y roles. La ve administración y el CEO."""
    return usuarios.listar(ctx.bd)


@r.post("/personas/invitar")
def invitar(datos: InvitarIn, ctx: Contexto = Depends(requiere("usuarios.gestionar"))):
    """Crea la invitación. El código se devuelve una sola vez: después solo queda su hash."""
    try:
        inv, codigo = usuarios.invitar(ctx.bd, datos.correo, datos.nombre, datos.cargo, datos.rol, ctx.actor)
    except ErrorUsuarios as e:
        raise _error(e) from None
    return {"invitacion": usuarios.invitacion_dict(inv), "codigo": codigo,
            "aviso": "Entregue este código por un canal distinto al correo de la invitación. No se vuelve a mostrar."}


@r.delete("/personas/invitaciones/{inv_id}")
def revocar(inv_id: int, ctx: Contexto = Depends(requiere("usuarios.gestionar"))):
    try:
        return usuarios.invitacion_dict(usuarios.revocar_invitacion(ctx.bd, inv_id, ctx.actor))
    except ErrorUsuarios as e:
        raise _error(e) from None


@r.post("/personas/registro")
def registro(datos: RegistroIn, request: Request, bd: Session = Depends(obtener_bd)):
    """Alta de la propia persona con el código de invitación. No necesita sesión; el rol ya viene dado."""
    ip = ip_de(request)
    limitar(f"registro-ip:{ip}", 8, 900)                 # contra el ensayo de códigos a ciegas
    limitar(f"registro-correo:{datos.correo.lower()}", 6, 900)
    try:
        u = usuarios.registrar(bd, datos.codigo, datos.correo, datos.contrasena, ip)
    except ErrorUsuarios as e:
        raise _error(e) from None
    return {"ok": True, "correo": u.correo, "nombre": u.nombre, "rol": u.rol, "rol_nombre": usuarios.ROLES[u.rol]["nombre"],
            "mensaje": "Cuenta creada. Ya puede entrar con su correo y su contraseña."}


@r.post("/personas/solicitar")
def solicitar(datos: SolicitudAccesoIn, request: Request, tareas: BackgroundTasks, bd: Session = Depends(obtener_bd)):
    """
    Registro sin invitación. Con KAUTA_REGISTRO_ROL (Finanzas por defecto) la cuenta queda creada con ese rol y la
    persona recibe en su correo el enlace para crear su contraseña; sin él, administración aprueba y asigna el rol.
    La respuesta es la misma exista o no la cuenta (no revela qué correos están registrados).
    """
    ip = ip_de(request)
    limitar(f"solicitud-ip:{ip}", 5, 3600)
    limitar(f"solicitud-correo:{datos.correo.lower()}", 3, 3600)
    for mensaje in usuarios.solicitar_acceso(bd, datos.correo, datos.nombre, datos.cargo, datos.mensaje, ip):
        tareas.add_task(correo.enviar, *mensaje)
    if usuarios.ROL_REGISTRO in usuarios.ROLES:
        return {"ok": True, "entrega": correo.entrega(), "automatico": True, "rol": usuarios.ROLES[usuarios.ROL_REGISTRO]["nombre"],
                "mensaje": "Revise su correo: le enviamos el enlace para crear su contraseña. Entrará con el rol "
                           f"{usuarios.ROLES[usuarios.ROL_REGISTRO]['nombre']}; administración puede cambiarlo."}
    return {"ok": True, "entrega": correo.entrega(), "automatico": False,
            "mensaje": "Recibimos su solicitud. Administración la revisará y, si la aprueba, le llegará al correo un "
                       "enlace para crear su contraseña."}


@r.post("/personas/solicitudes/{sid}/aprobar")
def aprobar_solicitud(sid: int, datos: AprobarSolicitudIn, request: Request, tareas: BackgroundTasks,
                      ctx: Contexto = Depends(requiere("usuarios.gestionar"))):
    try:
        s, mensaje = usuarios.aprobar_solicitud(ctx.bd, sid, datos.rol, ctx.actor, ip_de(request))
    except ErrorUsuarios as e:
        raise _error(e) from None
    tareas.add_task(correo.enviar, *mensaje)
    return {"solicitud": usuarios.solicitud_dict(s), "entrega": correo.entrega(),
            "mensaje": f"{s.nombre} recibirá en {s.correo} el enlace para activar su cuenta."}


@r.post("/personas/solicitudes/{sid}/rechazar")
def rechazar_solicitud(sid: int, datos: RechazarSolicitudIn, tareas: BackgroundTasks,
                       ctx: Contexto = Depends(requiere("usuarios.gestionar"))):
    try:
        s, mensaje = usuarios.rechazar_solicitud(ctx.bd, sid, datos.motivo, ctx.actor)
    except ErrorUsuarios as e:
        raise _error(e) from None
    tareas.add_task(correo.enviar, *mensaje)
    return {"solicitud": usuarios.solicitud_dict(s)}


@r.put("/personas/{usuario_id}/rol")
def rol(usuario_id: int, datos: RolIn, ctx: Contexto = Depends(requiere("usuarios.gestionar"))):
    try:
        return usuarios.usuario_dict(ctx.bd, usuarios.cambiar_rol(ctx.bd, usuario_id, datos.rol, ctx.actor))
    except ErrorUsuarios as e:
        raise _error(e) from None


@r.put("/personas/{usuario_id}/activo")
def activo(usuario_id: int, datos: ActivoIn, ctx: Contexto = Depends(requiere("usuarios.gestionar"))):
    try:
        return usuarios.usuario_dict(ctx.bd, usuarios.activar(ctx.bd, usuario_id, datos.activo, ctx.actor))
    except ErrorUsuarios as e:
        raise _error(e) from None


@r.post("/personas/{usuario_id}/desbloquear")
def desbloquear(usuario_id: int, ctx: Contexto = Depends(requiere("usuarios.gestionar"))):
    try:
        return usuarios.usuario_dict(ctx.bd, usuarios.desbloquear(ctx.bd, usuario_id, ctx.actor))
    except ErrorUsuarios as e:
        raise _error(e) from None


@r.post("/personas/{usuario_id}/restablecer")
def enviar_restablecimiento(usuario_id: int, request: Request, tareas: BackgroundTasks,
                            ctx: Contexto = Depends(requiere("usuarios.gestionar"))):
    """Administración envía a la persona un enlace para restablecer su contraseña (nunca la ve ni la elige)."""
    limitar(f"restablecer-admin:{ctx.usuario.id}", 10, 900)
    try:
        mensaje = usuarios.restablecer_por_admin(ctx.bd, usuario_id, ctx.actor, ip_de(request))
    except ErrorUsuarios as e:
        raise _error(e) from None
    tareas.add_task(correo.enviar, *mensaje)
    return {"ok": True, "entrega": correo.entrega(), "mensaje": f"Enlace enviado a {mensaje[0]}."}


@r.post("/personas/mi-contrasena")
def mi_contrasena(datos: CambioContrasenaIn, tareas: BackgroundTasks, ctx: Contexto = Depends(contexto)):
    """Cada persona cambia su propia contraseña; se cierran sus sesiones en otros dispositivos."""
    limitar(f"mi-contrasena:{ctx.usuario.id}", 5, 900)   # contra el ensayo de la contraseña actual con una sesión robada
    try:
        usuarios.cambiar_contrasena(ctx.bd, ctx.usuario, datos.actual, datos.nueva, sesion_actual=ctx.sesion.id)
    except ErrorUsuarios as e:
        raise _error(e) from None
    tareas.add_task(correo.enviar, *usuarios.aviso_cambio_contrasena(ctx.usuario))
    return {"ok": True, "mensaje": "Contraseña actualizada. Se cerraron sus sesiones en otros dispositivos."}
