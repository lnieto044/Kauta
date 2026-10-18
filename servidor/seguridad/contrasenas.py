"""
Contraseñas con Argon2id (ganador de la Password Hashing Competition y primera opción de OWASP).

Parámetros: 64 MiB de memoria, 3 iteraciones, 4 hilos (por encima del mínimo de OWASP: 19 MiB, t=2, p=1).
Política (NIST SP 800-63B-4): 15 caracteres como mínimo (lo que pide NIST cuando la contraseña es el único
factor), sin reglas de composición ni caducidad forzada, y con lista de contraseñas comunes. Se aplica al
crear usuarios. El hash se recalcula solo si cambian los parámetros.
"""
from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_ph = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4, hash_len=32, salt_len=16)
LARGO_MINIMO = 15
COMUNES = {"123456789012345", "contraseña12345", "password1234567", "qwertyuiop12345", "kauta2026kauta2026",
           "brisamar2026brisamar", "administrador123", "000000000000000", "iloveyou1234567", "colombia20262026",
           "contraseñasegura123", "passwordpassword"}

# Hash señuelo: cuando el usuario no existe se verifica contra este hash para que el tiempo de respuesta
# sea igual y no se pueda averiguar qué correos están registrados (enumeración de usuarios).
_SENUELO = _ph.hash("señuelo-para-tiempo-constante")


def hashear(contrasena: str) -> str:
    return _ph.hash(contrasena)


def verificar(hash_guardado: str | None, contrasena: str) -> bool:
    try:
        return _ph.verify(hash_guardado or _SENUELO, contrasena) and hash_guardado is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def necesita_rehash(hash_guardado: str) -> bool:
    return _ph.check_needs_rehash(hash_guardado)


def problemas_politica(contrasena: str, correo: str = "") -> list[str]:
    p = []
    if len(contrasena) < LARGO_MINIMO:
        p.append(f"Debe tener al menos {LARGO_MINIMO} caracteres (se recomienda una frase).")
    if contrasena.lower() in COMUNES:
        p.append("Es una contraseña demasiado común.")
    if correo and correo.split("@")[0].lower() in contrasena.lower():
        p.append("No debe contener el usuario del correo.")
    return p
