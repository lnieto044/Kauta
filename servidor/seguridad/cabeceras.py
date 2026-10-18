"""
Cabeceras de seguridad HTTP y verificación de Origin.

  * CSP estricta: solo código propio (sin scripts en línea ni de terceros), sin iframes, sin objetos.
  * HSTS con HTTPS, nosniff, Referrer-Policy, Permissions-Policy y aislamiento entre orígenes (COOP/CORP).
  * Las respuestas de la API no se guardan en caché (contienen datos financieros).
  * Toda petición que cambia datos debe venir del origen propio (defensa adicional contra CSRF).
"""
from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from ..config import CONFIG

CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; font-src 'self'; "
       "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
ORIGENES_DEV = {"http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:8000", "http://127.0.0.1:8000"}


class CabecerasSeguridad(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origen = request.headers.get("origin")
            permitidos = {CONFIG.origen, *CONFIG.origenes_extra} | (ORIGENES_DEV if CONFIG.demo else set())
            if origen and origen.rstrip("/") not in permitidos:
                return JSONResponse({"detail": "Origen no permitido."}, status_code=403)
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        respuesta = await call_next(request)
        h = respuesta.headers
        h["Content-Security-Policy"] = CSP + ("; upgrade-insecure-requests" if CONFIG.cookie_segura else "")
        h["X-Content-Type-Options"] = "nosniff"
        h["X-Frame-Options"] = "DENY"
        h["Referrer-Policy"] = "no-referrer"
        h["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()"
        h["Cross-Origin-Opener-Policy"] = "same-origin"
        h["Cross-Origin-Resource-Policy"] = "same-origin"
        h["X-Request-ID"] = rid
        if CONFIG.cookie_segura:
            h["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains; preload"
        if request.url.path.startswith("/api/"):
            h["Cache-Control"] = "no-store"
        return respuesta
