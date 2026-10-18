"""
Sesiones del lado del servidor (OWASP ASVS V3/V7).

  * Token opaco de 256 bits en una cookie HttpOnly + SameSite=Strict (+ Secure y prefijo __Host- con HTTPS).
    En la base de datos solo se guarda su SHA-256: un volcado de la base no entrega sesiones válidas.
  * Expira por inactividad (30 min) y por duración máxima (8 h). Se crea una sesión nueva en cada
    inicio de sesión (evita la fijación de sesión) y se revoca al cerrarla.
  * CSRF: token sincronizado por sesión que el navegador envía en la cabecera X-CSRF-Token en toda
    petición que cambia datos, y además verificación de la cabecera Origin.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import timedelta

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from ..config import CONFIG
from ..db import obtener_bd
from ..modelos import Sesion, Usuario, ahora
from .permisos import tiene

METODOS_SEGUROS = {"GET", "HEAD", "OPTIONS"}


def _id(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def ip_de(request: Request) -> str:
    return (request.client.host if request.client else "desconocida")[:64]


def crear(bd: Session, usuario: Usuario, request: Request, response: Response) -> Sesion:
    token = secrets.token_urlsafe(32)
    s = Sesion(id=_id(token), usuario_id=usuario.id, csrf=secrets.token_urlsafe(32), creada_en=ahora(),
               ultima_actividad=ahora(), expira_en=ahora() + timedelta(hours=CONFIG.duracion_max_h), ip=ip_de(request),
               agente_usuario=(request.headers.get("user-agent") or "")[:300])
    bd.add(s)
    response.set_cookie(CONFIG.nombre_cookie, token, httponly=True, secure=CONFIG.cookie_segura, samesite="strict",
                        path="/", max_age=CONFIG.duracion_max_h * 3600)
    return s


def revocar_actual(bd: Session, request: Request) -> None:
    """Revoca en la base la sesión que trae este navegador, si trae una."""
    token = request.cookies.get(CONFIG.nombre_cookie)
    if token:
        s = bd.get(Sesion, _id(token))
        if s:
            s.revocada = True


def cerrar(bd: Session, request: Request, response: Response) -> None:
    revocar_actual(bd, request)
    response.delete_cookie(CONFIG.nombre_cookie, path="/", secure=CONFIG.cookie_segura, httponly=True, samesite="strict")


@dataclass
class Contexto:
    usuario: Usuario
    sesion: Sesion
    bd: Session

    @property
    def actor(self) -> str:
        return f"{self.usuario.nombre} ({self.usuario.cargo})"


def contexto(request: Request, bd: Session = Depends(obtener_bd)) -> Contexto:
    token = request.cookies.get(CONFIG.nombre_cookie)
    if not token:
        raise HTTPException(401, "Inicie sesión para continuar.")
    s = bd.get(Sesion, _id(token))
    t = ahora()
    if (not s or s.revocada or s.expira_en < t
            or s.ultima_actividad < t - timedelta(minutes=CONFIG.inactividad_min)):
        raise HTTPException(401, "La sesión expiró. Inicie sesión de nuevo.")
    if request.method not in METODOS_SEGUROS:
        if not hmac.compare_digest(request.headers.get("x-csrf-token", ""), s.csrf):
            raise HTTPException(403, "Falta el token anti-CSRF o no es válido.")
    if not s.usuario.activo:
        raise HTTPException(401, "Usuario desactivado.")
    if (t - s.ultima_actividad).total_seconds() > 20:
        s.ultima_actividad = t
        bd.commit()
    request.state.actor = s.usuario.correo
    return Contexto(usuario=s.usuario, sesion=s, bd=bd)


def requiere(permiso: str):
    """Dependencia de FastAPI: niega por defecto si el rol no tiene el permiso."""
    def dependencia(ctx: Contexto = Depends(contexto)) -> Contexto:
        if not tiene(ctx.usuario.rol, permiso):
            raise HTTPException(403, f"Su rol ({ctx.usuario.rol}) no permite esta acción ({permiso}).")
        return ctx
    return dependencia
