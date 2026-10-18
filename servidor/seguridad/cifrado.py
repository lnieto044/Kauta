"""
Cifrado de datos sensibles en reposo con AES-256-GCM (cifrado autenticado).

  * Cada valor lleva su propio nonce de 96 bits generado al azar.
  * AAD (datos asociados): el cifrado queda «amarrado» a su registro (por ejemplo, el id del
    beneficiario). Si alguien copia el número de cuenta cifrado de un proveedor a otro, ya no descifra.
  * Formato versionado «v1:<id de clave>:<base64>» para rotar claves sin migraciones masivas.
En producción la clave la entrega un KMS (cifrado de sobre: la clave de datos va cifrada por una clave
maestra que nunca sale del HSM).
"""
from __future__ import annotations

import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ..config import CONFIG

_CLAVE = CONFIG.clave_datos[:32]
ID_CLAVE = hashlib.sha256(_CLAVE).hexdigest()[:8]


def cifrar(texto: str, aad: str = "") -> str:
    nonce = os.urandom(12)
    ct = AESGCM(_CLAVE).encrypt(nonce, texto.encode("utf-8"), aad.encode("utf-8"))
    return f"v1:{ID_CLAVE}:{base64.b64encode(nonce + ct).decode()}"


def descifrar(token: str, aad: str = "") -> str:
    version, kid, datos = token.split(":", 2)
    if version != "v1" or kid != ID_CLAVE:
        raise ValueError("Clave de cifrado desconocida (¿se rotó la clave?).")
    crudo = base64.b64decode(datos)
    return AESGCM(_CLAVE).decrypt(crudo[:12], crudo[12:], aad.encode("utf-8")).decode("utf-8")


def enmascarar(numero: str) -> str:
    d = "".join(c for c in numero if c.isalnum())
    return "•••• " + d[-4:] if len(d) >= 4 else "••••"
