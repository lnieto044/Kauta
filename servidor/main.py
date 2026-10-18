"""
Kauta · servidor (FastAPI). Arranque:  uvicorn servidor.main:app --port 8000

Sirve la API en /api y la pantalla (React compilada en web/dist) en /.
Documentación interactiva de la API en /api/docs (solo en modo demo).
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from .config import CONFIG, RAIZ
from .db import SesionBD
from .rutas import auth, control, dinero, negocio, personas, simulador
from .seguridad.cabeceras import CabecerasSeguridad
from .servicios import BLOQUEO, semilla
from .servicios.agente import ErrorNegocio

WEB = RAIZ / "web" / "dist"
MAX_CUERPO = (CONFIG.max_archivo_mb + 2) * 1024 * 1024


@asynccontextmanager
async def ciclo_de_vida(_: FastAPI):
    with BLOQUEO, SesionBD() as bd:          # con varias instancias, solo una prepara la base a la vez
        semilla.iniciar(bd, con_set=True)
    yield


app = FastAPI(title="Kauta API", version=CONFIG.version, lifespan=ciclo_de_vida,
              description="Agente de cuentas por pagar: la IA lee, el código decide. Datos ficticios.",
              docs_url="/api/docs" if CONFIG.demo else None, redoc_url=None,
              openapi_url="/api/openapi.json" if CONFIG.demo else None)


class LimiteCuerpo(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        largo = request.headers.get("content-length")
        if largo and largo.isdigit() and int(largo) > MAX_CUERPO:
            return JSONResponse({"detail": "La solicitud es demasiado grande."}, status_code=413)
        return await call_next(request)


app.add_middleware(LimiteCuerpo)
app.add_middleware(CabecerasSeguridad)
for modulo in (auth, negocio, dinero, simulador, control, personas):
    app.include_router(modulo.r)


@app.exception_handler(ErrorNegocio)
async def _negocio(_: Request, e: ErrorNegocio):
    return JSONResponse({"detail": str(e)}, status_code=409)


CAMPOS = {"correo": "El correo", "contrasena": "La contraseña", "nueva": "La contraseña nueva", "actual": "La contraseña actual",
          "nombre": "El nombre", "codigo": "El código", "token": "El enlace", "comentario": "El comentario", "cargo": "El cargo",
          "mensaje": "El mensaje", "motivo": "El motivo", "rol": "El rol"}


def _mensaje(err: dict) -> str:
    """Traduce los errores de validación a frases que entiende quien usa la pantalla."""
    campo = str(err["loc"][-1]) if err.get("loc") else ""
    sujeto = CAMPOS.get(campo, f"El campo «{campo}»")
    ctx, tipo = err.get("ctx") or {}, err.get("type", "")
    if tipo == "missing":
        return f"{sujeto} es obligatorio."
    if tipo == "string_too_short":
        return f"{sujeto} debe tener al menos {ctx.get('min_length')} caracteres."
    if tipo == "string_too_long":
        return f"{sujeto} admite como máximo {ctx.get('max_length')} caracteres."
    if tipo == "string_pattern_mismatch":
        return "Escriba un correo válido, como nombre@empresa.com." if campo == "correo" else f"{sujeto} no tiene el formato esperado."
    if tipo == "literal_error":
        return f"{sujeto} no es una opción válida."
    if tipo == "extra_forbidden":
        return f"El campo «{campo}» no se admite."
    return f"{sujeto}: {err.get('msg', 'valor inválido')}."


@app.exception_handler(RequestValidationError)
async def _validacion(_: Request, e: RequestValidationError):
    return JSONResponse({"detail": " ".join(dict.fromkeys(_mensaje(err) for err in e.errors()[:5]))}, status_code=422)


@app.get("/api/salud", tags=["Control"])
def salud():
    return {"ok": True, "version": CONFIG.version, "modo": CONFIG.modo}


if WEB.exists():
    app.mount("/assets", StaticFiles(directory=WEB / "assets"), name="assets")

    @app.get("/{ruta:path}", include_in_schema=False)
    def pantalla(ruta: str):
        archivo = (WEB / ruta).resolve()
        if ruta and archivo.is_file() and WEB.resolve() in archivo.parents:
            return FileResponse(archivo)
        return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-cache"})
