"""
Kauta · Registro de auditoría.

Cada evento (decisión del agente, aprobación, rechazo, cambio de reglas) se guarda como una
línea JSON en un archivo de solo-agregar. Cada línea incluye el hash SHA-256 de la anterior,
así que si alguien edita o borra una línea, la verificación lo detecta (cadena de hashes).
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

TZ = timezone(timedelta(hours=-5))  # America/Bogota
GENESIS = "0" * 64


def _hash(entrada: dict[str, Any]) -> str:
    datos = {k: v for k, v in entrada.items() if k != "hash"}
    return hashlib.sha256(json.dumps(datos, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


class Registro:
    def __init__(self, ruta: str | Path | None = None):
        self.ruta = Path(ruta) if ruta else None
        self.entradas: list[dict[str, Any]] = []
        if self.ruta and self.ruta.exists():
            for linea in self.ruta.read_text(encoding="utf-8").splitlines():
                if linea.strip():
                    self.entradas.append(json.loads(linea))

    def agregar(self, evento: str, **datos: Any) -> dict[str, Any]:
        entrada = {
            "seq": len(self.entradas) + 1,
            "fecha": datetime.now(TZ).isoformat(timespec="seconds"),
            "evento": evento,
            **datos,
            "hash_anterior": self.entradas[-1]["hash"] if self.entradas else GENESIS,
        }
        entrada["hash"] = _hash(entrada)
        self.entradas.append(entrada)
        if self.ruta:
            self.ruta.parent.mkdir(parents=True, exist_ok=True)
            with open(self.ruta, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entrada, ensure_ascii=False) + "\n")
        return entrada

    def verificar(self) -> tuple[bool, int | None]:
        """Devuelve (True, None) si la cadena está intacta; si no, (False, seq de la primera línea alterada)."""
        anterior = GENESIS
        for e in self.entradas:
            if e.get("hash_anterior") != anterior or _hash(e) != e.get("hash"):
                return False, e.get("seq")
            anterior = e["hash"]
        return True, None

    def a_csv(self) -> str:
        buf = io.StringIO()
        campos = ["seq", "fecha", "evento", "factura_id", "decision", "estado", "actor", "beneficiario",
                  "monto", "moneda", "monto_usd", "motivo", "version_reglas", "hash"]
        wr = csv.DictWriter(buf, fieldnames=campos, extrasaction="ignore")
        wr.writeheader()
        for e in self.entradas:
            wr.writerow(e)
        return buf.getvalue()
