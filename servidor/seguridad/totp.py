"""
Segundo factor TOTP (RFC 6238), compatible con Google Authenticator, Microsoft Authenticator o 1Password.

  * El secreto se guarda cifrado con AES-256-GCM.
  * Se acepta una ventana de ±30 s y cada código se usa una sola vez (anti-repetición).
  * Se pide de nuevo al aprobar pagos («step-up»): una sesión robada no basta para mover dinero.
La hoja de ruta reemplaza TOTP por passkeys (WebAuthn), resistentes al phishing.
"""
from __future__ import annotations

import time

import pyotp

from .cifrado import cifrar, descifrar

EMISOR = "Kauta"


def nuevo_secreto() -> str:
    return pyotp.random_base32(length=32)


def uri(secreto: str, correo: str) -> str:
    return pyotp.TOTP(secreto).provisioning_uri(name=correo, issuer_name=EMISOR)


def cifrar_secreto(secreto: str, usuario_id: int) -> str:
    return cifrar(secreto, aad=f"totp:{usuario_id}")


def verificar_codigo(secreto_cifrado: str, usuario_id: int, codigo: str, ultimo_paso: int | None) -> int | None:
    """Devuelve el paso de tiempo usado si el código es válido y no se ha usado antes; si no, None."""
    codigo = "".join(c for c in (codigo or "") if c.isdigit())
    if len(codigo) != 6:
        return None
    totp = pyotp.TOTP(descifrar(secreto_cifrado, aad=f"totp:{usuario_id}"))
    ahora = int(time.time())
    for delta in (0, -30, 30):
        paso = (ahora + delta) // 30
        if totp.at(paso * 30) == codigo:
            if ultimo_paso is not None and paso <= ultimo_paso:
                return None  # código ya usado: posible repetición
            return paso
    return None
