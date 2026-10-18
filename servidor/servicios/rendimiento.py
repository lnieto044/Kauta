"""
Rendimiento y costos de un periodo, con los datos reales de la base:

  * Indicadores de la última semana con facturas frente a la semana anterior (variación con flecha).
  * Tendencia diaria: lo pagado acumulado frente al ritmo del presupuesto del mes.
  * Cascada: de todo lo facturado a lo que se pagó (lo frenado, lo que espera y lo devuelto se restan).
Las semanas y los días van en hora de Bogotá. Nada se inventa: si no hay semana anterior, la variación no se muestra.
"""
from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from kauta import motor

from ..modelos import Factura, Pago
from . import agente

BOGOTA = timedelta(hours=-5)


def _fecha(f: Factura) -> date:
    """Cuándo cuenta la factura dentro de su periodo: el día en que llegó o, si llegó en otro mes, su fecha de emisión."""
    a, m = (int(x) for x in f.periodo.split("-"))
    llegada = (f.recibida_en + BOGOTA).date()
    if (llegada.year, llegada.month) == (a, m):
        return llegada
    try:
        emision = date.fromisoformat((f.extraccion or {}).get("fecha_emision") or "")
        if (emision.year, emision.month) == (a, m):
            return emision
    except ValueError:
        pass
    return date(a, m, 1)


def _lunes(d: date) -> date:
    return d - timedelta(days=d.weekday())


def calcular(bd: Session, periodo: str | None = None) -> dict[str, Any]:
    reglas = agente.reglas_vigentes(bd)
    todas = bd.execute(select(Factura)).scalars().all()
    periodos = sorted({f.periodo for f in todas} | {reglas["periodo_actual"]})
    periodo = periodo if periodo in periodos else reglas["periodo_actual"]
    fs = [f for f in todas if f.periodo == periodo]
    pagos: dict[str, Pago] = {}
    for p in bd.execute(select(Pago).order_by(Pago.creado_en, Pago.id)).scalars():
        pagos[p.factura_id] = p                      # el último intento de cada factura
    usd = lambda f: float(f.monto_usd or 0)          # noqa: E731

    # ---------------------------------------------------------------- semana contra semana
    base = {"recibidas": 0, "autonomas": 0, "pagadas": 0, "pagado_usd": 0.0, "protegido_usd": 0.0, "costos_usd": 0.0, "pagos": 0}
    sem: dict[date, dict[str, Any]] = defaultdict(lambda: dict(base))
    for f in fs:
        s = sem[_lunes(_fecha(f))]
        s["recibidas"] += 1
        s["autonomas"] += f.decision_inicial in ("pagar", "frenar")
        if f.estado == "pagada":
            s["pagadas"] += 1
            s["pagado_usd"] += usd(f)
        if f.estado in ("frenada", "rechazada"):
            s["protegido_usd"] += usd(f)
        p = pagos.get(f.id)
        if p and p.estado not in ("devuelto", "negado"):
            s["costos_usd"] += float(p.comision_usd + p.costo_fx_usd)
            s["pagos"] += 1
    semanas = []
    for lunes, s in sorted(sem.items()):
        semanas.append({**s, "desde": lunes.isoformat(), "hasta": (lunes + timedelta(days=6)).isoformat(),
                        "pagado_usd": round(s["pagado_usd"], 2), "protegido_usd": round(s["protegido_usd"], 2),
                        "costos_usd": round(s["costos_usd"], 2),
                        "autonomia_pct": round(100 * s["autonomas"] / s["recibidas"], 1) if s["recibidas"] else None,
                        "costo_medio_usd": round(s["costos_usd"] / s["pagos"], 2) if s["pagos"] else None})
    actual = semanas[-1] if semanas else None
    anterior = None
    if actual:
        previo = (date.fromisoformat(actual["desde"]) - timedelta(days=7)).isoformat()
        anterior = next((s for s in semanas if s["desde"] == previo), None)

    def kpi(clave: str, nombre: str, unidad: str, mejor: str | None, ayuda: str) -> dict[str, Any]:
        return {"clave": clave, "nombre": nombre, "unidad": unidad, "mejor": mejor, "ayuda": ayuda,
                "actual": actual[clave] if actual else None, "anterior": anterior[clave] if anterior else None}

    kpis = [
        kpi("pagado_usd", "Pagado", "usd", None, "Facturas pagadas, por la semana en que llegaron"),
        kpi("autonomia_pct", "Resueltas sin intervención", "pct", "sube", "Kauta pagó o frenó sola, sin esperar a una persona"),
        kpi("protegido_usd", "Dinero protegido", "usd", None, "Facturas frenadas o rechazadas por romper una regla"),
        kpi("recibidas", "Facturas recibidas", "num", None, "Documentos que llegaron por correo, chat, PDF, foto o XML"),
    ]

    # ---------------------------------------------------------------- tendencia diaria del gasto
    a, m = (int(x) for x in periodo.split("-"))
    dias = calendar.monthrange(a, m)[1]
    presupuesto = float(motor.presupuesto_de(reglas, periodo))
    por_dia: dict[int, float] = defaultdict(float)
    for f in fs:
        if f.estado == "pagada":
            por_dia[_fecha(f).day] += usd(f)
    ultimo = max((_fecha(f).day for f in fs), default=0)
    acumulado, tendencia = 0.0, []
    for d in range(1, dias + 1):
        acumulado += por_dia.get(d, 0.0)
        tendencia.append({"dia": d, "fecha": date(a, m, d).isoformat(), "pagado": round(acumulado, 2) if d <= ultimo else None,
                          "ritmo": round(presupuesto * d / dias, 2)})

    # ---------------------------------------------------------------- cascada: de lo facturado a lo pagado
    suma = lambda estado: round(sum(usd(f) for f in fs if f.estado == estado), 2)  # noqa: E731
    cascada = [{"clave": "facturado", "nombre": "Facturado", "valor": round(sum(usd(f) for f in fs), 2), "tipo": "total"}]
    for estado, nombre, tipo in (("frenada", "Frenado por reglas", "frenado"), ("rechazada", "Rechazado", "otro"),
                                 ("devuelta", "Devuelto por el riel", "otro"), ("pendiente", "Espera aprobación", "espera"),
                                 ("aprobada", "Aprobado, por pagar", "espera")):
        if suma(estado):
            cascada.append({"clave": estado, "nombre": nombre, "valor": -suma(estado), "tipo": tipo})
    cascada.append({"clave": "pagado", "nombre": "Pagado", "valor": suma("pagada"), "tipo": "pagado"})

    costos = sum(float(p.comision_usd + p.costo_fx_usd) for f in fs if (p := pagos.get(f.id)) and p.estado not in ("devuelto", "negado"))
    n_pagos = sum(1 for f in fs if (p := pagos.get(f.id)) and p.estado not in ("devuelto", "negado"))
    return {
        "periodo": periodo, "periodos": periodos, "presupuesto": presupuesto,
        "semana": {"actual": actual["desde"] if actual else None, "anterior": anterior["desde"] if anterior else None},
        "kpis": kpis, "semanas": semanas, "tendencia": tendencia, "cascada": cascada,
        "costos": {"total_usd": round(costos, 2), "pagos": n_pagos,
                   "por_pago_usd": round(costos / n_pagos, 2) if n_pagos else None,
                   "sin_monto": sum(1 for f in fs if f.monto_usd is None)},
    }
