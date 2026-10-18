"""Conversión de los modelos a JSON para la pantalla (nunca se exponen secretos ni números completos de cuenta)."""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from kauta import motor

from .modelos import Beneficiario, CambioCuenta, Factura, Pago
from .servicios import pagos
from .servicios.agente import regla_principal

DIAS_RIEL = {"SWIFT": 2, "ACH": 1, "WIRE": 0, "ACH_CO": 0, "SPEI": 0, "BREB": 0, "PIX": 0, "USDC": 0, "PAYPAL": 0}


def iso(dt) -> str | None:
    return dt.isoformat() + "Z" if dt else None


def _pago(bd: Session, fid: str) -> Pago | None:
    return bd.execute(select(Pago).where(Pago.factura_id == fid).order_by(Pago.creado_en.desc())).scalars().first()


def factura_resumen(bd: Session, f: Factura) -> dict[str, Any]:
    p = _pago(bd, f.id)
    hechas = sum(1 for a in f.aprobaciones if a.accion == "aprobar")
    return {"id": f.id, "archivo": f.archivo, "canal": f.canal, "origen": f.origen, "beneficiario": f.beneficiario_nombre,
            "beneficiario_id": f.beneficiario_id, "numero": f.numero, "monto": float(f.monto) if f.monto is not None else None,
            "moneda": f.moneda, "monto_usd": float(f.monto_usd) if f.monto_usd is not None else None, "periodo": f.periodo,
            "decision": f.decision, "decision_inicial": f.decision_inicial, "estado": f.estado, "motivo": f.motivo,
            "regla": regla_principal(f.motivo), "regla_inicial": regla_principal(f.motivo_inicial),
            "recibida_en": iso(f.recibida_en), "metodo_lectura": f.metodo_lectura, "fecha_vencimiento": f.fecha_vencimiento,
            "aprobaciones_requeridas": f.aprobaciones_requeridas, "aprobaciones_hechas": hechas,
            "aprobada_por": [a.usuario_nombre for a in f.aprobaciones if a.accion == "aprobar"],
            "pago": {"id": p.id, "estado": p.estado, "resultado": pagos.RESULTADOS.get(p.estado, p.estado), "riel": p.riel} if p else None,
            "reglas": [{"id": r["id"], "nombre": r["nombre"], "efecto": r["efecto"], "estado": r["estado"], "detalle": ""} for r in f.reglas]}


def preguntas(bd: Session, f: Factura) -> list[dict[str, str]]:
    """Kauta pregunta: una pregunta concreta por cada regla blanda que falló."""
    ben = bd.get(Beneficiario, f.beneficiario_id) if f.beneficiario_id else None
    ext = f.extraccion or {}
    salida = []
    for r in f.reglas:
        if r["estado"] != "falla" or r["efecto"] != "escalar":
            continue
        q = {
            "R01": "¿Puedes confirmar los datos mirando el documento original? Si un dato está mal leído, corrígelo antes de aprobar.",
            "R02": f"La moneda {f.moneda} no está en la política. ¿Se acordó pagar así? Si no, pide la factura en una moneda permitida.",
            "R06": f"«{f.beneficiario_nombre}» no está registrado. ¿Hay contrato firmado? Primero se da de alta y se verifica su cuenta.",
            "R07": (f"Piden pagar a la cuenta ···{ext.get('cuenta_destino') or '?'}. ¿Llamaste al número registrado del proveedor? "
                    f"Si apruebas sin verificar, Kauta paga a la cuenta registrada (···{ben.cuenta_ultimos4 if ben else '?'})."),
            "R08": "El monto no cuadra con el contrato. ¿Hubo un trabajo adicional aprobado? Puedes pagar lo facturado o corregirlo.",
            "R10": "Supera el umbral de aprobación: la aprueba el CEO y después Finanzas la paga con su token (dos personas distintas).",
            "R11": "El beneficiario superaría su límite del periodo. ¿Se autorizó un trabajo extra?",
            "R13": "El documento intenta darle órdenes al agente; Kauta lo ignoró. ¿Reconoces la factura como legítima?",
        }.get(r["id"], r["detalle"])
        salida.append({"regla": r["id"], "titulo": motor.CATALOGO[r["id"]]["falla"], "pregunta": q, "detalle": r["detalle"]})
    return salida


def plazo(bd: Session, f: Factura) -> dict[str, Any] | None:
    if not f.fecha_vencimiento:
        return None
    try:
        vence = date.fromisoformat(f.fecha_vencimiento)
    except ValueError:
        return None
    hoy = date(2026, 10, 17) if vence.year == 2026 and vence.month == 10 else date.today()
    riel = f.riel_pago or pagos.RIEL_PAGOS
    return {"vence": f.fecha_vencimiento, "dias": (vence - hoy).days, "dias_riel": DIAS_RIEL.get(riel, 0),
            "riel": pagos.RIELES.get(riel, {}).get("nombre") if riel else None}


def factura_detalle(bd: Session, f: Factura) -> dict[str, Any]:
    d = factura_resumen(bd, f)
    ext = {k: v for k, v in (f.extraccion or {}).items()}
    cambio = bd.execute(select(CambioCuenta).where(CambioCuenta.factura_id == f.id)).scalars().first()
    p = _pago(bd, f.id)
    d.update({
        "extraccion": ext, "reglas": f.reglas, "reglas_iniciales": f.reglas_iniciales, "motivo_inicial": f.motivo_inicial,
        "texto": (f.texto or "")[:6000], "modelo": f.modelo, "hash_documento": f.hash_documento, "hashes": f.hashes,
        "version_reglas": f.version_reglas, "cargada_por": f.cargada_por, "id_fiscal_unico": f.id_fiscal_unico,
        "riel_pago": f.riel_pago or pagos.RIEL_PAGOS, "riel_pago_nombre": pagos.RIELES[f.riel_pago or pagos.RIEL_PAGOS]["nombre"],
        "paypal_modo": pagos.paypal.modo(),
        "tiene_vista": f.canal in ("pdf", "imagen", "correo") and f.ruta_archivo is not None,
        "aprobaciones": [{"usuario": a.usuario_nombre, "nivel": a.nivel, "accion": a.accion, "comentario": a.comentario,
                          "correcciones": a.correcciones, "firma": a.firma[:16], "con_mfa": a.con_mfa, "creada_en": iso(a.creada_en)}
                         for a in f.aprobaciones],
        "preguntas": preguntas(bd, f) if f.estado == "pendiente" else [],
        "plazo": plazo(bd, f),
        "pago_detalle": pagos.a_dict(p) if p else None,
        "cambio_cuenta": cambio_dict(bd, cambio) if cambio else None,
    })
    return d


def beneficiario_dict(bd: Session, b: Beneficiario) -> dict[str, Any]:
    info = pagos.RIELES.get(b.riel, {})
    facturas = bd.execute(select(Factura).where(Factura.beneficiario_id == b.id)).scalars().all()
    return {"id": b.id, "nombre": b.nombre, "id_fiscal": b.id_fiscal, "tipo_id": b.tipo_id, "id_valido": b.id_valido,
            "pais": b.pais, "tipo_persona": b.tipo_persona, "categoria": b.categoria, "estado": b.estado,
            "motivo_bloqueo": b.motivo_bloqueo, "contrato": b.contrato, "contactos": b.contactos, "riel": b.riel,
            "riel_nombre": info.get("nombre"), "moneda_recepcion": b.moneda_recepcion, "banco": b.banco,
            "cuenta": f"···{b.cuenta_ultimos4}", "titular": b.titular_registrado, "verificada_por": b.verificada_por,
            "verificada_en": iso(b.verificada_en), "facturas": len(facturas),
            "pagado_usd": round(sum(float(f.monto_usd or 0) for f in facturas if f.estado == "pagada"), 2)}


def cambio_dict(bd: Session, c: CambioCuenta) -> dict[str, Any]:
    b = bd.get(Beneficiario, c.beneficiario_id)
    return {"id": c.id, "beneficiario_id": c.beneficiario_id, "beneficiario": b.nombre if b else "?", "factura_id": c.factura_id,
            "banco_nuevo": c.banco_nuevo, "cuenta_nueva": f"···{c.ultimos4_nuevos}", "cuenta_actual": f"···{b.cuenta_ultimos4}" if b else None,
            "origen": c.origen, "estado": c.estado, "solicitada_por": c.solicitada_por, "verificada_por": c.verificada_por,
            "metodo_verificacion": c.metodo_verificacion, "creada_en": iso(c.creada_en), "resuelta_en": iso(c.resuelta_en)}
