"""
Cuánto cuesta resolver una factura y dónde se va el dinero, por periodo.

Cada factura suma cuatro costos:
  * Lectura: según cómo se leyó. El XML fiscal, el texto del PDF y el OCR local no cobran por documento; la IA sí
    (tarifa estimada por documento). En modo demo, lo que no es XML se lee con su extracción verificada, sin costo.
  * Revisión humana: cada decisión de una persona (aprobar o rechazar) a una tarifa estimada por minuto.
  * Pago: la comisión y el costo de cambio reales de su pago por PayPal (los pagos devueltos no cobran comisión).
  * Infraestructura: el costo fijo del mes, repartido entre las facturas finales del periodo.
Solo las facturas finales (pagadas, frenadas o rechazadas) entran en el costo por factura; las abiertas se muestran aparte.
Las tarifas son supuestos visibles en la respuesta: nada se presenta como medido si no lo es.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..modelos import Aprobacion, Factura, Pago
from . import agente
from .rendimiento import _fecha, _lunes

TARIFAS = {
    "lectura_usd": {"xml_fiscal": 0.0, "texto_pdf": 0.0, "ocr": 0.0, "referencia": 0.0, "simulador": 0.0, "rechazado": 0.0,
                    "ia": 0.028},
    "revision_minutos": 4, "hora_revision_usd": 30.0, "infraestructura_mes_usd": 30.0,
}
LECTURAS = {"xml_fiscal": "XML fiscal exacto", "texto_pdf": "Texto del PDF", "ocr": "OCR local", "ia": "IA",
            "referencia": "Extracción verificada (modo demo)", "simulador": "Caso de prueba", "rechazado": "Archivo rechazado"}
FINALES = ("pagada", "frenada", "rechazada")
COMPONENTES = [("lectura", "Lectura", "Leer el documento: XML, texto del PDF, OCR o IA"),
               ("revision", "Revisión humana", "Minutos de una persona que aprueba o rechaza"),
               ("pago", "Pago", "Comisión y cambio de PayPal"),
               ("infraestructura", "Infraestructura", "Servidor y base de datos del mes, repartidos")]


def _por_factura(fs: list[Factura], pagos: dict[str, Pago], decisiones: Counter) -> dict[str, dict[str, float | None]]:
    revision = TARIFAS["revision_minutos"] / 60 * TARIFAS["hora_revision_usd"]
    salida = {}
    for f in fs:
        p = pagos.get(f.id)
        pago: float | None = float(p.comision_usd + p.costo_fx_usd) if p and p.estado not in ("devuelto", "negado") else 0.0
        if f.estado == "pagada" and not p:
            pago = None                                      # pagada sin registro de pago: costo desconocido
        salida[f.id] = {"lectura": TARIFAS["lectura_usd"].get(f.metodo_lectura), "revision": decisiones[f.id] * revision,
                        "pago": pago}
    return salida


def _indicadores(fs: list[Factura], costos: dict[str, dict[str, float | None]]) -> dict[str, Any]:
    finales = [f for f in fs if f.estado in FINALES]
    pagadas = [f for f in finales if f.estado == "pagada"]
    suma = lambda clave, lista: sum((costos[f.id][clave] or 0.0) for f in lista)  # noqa: E731
    infra = TARIFAS["infraestructura_mes_usd"] if finales else 0.0
    total = suma("lectura", finales) + suma("revision", finales) + suma("pago", finales) + infra
    casillas = 3 * len(finales)
    conocidas = sum(1 for f in finales for k in ("lectura", "revision", "pago") if costos[f.id][k] is not None)
    con_ia = sum(1 for f in fs if f.metodo_lectura == "ia")
    return {
        "finales": len(finales), "pagadas": len(pagadas), "facturas": len(fs), "con_ia": con_ia,
        "costo_total_usd": round(total, 2),
        "costo_por_factura_usd": round(total / len(finales), 2) if finales else None,
        "costo_pago_usd": round(suma("pago", pagadas) / len(pagadas), 2) if pagadas else None,
        "pago_total_usd": round(suma("pago", pagadas), 2),
        "sin_ia_pct": round(100 * (len(fs) - con_ia) / len(fs), 1) if fs else None,
        "cobertura_pct": round(100 * conocidas / casillas, 1) if casillas else None,
        "casillas": casillas, "casillas_conocidas": conocidas,
        "componentes": {"lectura": round(suma("lectura", finales), 4), "revision": round(suma("revision", finales), 4),
                        "pago": round(suma("pago", finales), 4), "infraestructura": round(infra, 4)},
    }


def calcular(bd: Session, periodo: str | None = None) -> dict[str, Any]:
    reglas = agente.reglas_vigentes(bd)
    todas = bd.execute(select(Factura)).scalars().all()
    periodos = sorted({f.periodo for f in todas} | {reglas["periodo_actual"]})
    periodo = periodo if periodo in periodos else reglas["periodo_actual"]
    pagos: dict[str, Pago] = {}
    for p in bd.execute(select(Pago).order_by(Pago.creado_en, Pago.id)).scalars():
        pagos[p.factura_id] = p                              # el último intento de cada factura
    decisiones = Counter(a.factura_id for a in bd.execute(select(Aprobacion)).scalars() if a.accion in ("aprobar", "rechazar"))
    fs = [f for f in todas if f.periodo == periodo]
    costos = _por_factura(fs, pagos, decisiones)
    ind = _indicadores(fs, costos)
    i = periodos.index(periodo)
    previo = periodos[i - 1] if i > 0 else None
    fs_prev = [f for f in todas if f.periodo == previo] if previo else []
    ind_prev = _indicadores(fs_prev, _por_factura(fs_prev, pagos, decisiones)) if fs_prev else None

    finales = [f for f in fs if f.estado in FINALES]
    cuota = TARIFAS["infraestructura_mes_usd"] / len(finales) if finales else 0.0
    costo_de = lambda f: sum((costos[f.id][k] or 0.0) for k in ("lectura", "revision", "pago")) + cuota  # noqa: E731

    # Por canal: cuánto cuesta en promedio resolver una factura según por dónde llegó
    canales: dict[str, list[float]] = defaultdict(list)
    for f in finales:
        canales[f.canal].append(costo_de(f))
    por_canal = sorted(({"canal": c, "facturas": len(v), "costo_medio_usd": round(sum(v) / len(v), 2)} for c, v in canales.items()),
                       key=lambda x: -x["costo_medio_usd"])

    # Por semana de llegada
    sem: dict[date, list[float]] = defaultdict(list)
    for f in finales:
        sem[_lunes(_fecha(f))].append(costo_de(f))
    por_semana = [{"desde": d.isoformat(), "hasta": (d + timedelta(days=6)).isoformat(), "facturas": len(v),
                   "costo_usd": round(sum(v), 2), "costo_medio_usd": round(sum(v) / len(v), 2)} for d, v in sorted(sem.items())]

    # Cómo se leyeron (todas las del periodo)
    lecturas = Counter(f.metodo_lectura for f in fs)
    desglose = [{"metodo": m, "nombre": LECTURAS.get(m, m), "facturas": n,
                 "costo_usd": round(n * (TARIFAS["lectura_usd"].get(m) or 0.0), 4)}
                for m, n in sorted(lecturas.items(), key=lambda x: -x[1])]

    abiertas = [f for f in fs if f.estado not in FINALES]
    en_curso = {"facturas": len(abiertas), "por_estado": dict(Counter(f.estado for f in abiertas)),
                "costo_conocido_usd": round(sum(sum((costos[f.id][k] or 0.0) for k in ("lectura", "revision", "pago"))
                                                for f in abiertas), 2)}
    return {
        "periodo": periodo, "periodos": periodos, "anterior": previo if ind_prev else None,
        "indicadores": ind, "indicadores_anteriores": ind_prev,
        "componentes": [{"clave": k, "nombre": n, "detalle": d, "valor_usd": ind["componentes"][k]} for k, n, d in COMPONENTES],
        "lectura": desglose, "por_canal": por_canal, "por_semana": por_semana, "en_curso": en_curso,
        "tarifas": {"lectura_ia_usd": TARIFAS["lectura_usd"]["ia"], "revision_minutos": TARIFAS["revision_minutos"],
                    "hora_revision_usd": TARIFAS["hora_revision_usd"], "infraestructura_mes_usd": TARIFAS["infraestructura_mes_usd"]},
        "calculado_en": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
