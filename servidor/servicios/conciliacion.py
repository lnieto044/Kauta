"""
Conciliación del periodo: qué llegó, qué decidió Kauta, quién aprobó, qué se pagó, por dónde, cuánto costó y por qué.

Reemplaza la hoja de cálculo que finanzas arma a mano cada mes. Sale en CSV para Excel en español: separador «;»,
coma decimal y BOM UTF-8 (así abre con tildes y columnas correctas sin importar nada).
"""
from __future__ import annotations

import csv
import io
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..modelos import Factura, Pago
from . import agente

COLUMNAS = ["Factura", "Número", "Recibida", "Canal", "Proveedor", "Moneda", "Monto factura", "Monto USD", "Decisión de Kauta",
            "Regla principal", "Estado", "Aprobada por", "Pago", "Riel", "Referencia del pago", "Estado del pago",
            "Pagado USD", "Comisión USD", "Costo de cambio USD", "Fecha del pago", "Motivo"]
DECISION = {"pagar": "Pagar", "escalar": "Preguntar a una persona", "frenar": "Frenar"}


def _num(v: Decimal | float | None) -> str:
    return "" if v is None else f"{Decimal(str(v)):.2f}".replace(".", ",")


def generar(bd: Session, periodo: str | None = None) -> tuple[str, bytes]:
    reglas = agente.reglas_vigentes(bd)
    periodo = periodo or reglas["periodo_actual"]
    pagos: dict[str, Pago] = {}
    for p in bd.execute(select(Pago).order_by(Pago.creado_en, Pago.id)).scalars():
        pagos[p.factura_id] = p                                   # el último intento de cada factura
    salida = io.StringIO()
    w = csv.writer(salida, delimiter=";", lineterminator="\r\n")
    w.writerow(COLUMNAS)
    fs = bd.execute(select(Factura).where(Factura.periodo == periodo).order_by(Factura.recibida_en, Factura.id)).scalars()
    for f in fs:
        p = pagos.get(f.id)
        aprobaron = ", ".join(a.usuario_nombre for a in f.aprobaciones if a.accion == "aprobar")
        w.writerow([
            f.id, f.numero or "", f.recibida_en.strftime("%Y-%m-%d %H:%M") if f.recibida_en else "", f.canal,
            f.beneficiario_nombre or "", f.moneda or "", _num(f.monto), _num(f.monto_usd),
            DECISION.get(f.decision_inicial or "", f.decision_inicial or ""), agente.regla_principal(f.motivo_inicial or ""),
            f.estado, aprobaron or ("Kauta (automático)" if f.estado == "pagada" else ""),
            p.id if p else "", p.riel if p else "", p.referencia if p else "", p.estado if p else "",
            _num(p.monto_usd) if p and p.estado == "liquidado" else "", _num(p.comision_usd) if p else "",
            _num(p.costo_fx_usd) if p else "", p.liquidado_en.strftime("%Y-%m-%d %H:%M") if p and p.liquidado_en else "",
            (f.motivo or "").replace("\n", " "),
        ])
    return f"kauta-conciliacion-{periodo}.csv", "﻿".encode("utf-8") + salida.getvalue().encode("utf-8")
