"""Lógica de negocio del servidor. Las rutas HTTP solo validan, autorizan y llaman a estos servicios."""
import threading

from sqlalchemy import text

from ..db import motor_bd

_CLAVE_PG = 0x4B415554          # «KAUT»: el número del candado de Kauta en PostgreSQL


class _Bloqueo:
    """
    Las operaciones que mueven dinero o escriben en la cadena de auditoría se serializan.
    En un solo proceso basta un RLock. Con PostgreSQL puede haber varias instancias del servidor a la vez (por ejemplo
    en Vercel), así que además se toma el candado de la base (pg_advisory_lock) mientras dura la operación.
    Es reentrante, como el RLock: una operación puede llamar a otra que también lo pide.
    """

    def __init__(self) -> None:
        self._rlock = threading.RLock()
        self._nivel = 0
        self._conexion = None

    def __enter__(self) -> "_Bloqueo":
        self._rlock.acquire()
        try:
            if self._nivel == 0 and motor_bd.dialect.name == "postgresql":
                c = motor_bd.connect()
                c.execute(text("SELECT pg_advisory_lock(:k)"), {"k": _CLAVE_PG})
                c.commit()
                self._conexion = c
        except BaseException:
            self._rlock.release()
            raise
        self._nivel += 1
        return self

    def __exit__(self, *_: object) -> bool:
        self._nivel -= 1
        try:
            if self._nivel == 0 and self._conexion is not None:
                c, self._conexion = self._conexion, None
                try:
                    c.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _CLAVE_PG})
                    c.commit()
                except Exception:
                    c.invalidate()          # sin poder soltarlo, la conexión se descarta y el candado cae con ella
                finally:
                    c.close()
        finally:
            self._rlock.release()
        return False


BLOQUEO = _Bloqueo()
