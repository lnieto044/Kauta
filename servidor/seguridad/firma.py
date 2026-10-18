"""
Firma de transacciones (vinculación dinámica, como exige PSD2 para pagos):
cada aprobación y cada orden de pago se firman con HMAC-SHA256 sobre los datos EXACTOS que la
persona vio (factura, beneficiario, monto, moneda, cuenta, huella del documento, versión de reglas).
Antes de mover dinero se vuelven a verificar todas las firmas: si alguien altera el monto o la cuenta
después de aprobar —incluso directamente en la base de datos— la firma deja de coincidir y el pago se bloquea.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from ..config import CONFIG


def canonico(datos: dict[str, Any]) -> bytes:
    return json.dumps(datos, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")


def firmar(datos: dict[str, Any]) -> str:
    return hmac.new(CONFIG.clave_firma, canonico(datos), hashlib.sha256).hexdigest()


def verificar(datos: dict[str, Any], firma: str) -> bool:
    return hmac.compare_digest(firmar(datos), firma or "")


def huella(datos: dict[str, Any]) -> str:
    """Resumen corto y legible de lo que se firmó (se muestra a la persona)."""
    return hashlib.sha256(canonico(datos)).hexdigest()[:16]
