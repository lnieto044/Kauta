"""Simulador de pagos: escenarios, crear factura y simular un año."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..config import CONFIG
from ..esquemas import SimAnioIn, SimFacturaIn
from ..seguridad.limites import limitar
from ..seguridad.sesiones import Contexto, requiere
from ..servicios import agente, pagos, simulador
from ..servicios.agente import ErrorNegocio
from .. import vistas


def _solo_demo() -> None:
    """Los datos de prueba solo existen en modo demo; en producción estas rutas no existen."""
    if not CONFIG.demo:
        raise HTTPException(404)


# Herramienta de datos de prueba (la usan las pruebas automáticas y la demo); ya no tiene pantalla propia
r = APIRouter(prefix="/api/simulador", tags=["Simulador"], dependencies=[Depends(_solo_demo)])


@r.get("/escenarios")
def escenarios(ctx: Contexto = Depends(requiere("ver"))):
    reglas = agente.reglas_vigentes(ctx.bd)
    periodos = [{"periodo": p, "disponible": float(simulador.disponible_periodo(ctx.bd, reglas, p))}
                for p in simulador.periodos_simulables(reglas)]
    return {"escenarios": simulador.ESCENARIOS, "rieles": pagos.rieles_publicos(),
            "periodos": periodos, "proveedores": agente.beneficiarios_motor(ctx.bd)}


@r.get("/escenarios/{codigo}")
def preparar(codigo: str, periodo: str | None = None, ctx: Contexto = Depends(requiere("simulador.usar"))):
    try:
        return simulador.escenario(ctx.bd, codigo, periodo)
    except ErrorNegocio as e:
        raise HTTPException(409, str(e))


@r.post("/factura")
def crear(datos: SimFacturaIn, ctx: Contexto = Depends(requiere("simulador.usar"))):
    limitar(f"sim:{ctx.usuario.id}", 60, 60)
    if datos.riel and datos.riel not in pagos.RIELES:
        raise HTTPException(422, "Riel desconocido.")
    try:
        f = simulador.crear_factura(ctx.bd, datos.model_dump(), ctx.actor, f"caso de prueba:{ctx.usuario.correo}")
    except ErrorNegocio as e:
        raise HTTPException(409, str(e))
    return vistas.factura_detalle(ctx.bd, f)


@r.post("/anio")
def anio(datos: SimAnioIn, ctx: Contexto = Depends(requiere("simulador.usar"))):
    limitar(f"sim-anio:{ctx.usuario.id}", 10, 60)
    return simulador.simular_anio(ctx.bd, datos.meses, datos.trampas_pct, datos.semilla)
