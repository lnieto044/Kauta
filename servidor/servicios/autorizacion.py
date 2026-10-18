"""
Token de autorización por factura: cada aprobación que mueve dinero se confirma con un código propio.

Funciona como el token de un banco con vinculación dinámica (PSD2 / SCA):
  * Quien va a aprobar pide el token. Kauta revisa primero que pueda aprobar (estado, segregación de
    funciones, quién aprueba según el monto y reglas duras) y le envía a SU correo un código de 6 dígitos junto con lo
    que autoriza: factura, proveedor, monto y cuenta destino.
  * El código queda ligado a esos datos exactos: se guarda como HMAC-SHA256 (con la clave de firmas) del
    código más la huella de la factura, el monto, la moneda, la cuenta, el documento y la persona. Si el
    monto, la cuenta o las correcciones cambian después de emitirlo, el token ya no sirve.
  * Vence a los 5 minutos, se usa una sola vez, admite 5 intentos y uno nuevo anula al anterior.
  * Quien tiene activa la app autenticadora (TOTP) puede usar su código en lugar del token por correo.
  * Pagar una factura aprobada es otro paso con su propio token (otra clave de derivación: un token de
    aprobación no sirve para pagar), ligado al monto, al riel y al destino del dinero.
El token nunca se guarda en claro ni aparece en la auditoría: allí queda solo que se emitió y se usó.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import timedelta
from decimal import Decimal
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import CONFIG
from ..modelos import Beneficiario, Factura, TokenFactura, Usuario, ahora
from ..seguridad import firma, totp
from . import BLOQUEO, agente, auditoria, correo, pagos

MINUTOS = 5
MAX_INTENTOS = 5


class ErrorToken(Exception):
    """El token falta, venció, no coincide o se agotaron los intentos."""


def _datos(f: Factura, d: Any, ben: Beneficiario | None, u: Usuario) -> dict[str, Any]:
    """Lo que autoriza el token: los datos con los que se pagaría (con las correcciones ya aplicadas)."""
    return {"factura_id": f.id, "usuario_id": u.id, "beneficiario_id": ben.id if ben else None,
            "cuenta_ultimos4": ben.cuenta_ultimos4 if ben else "", "monto": str(d.monto), "moneda": d.moneda,
            "monto_usd": str(d.monto_usd), "hash_documento": f.hash_documento, "version_reglas": f.version_reglas,
            "riel": f.riel_pago or pagos.RIEL_PAGOS}


def _hmac(datos: dict[str, Any], codigo: str) -> str:
    return hmac.new(CONFIG.clave_firma, b"token-factura|" + firma.canonico(datos) + b"|" + codigo.encode(), hashlib.sha256).hexdigest()


def _monto(valor: Any, moneda: str | None) -> str:
    try:
        texto = f"{Decimal(str(valor)):,.2f}".replace(",", "·").replace(".", ",").replace("·", ".")
    except Exception:  # noqa: BLE001 - monto ilegible: se muestra tal cual
        texto = str(valor)
    return f"{moneda or ''} {texto}".strip()


def enmascarar(correo: str) -> str:
    usuario, _, dominio = correo.partition("@")
    return f"{usuario[:1]}{'•' * max(2, len(usuario) - 1)}@{dominio}"


def _vivos(bd: Session, fid: str, u: Usuario) -> list[TokenFactura]:
    return list(bd.execute(select(TokenFactura).where(TokenFactura.factura_id == fid, TokenFactura.usuario_id == u.id,
                                                      TokenFactura.usado_en.is_(None))
                           .order_by(TokenFactura.id.desc())).scalars())


def en_pantalla(u: Usuario) -> bool:
    """En una demo en línea (KAUTA_CODIGOS_EN_PANTALLA=1) las cuentas de ejemplo no tienen buzón real: su token se
    muestra a quien lo pidió. Las cuentas reales y el modo producción siempre lo reciben solo por correo."""
    return CONFIG.codigos_en_pantalla and correo.de_ejemplo(u.correo)


def emitir(bd: Session, fid: str, u: Usuario, correcciones: dict[str, Any] | None) -> tuple[TokenFactura, tuple[str, str, str]]:
    """Emite el token y devuelve el correo que hay que enviar a la persona (el código solo viaja en ese correo)."""
    with BLOQUEO:
        f, _, d, _, previas, _ = agente.revisar_aprobacion(bd, fid, u, correcciones)
        ben = bd.get(Beneficiario, f.beneficiario_id) if f.beneficiario_id else None
        datos = _datos(f, d, ben, u)
        for t in _vivos(bd, fid, u):                      # un token nuevo anula los anteriores
            t.usado_en = ahora()
        codigo = f"{secrets.randbelow(1_000_000):06d}"
        cuenta = f"···{ben.cuenta_ultimos4}" if ben else "sin cuenta registrada"
        resumen = f"{f.id} · {f.beneficiario_nombre} · {_monto(d.monto, d.moneda)} · cuenta {cuenta}"
        t = TokenFactura(factura_id=f.id, usuario_id=u.id, hash=_hmac(datos, codigo), huella=firma.huella(datos),
                         resumen=resumen, expira_en=ahora() + timedelta(minutes=MINUTOS))
        t.codigo_demo = codigo if en_pantalla(u) else None
        bd.add(t)
        auditoria.registrar(bd, "aprobacion.token_emitido", f"{u.nombre} ({u.cargo})", "factura", f.id,
                            f"Token de autorización enviado a {enmascarar(u.correo)} para aprobar {resumen}.",
                            {"huella": t.huella, "nivel": len(previas) + 1})
        bd.commit()
    texto = (f"Hola, {u.nombre}:\n\nSu token para aprobar esta factura en Kauta es:\n\n    {codigo}\n\n"
             f"Autoriza: {resumen}\nDocumento: {f.hash_documento[:16]}…\n\n"
             f"Vence en {MINUTOS} minutos y sirve una sola vez, solo para estos datos.\n"
             "Si usted no está aprobando esta factura, no comparta el código y avise a administración.")
    return t, (u.correo, f"Kauta · Token para aprobar {f.id}", texto)


def _comprobar(bd: Session, f: Factura, u: Usuario, codigo: str, esperado: Callable[[str], str], evento: str) -> str:
    """El código de 6 dígitos (o el de la app autenticadora) contra el último token vivo de esta persona y factura."""
    codigo = "".join(c for c in (codigo or "") if c.isdigit())
    if len(codigo) != 6:
        raise ErrorToken("Escriba el token de 6 dígitos que le enviamos al correo para autorizar este paso.")
    if u.mfa_activo and u.totp_cifrado:
        paso = totp.verificar_codigo(u.totp_cifrado, u.id, codigo, u.totp_ultimo_paso)
        if paso is not None:
            u.totp_ultimo_paso = paso
            return "totp"
    vivos = _vivos(bd, f.id, u)
    t = vivos[0] if vivos else None
    if not t or t.expira_en < ahora():
        raise ErrorToken("No hay un token vigente para esta factura: pida uno nuevo (vencen a los "
                         f"{MINUTOS} minutos y sirven una sola vez).")
    if not hmac.compare_digest(esperado(codigo), t.hash):
        t.intentos += 1
        agotado = t.intentos >= MAX_INTENTOS
        if agotado:
            t.usado_en = ahora()
        auditoria.registrar(bd, evento, f"{u.nombre} ({u.cargo})", "factura", f.id,
                            f"Token incorrecto o para otros datos (intento {t.intentos} de {MAX_INTENTOS}).", {})
        bd.commit()
        if agotado:
            raise ErrorToken("Demasiados intentos: el token quedó anulado. Pida uno nuevo.")
        raise ErrorToken("El token no coincide. Revise el código o pida uno nuevo si cambió el monto o una corrección.")
    t.usado_en = ahora()                              # se confirma junto con la aprobación o el pago
    return "token"


def verificar(bd: Session, fid: str, u: Usuario, correcciones: dict[str, Any] | None, codigo: str) -> str:
    """Valida el token (o el código TOTP) para aprobar esta factura con estos datos. Devuelve el factor usado."""
    with BLOQUEO:
        f, _, d, _, _, _ = agente.revisar_aprobacion(bd, fid, u, correcciones)
        ben = bd.get(Beneficiario, f.beneficiario_id) if f.beneficiario_id else None
        datos = _datos(f, d, ben, u)
        return _comprobar(bd, f, u, codigo, lambda c: _hmac(datos, c), "aprobacion.token_rechazado")


# ---------------------------------------------------------------------------
# Token de pago: pagar una factura aprobada es otro paso y lleva su propio token
# ---------------------------------------------------------------------------
def _datos_pago(f: Factura, ben: Beneficiario, u: Usuario) -> dict[str, Any]:
    return {"accion": "pagar", "factura_id": f.id, "usuario_id": u.id, "beneficiario_id": ben.id,
            "cuenta_ultimos4": ben.cuenta_ultimos4, "monto": str(f.monto), "moneda": f.moneda, "monto_usd": str(f.monto_usd),
            "hash_documento": f.hash_documento, "riel": f.riel_pago or pagos.RIEL_PAGOS}


def _hmac_pago(datos: dict[str, Any], codigo: str) -> str:
    return hmac.new(CONFIG.clave_firma, b"token-pago|" + firma.canonico(datos) + b"|" + codigo.encode(), hashlib.sha256).hexdigest()


def destino_pago(f: Factura, ben: Beneficiario) -> str:
    """A dónde sale el dinero, como lo verá la persona que paga."""
    riel = f.riel_pago or pagos.RIEL_PAGOS
    if riel == "PAYPAL":
        return f"PayPal {pagos.paypal.receptor_enmascarado()}" if pagos.paypal.envio_real() else "PayPal (simulado)"
    return f"cuenta ···{ben.cuenta_ultimos4}"


def emitir_pago(bd: Session, fid: str, u: Usuario) -> tuple[TokenFactura, tuple[str, str, str]]:
    """Token para PAGAR una factura aprobada: autoriza ese monto, por ese riel, a ese destino."""
    with BLOQUEO:
        f, ben = agente.revisar_pago(bd, fid, u)
        datos = _datos_pago(f, ben, u)
        for t in _vivos(bd, fid, u):
            t.usado_en = ahora()
        codigo = f"{secrets.randbelow(1_000_000):06d}"
        riel = pagos.RIELES[f.riel_pago or pagos.RIEL_PAGOS]["nombre"]
        resumen = f"Pagar {f.id} · {f.beneficiario_nombre} · {_monto(f.monto_usd, 'USD')} · {riel} · {destino_pago(f, ben)}"
        t = TokenFactura(factura_id=f.id, usuario_id=u.id, hash=_hmac_pago(datos, codigo), huella=firma.huella(datos),
                         resumen=resumen, expira_en=ahora() + timedelta(minutes=MINUTOS))
        t.codigo_demo = codigo if en_pantalla(u) else None
        bd.add(t)
        auditoria.registrar(bd, "pago.token_emitido", f"{u.nombre} ({u.cargo})", "factura", f.id,
                            f"Token de pago enviado a {enmascarar(u.correo)}: {resumen}.", {"huella": t.huella})
        bd.commit()
    texto = (f"Hola, {u.nombre}:\n\nSu token para PAGAR esta factura en Kauta es:\n\n    {codigo}\n\n"
             f"Autoriza: {resumen}\nDocumento: {f.hash_documento[:16]}…\n\n"
             f"Vence en {MINUTOS} minutos y sirve una sola vez, solo para este pago.\n"
             "Si usted no está pagando esta factura, no comparta el código y avise a administración.")
    return t, (u.correo, f"Kauta · Token para pagar {f.id}", texto)


def verificar_pago(bd: Session, fid: str, u: Usuario, codigo: str) -> str:
    with BLOQUEO:
        f, ben = agente.revisar_pago(bd, fid, u)
        datos = _datos_pago(f, ben, u)
        return _comprobar(bd, f, u, codigo, lambda c: _hmac_pago(datos, c), "pago.token_rechazado")
