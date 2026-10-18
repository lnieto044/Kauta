"""
Pagos por PayPal en modo de pruebas (sandbox), con la API de Payouts.

  * Solo se habla con el sandbox (api-m.sandbox.paypal.com): el dinero es de prueba. Kauta no tiene modo
    «live» de PayPal; pagar de verdad exige registrar y verificar el correo PayPal de cada proveedor.
  * Credenciales: KAUTA_PAYPAL_CLIENT_ID y KAUTA_PAYPAL_SECRET de una app del sandbox. Nunca se registran
    ni se devuelven a la pantalla. Sin ellas, el riel PayPal funciona simulado, como los demás.
  * Receptor: en pruebas todos los pagos van a la cuenta personal del sandbox (KAUTA_PAYPAL_RECEPTOR), así el
    equipo ve llegar el dinero de prueba. En la pantalla y en la auditoría el correo aparece enmascarado.
  * Cada envío lleva un sender_batch_id único: PayPal rechaza un segundo lote con el mismo identificador.
"""
from __future__ import annotations

import base64
import json
import logging
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal
from typing import Any

from ..config import CONFIG, RAIZ as CONFIG_RAIZ

BASE = "https://api-m.sandbox.paypal.com"
TIEMPO_MAX_S = 20
CONSULTAS = 3            # tras enviar, se consulta el estado unas veces antes de responder
ESPERA_S = 1.2
log = logging.getLogger("uvicorn.error")

# Estado de cada pago dentro del lote de PayPal → estado del pago en Kauta
LIQUIDADO = {"SUCCESS"}
DEVUELTO = {"FAILED", "RETURNED", "BLOCKED", "REFUNDED", "REVERSED", "DENIED"}
# PENDING, ONHOLD, NEW y UNCLAIMED (el receptor aún no lo reclama) siguen «enviado» hasta la próxima consulta

# Rechazos frecuentes de Payouts, explicados en español (PayPal responde en inglés)
EXPLICACION = {
    "INSUFFICIENT_FUNDS": "La cuenta Business del sandbox (la que envía) no tiene saldo suficiente para este pago. "
                          "Agréguele saldo de prueba y reintente el pago.",
    "RECEIVER_UNREGISTERED": "El correo receptor no corresponde a una cuenta del sandbox. Revise KAUTA_PAYPAL_RECEPTOR.",
    "CURRENCY_NOT_SUPPORTED_FOR_RECEIVER": "La cuenta receptora no acepta esta moneda.",
    "AUTHORIZATION_ERROR": "La app del sandbox no tiene activado Payouts. Actívelo en developer.paypal.com.",
    "INSTRUMENT_DECLINED": "PayPal rechazó el medio de pago elegido en la ventana de PayPal. Pruebe con otro o con saldo.",
    "PAYER_ACTION_REQUIRED": "Quien paga todavía no aprobó el pago en la ventana de PayPal.",
    "ORDER_NOT_APPROVED": "Quien paga no aprobó el pago en la ventana de PayPal.",
    "ORDER_ALREADY_CAPTURED": "PayPal ya había cobrado esta orden.",
}

_token: dict[str, Any] = {"valor": None, "vence": 0.0}
_solo_simulado: ContextVar[bool] = ContextVar("kauta_paypal_solo_simulado", default=False)
_candado = threading.Lock()


class ErrorPayPal(Exception):
    """PayPal rechazó la operación o no respondió. El mensaje es apto para mostrar (sin secretos)."""


def _credenciales() -> tuple[str, str, str]:
    return CONFIG.paypal_client_id, CONFIG.paypal_secret, CONFIG.paypal_receptor


def configurado() -> bool:
    cid, secreto, receptor = _credenciales()
    return bool(cid and secreto and receptor)


def modo() -> str:
    return "sandbox" if configurado() else "simulado"


def envio_real() -> bool:
    """Si los pagos de este momento salen de verdad al sandbox (la carga inicial de la demo nunca envía)."""
    return configurado() and not _solo_simulado.get()


@contextmanager
def solo_simulado():
    """Dentro de este bloque los pagos por PayPal se registran sin llamar a la API (carga inicial de datos)."""
    marca = _solo_simulado.set(True)
    try:
        yield
    finally:
        _solo_simulado.reset(marca)


def enmascarar(correo: str) -> str:
    usuario, _, dominio = (correo or "").partition("@")
    return f"{usuario[:3]}···@{dominio}" if dominio else "—"


def receptor_enmascarado() -> str:
    return enmascarar(_credenciales()[2])


def _pedir(metodo: str, ruta: str, cuerpo: dict[str, Any] | None = None, *, token: str | None = None,
           formulario: dict[str, str] | None = None, extra: dict[str, str] | None = None) -> dict[str, Any]:
    """Una llamada HTTP a la API del sandbox. Traduce los errores de PayPal a ErrorPayPal."""
    cid, secreto, _ = _credenciales()
    cabeceras = {"Accept": "application/json", "Accept-Language": "es_ES", **(extra or {})}
    if formulario is not None:
        datos = urllib.parse.urlencode(formulario).encode()
        cabeceras["Content-Type"] = "application/x-www-form-urlencoded"
        cabeceras["Authorization"] = "Basic " + base64.b64encode(f"{cid}:{secreto}".encode()).decode()
    else:
        datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
        cabeceras["Content-Type"] = "application/json"
        cabeceras["Authorization"] = f"Bearer {token}"
    peticion = urllib.request.Request(BASE + ruta, data=datos, headers=cabeceras, method=metodo)
    try:
        with urllib.request.urlopen(peticion, timeout=TIEMPO_MAX_S) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            detalle = json.loads(e.read() or b"{}")
        except ValueError:
            detalle = {}
        nombre = detalle.get("name") or detalle.get("error") or f"HTTP {e.code}"
        mensaje = detalle.get("message") or detalle.get("error_description") or ""
        extra = "; ".join(d.get("issue", "") for d in detalle.get("details", []) if d.get("issue"))
        log.warning("PayPal respondió %s a %s %s (debug_id %s)", e.code, metodo, ruta.split("?")[0], detalle.get("debug_id"))
        if e.code == 401:
            raise ErrorPayPal("PayPal no aceptó las credenciales del sandbox: revise KAUTA_PAYPAL_CLIENT_ID y "
                              "KAUTA_PAYPAL_SECRET.") from None
        if nombre in EXPLICACION:
            raise ErrorPayPal(f"PayPal rechazó la operación ({nombre}). {EXPLICACION[nombre]}") from None
        raise ErrorPayPal(f"PayPal rechazó la operación ({nombre}). {mensaje} {extra}".strip()) from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ErrorPayPal(f"No se pudo conectar con el sandbox de PayPal ({type(e).__name__}).") from None


def _token_acceso() -> str:
    """Token OAuth 2.0 (client credentials), guardado en memoria hasta un minuto antes de vencer."""
    with _candado:
        if _token["valor"] and time.monotonic() < _token["vence"]:
            return _token["valor"]
        r = _pedir("POST", "/v1/oauth2/token", formulario={"grant_type": "client_credentials"})
        _token["valor"] = r.get("access_token")
        _token["vence"] = time.monotonic() + max(0, int(r.get("expires_in", 0)) - 60)
        if not _token["valor"]:
            raise ErrorPayPal("PayPal no entregó un token de acceso.")
        return _token["valor"]


def estado() -> dict[str, Any]:
    """Qué falta para conectar el sandbox. Nunca devuelve las credenciales, solo si están puestas."""
    cid, secreto, receptor = _credenciales()
    return {"modo": modo(), "client_id": bool(cid), "secret": bool(secreto), "receptor": bool(receptor),
            "receptor_valido": "@" in receptor and "." in receptor.rpartition("@")[2],
            "receptor_enmascarado": enmascarar(receptor) if receptor else None,
            "archivo_env": (CONFIG_RAIZ / ".env").exists(), "api": BASE}


def probar() -> tuple[bool, str]:
    """Pide un token nuevo al sandbox: confirma que las credenciales sirven sin crear ningún pago.
    Devuelve (listo para pagar, mensaje)."""
    cid, secreto, receptor = _credenciales()
    if not (cid and secreto):
        faltan = [n for n, ok in (("KAUTA_PAYPAL_CLIENT_ID", cid), ("KAUTA_PAYPAL_SECRET", secreto)) if not ok]
        raise ErrorPayPal(f"Faltan en el archivo .env: {', '.join(faltan)}. Agréguelas y reinicie Kauta.")
    with _candado:
        _token["valor"], _token["vence"] = None, 0.0
    _token_acceso()
    if not receptor:
        return False, ("Las credenciales del sandbox funcionan. Falta KAUTA_PAYPAL_RECEPTOR: el correo de la cuenta Personal "
                       "del sandbox (sb-…@personal.example.com). Mientras tanto, los pagos siguen simulados.")
    if receptor.lower().endswith("@business.example.com"):
        return False, ("Las credenciales funcionan, pero el receptor es una cuenta Business (la que envía). Use el correo de la "
                       "cuenta Personal del sandbox para recibir los pagos de prueba.")
    return True, f"Conexión correcta con el sandbox de PayPal. Los pagos aprobados saldrán a la cuenta de pruebas {receptor_enmascarado()}."


def enviar(lote_id: str, item_id: str, monto: Decimal, moneda: str, nota: str, asunto: str) -> dict[str, Any]:
    """Crea el lote de Payouts con un solo pago. Devuelve el id del lote y su estado inicial."""
    if not configurado():
        raise ErrorPayPal("PayPal no está configurado.")
    receptor = _credenciales()[2]
    cuerpo = {
        "sender_batch_header": {"sender_batch_id": lote_id, "email_subject": asunto[:255], "email_message": nota[:1000]},
        "items": [{"recipient_type": "EMAIL", "receiver": receptor, "sender_item_id": item_id[:30], "note": nota[:4000],
                   "amount": {"value": f"{monto.quantize(Decimal('0.01'))}", "currency": moneda}}],
    }
    r = _pedir("POST", "/v1/payments/payouts", cuerpo, token=_token_acceso())
    cab = r.get("batch_header") or {}
    if not cab.get("payout_batch_id"):
        raise ErrorPayPal("PayPal no devolvió el identificador del lote.")
    return {"lote": cab["payout_batch_id"], "estado_lote": cab.get("batch_status", "PENDING")}


def consultar(lote: str) -> dict[str, Any]:
    """Estado del lote y de su único pago: SUCCESS, PENDING, UNCLAIMED, FAILED, RETURNED…"""
    r = _pedir("GET", f"/v1/payments/payouts/{urllib.parse.quote(lote, safe='')}", token=_token_acceso())
    cab = r.get("batch_header") or {}
    item = (r.get("items") or [{}])[0]
    error = item.get("errors") or {}
    return {"estado_lote": cab.get("batch_status"), "estado": item.get("transaction_status") or cab.get("batch_status"),
            "item": item.get("payout_item_id"), "transaccion": item.get("transaction_id"),
            "error": error.get("message") or error.get("name")}


def esperar_resultado(lote: str) -> dict[str, Any]:
    """Consulta unas pocas veces: en el sandbox el pago suele quedar en firme en segundos."""
    ultimo: dict[str, Any] = {"estado": "PENDING"}
    for i in range(CONSULTAS):
        if i:
            time.sleep(ESPERA_S)
        try:
            ultimo = consultar(lote)
        except ErrorPayPal as e:
            ultimo = {"estado": "PENDING", "error": str(e)}
            continue
        if ultimo["estado"] in LIQUIDADO | DEVUELTO:
            break
    return ultimo


# ---------------------------------------------------------------------------
# PayPal Checkout (Orders v2): la ventana de PayPal donde quien paga aprueba o rechaza
# ---------------------------------------------------------------------------
# En el sandbox, quien paga entra con la cuenta Personal de pruebas y el dinero llega a la cuenta Business de la app
# (en la demo, la Business hace de proveedor). Kauta cobra la orden solo después de que PayPal confirma la aprobación.
ORDEN_LIQUIDADA = {"COMPLETED"}
ORDEN_RECHAZADA = {"DECLINED", "FAILED", "VOIDED"}


def crear_orden(pago_id: str, monto: Decimal, moneda: str, descripcion: str, volver: str, cancelar: str) -> dict[str, Any]:
    """Crea la orden y devuelve su id y el enlace de la ventana de PayPal para aprobarla."""
    if not configurado():
        raise ErrorPayPal("PayPal no está configurado.")
    cuerpo = {
        "intent": "CAPTURE",
        "purchase_units": [{"reference_id": pago_id[:256], "custom_id": pago_id[:127], "description": descripcion[:127],
                            "amount": {"currency_code": moneda, "value": f"{monto.quantize(Decimal('0.01'))}"}}],
        "payment_source": {"paypal": {"experience_context": {
            "brand_name": "Kauta · Brisamar Labs", "locale": "es-ES", "shipping_preference": "NO_SHIPPING",
            "user_action": "PAY_NOW", "return_url": volver, "cancel_url": cancelar}}},
    }
    r = _pedir("POST", "/v2/checkout/orders", cuerpo, token=_token_acceso(),
               extra={"PayPal-Request-Id": f"kauta-orden-{pago_id}", "Prefer": "return=representation"})
    enlace = next((x.get("href") for x in r.get("links", []) if x.get("rel") in ("payer-action", "approve")), None)
    if not r.get("id") or not enlace:
        raise ErrorPayPal("PayPal no devolvió el enlace para aprobar el pago.")
    return {"orden": r["id"], "estado": r.get("status"), "aprobar": enlace}


def consultar_orden(orden: str) -> dict[str, Any]:
    r = _pedir("GET", f"/v2/checkout/orders/{urllib.parse.quote(orden, safe='')}", token=_token_acceso())
    return {"estado": r.get("status")}


def capturar_orden(orden: str) -> dict[str, Any]:
    """Cobra una orden ya aprobada. Devuelve el estado del cobro (COMPLETED, PENDING, DECLINED…) y su identificador."""
    r = _pedir("POST", f"/v2/checkout/orders/{urllib.parse.quote(orden, safe='')}/capture", {}, token=_token_acceso(),
               extra={"PayPal-Request-Id": f"kauta-cobro-{orden}", "Prefer": "return=representation"})
    capturas = ((r.get("purchase_units") or [{}])[0].get("payments") or {}).get("captures") or [{}]
    c = capturas[0]
    return {"estado_orden": r.get("status"), "estado": c.get("status") or r.get("status"), "captura": c.get("id"),
            "pagador": enmascarar((r.get("payer") or {}).get("email_address") or "")}
