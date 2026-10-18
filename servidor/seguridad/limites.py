"""
Límite de peticiones por ventana deslizante (contra fuerza bruta y abuso de la API).
En producción con varias réplicas, el mismo algoritmo vive en Redis o en el API gateway.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException


class Limitador:
    def __init__(self) -> None:
        self._eventos: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def permitir(self, clave: str, maximo: int, ventana_s: int) -> bool:
        t = time.monotonic()
        with self._lock:
            q = self._eventos[clave]
            while q and q[0] <= t - ventana_s:
                q.popleft()
            if len(q) >= maximo:
                return False
            q.append(t)
            return True

    def reiniciar(self) -> None:
        with self._lock:
            self._eventos.clear()


LIMITADOR = Limitador()


def limitar(clave: str, maximo: int, ventana_s: int) -> None:
    if not LIMITADOR.permitir(clave, maximo, ventana_s):
        raise HTTPException(429, "Demasiadas solicitudes. Espere un momento e intente de nuevo.",
                            headers={"Retry-After": str(ventana_s)})
