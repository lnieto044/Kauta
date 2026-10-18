"""
La wallet de Kauta: libro mayor de doble partida en USD.

Qué es una wallet aquí: la cuenta digital de la empresa (en dólares, con salida a monedas locales)
desde la que Kauta paga. Se modela como un conjunto de cuentas y cada movimiento es un ASIENTO
con débitos y créditos que siempre suman lo mismo (nada aparece ni desaparece).

    operativa  ──fondeo del periodo──▶  cxp (sub-wallet de cuentas por pagar)
    cxp        ──reserva──▶  reservas  ──envío──▶  tránsito  ──liquidación──▶  proveedores
    operativa  ──comisión del riel y costo cambiario──▶  comisiones / costos_fx
    tránsito   ──devolución──▶  cxp  (si el riel rechaza el pago)

El saldo de «cxp» es exactamente lo que el motor llama «saldo del periodo» (regla R12).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..modelos import Asiento, CuentaWallet, Movimiento

CERO = Decimal("0.00")
CUENTAS = [
    ("operativa", "Cuenta operativa USD", "activo", "Cuenta principal de la empresa en dólares."),
    ("cxp", "Sub-wallet de cuentas por pagar", "activo", "Se fondea al inicio de cada periodo con el presupuesto de pagos (regla R12)."),
    ("reservas", "Fondos reservados", "activo", "Dinero apartado para pagos aprobados que aún no salen."),
    ("transito", "Pagos en tránsito", "activo", "Pagos enviados al riel que todavía no se liquidan."),
    ("proveedores", "Pagado a proveedores", "externa", "Salidas liquidadas hacia los beneficiarios."),
    ("comisiones", "Comisiones de rieles", "gasto", "Lo que cuesta enviar cada pago."),
    ("costos_fx", "Costo cambiario", "gasto", "Diferencial al convertir dólares a moneda local."),
    ("fondeo", "Fondeo externo", "externa", "Origen de los depósitos simulados a la cuenta operativa."),
]


def crear_cuentas(bd: Session) -> None:
    for codigo, nombre, tipo, desc in CUENTAS:
        if not bd.get(CuentaWallet, codigo):
            bd.add(CuentaWallet(codigo=codigo, nombre=nombre, tipo=tipo, descripcion=desc))
    bd.flush()


def asiento(bd: Session, tipo: str, descripcion: str, referencia: str | None, periodo: str,
            lineas: list[tuple[str, Decimal, Decimal]]) -> Asiento:
    debitos = sum((Decimal(d) for _, d, _ in lineas), CERO)
    creditos = sum((Decimal(c) for _, _, c in lineas), CERO)
    if debitos != creditos or debitos <= 0:
        raise ValueError(f"Asiento descuadrado: débitos {debitos} ≠ créditos {creditos}.")
    a = Asiento(tipo=tipo, descripcion=descripcion, referencia=referencia, periodo=periodo)
    bd.add(a)
    for cuenta, d, c in lineas:
        bd.add(Movimiento(asiento=a, cuenta=cuenta, debito=Decimal(d), credito=Decimal(c)))
    bd.flush()
    return a


def transferir(bd: Session, tipo: str, descripcion: str, referencia: str | None, periodo: str,
               desde: str, hacia: str, monto: Decimal) -> Asiento:
    monto = Decimal(monto).quantize(Decimal("0.01"))
    return asiento(bd, tipo, descripcion, referencia, periodo, [(hacia, monto, CERO), (desde, CERO, monto)])


def saldo(bd: Session, cuenta: str) -> Decimal:
    d, c = bd.execute(select(func.coalesce(func.sum(Movimiento.debito), 0), func.coalesce(func.sum(Movimiento.credito), 0))
                      .where(Movimiento.cuenta == cuenta)).one()
    return (Decimal(d) - Decimal(c)).quantize(Decimal("0.01"))


def saldos(bd: Session) -> dict[str, Decimal]:
    return {codigo: saldo(bd, codigo) for codigo, *_ in CUENTAS}


def verificar_libro(bd: Session) -> dict[str, Any]:
    descuadrados = []
    for a in bd.execute(select(Asiento)).scalars():
        d = sum((m.debito for m in a.movimientos), CERO)
        c = sum((m.credito for m in a.movimientos), CERO)
        if d != c:
            descuadrados.append(a.id)
    total = sum(saldos(bd).values(), CERO)
    return {"ok": not descuadrados and total == 0, "asientos_descuadrados": descuadrados, "suma_de_saldos": str(total),
            "mensaje": "Libro cuadrado: cada asiento tiene débitos = créditos y la suma de todas las cuentas es cero."
            if not descuadrados and total == 0 else "El libro no cuadra: revise los asientos señalados."}


def periodos_fondeados(bd: Session) -> list[str]:
    return [a.referencia.split("FONDEO-", 1)[1] for a in bd.execute(
        select(Asiento).where(Asiento.referencia.like("FONDEO-____-__")).order_by(Asiento.id)).scalars()]


def asegurar_fondeo(bd: Session, periodo: str, presupuesto: Decimal, permitidos: list[str]) -> bool:
    """La sub-wallet de cuentas por pagar se fondea una vez por periodo con el presupuesto vigente."""
    if periodo not in permitidos or periodo in periodos_fondeados(bd):
        return False
    transferir(bd, "fondeo", f"Fondeo de la sub-wallet de cuentas por pagar para {periodo}", f"FONDEO-{periodo}", periodo,
               "operativa", "cxp", presupuesto)
    return True


def resumen(bd: Session) -> dict[str, Any]:
    s = saldos(bd)
    cuentas = [{"codigo": c.codigo, "nombre": c.nombre, "tipo": c.tipo, "descripcion": c.descripcion,
                "saldo": float(abs(s[c.codigo]) if c.tipo == "externa" else s[c.codigo])}
               for c in bd.execute(select(CuentaWallet)).scalars()]
    orden = {codigo: i for i, (codigo, *_) in enumerate(CUENTAS)}
    cuentas.sort(key=lambda x: orden.get(x["codigo"], 99))
    return {"cuentas": cuentas, "disponible_cxp": float(s["cxp"]), "reservado": float(s["reservas"]),
            "en_transito": float(s["transito"]), "pagado": float(s["proveedores"]), "operativa": float(s["operativa"]),
            "costos": float(s["comisiones"] + s["costos_fx"])}
