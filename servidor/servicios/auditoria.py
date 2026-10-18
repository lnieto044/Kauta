"""
Registro de auditoría a prueba de alteraciones: cadena HMAC-SHA256.

Cada evento guarda el hash del anterior; el hash se calcula con una clave secreta (HMAC), así que
quien tenga acceso de escritura a la base de datos pero no a la clave no puede rehacer la cadena.
La «cabeza» de la cadena (último hash) se puede publicar o enviar a un sistema externo como ancla.
"""
from __future__ import annotations

import csv
import hashlib
import hmac
import io
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import CONFIG
from ..modelos import EventoAuditoria
from ..seguridad.firma import canonico
from . import BLOQUEO

GENESIS = "0" * 64


def _hmac(anterior: str, contenido: dict[str, Any]) -> str:
    return hmac.new(CONFIG.clave_auditoria, anterior.encode() + canonico(contenido), hashlib.sha256).hexdigest()


def registrar(bd: Session, tipo: str, actor: str, entidad: str, entidad_id: str | None, resumen: str,
              datos: dict[str, Any] | None = None) -> EventoAuditoria:
    with BLOQUEO:
        ultimo = bd.execute(select(EventoAuditoria).order_by(EventoAuditoria.id.desc()).limit(1)).scalar_one_or_none()
        anterior = ultimo.hash if ultimo else GENESIS
        nid = (ultimo.id + 1) if ultimo else 1
        ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        contenido = {"id": nid, "ts": ts, "tipo": tipo, "actor": actor, "entidad": entidad, "entidad_id": entidad_id,
                     "resumen": resumen, "datos": json.loads(json.dumps(datos or {}, default=str))}
        ev = EventoAuditoria(id=nid, ts=ts, tipo=tipo, actor=actor, entidad=entidad, entidad_id=entidad_id,
                             resumen=resumen, datos=contenido["datos"], hash_anterior=anterior,
                             hash=_hmac(anterior, contenido))
        bd.add(ev)
        bd.flush()
        return ev


def verificar(bd: Session) -> dict[str, Any]:
    anterior, total = GENESIS, 0
    for ev in bd.execute(select(EventoAuditoria).order_by(EventoAuditoria.id)).scalars():
        total += 1
        contenido = {"id": ev.id, "ts": ev.ts, "tipo": ev.tipo, "actor": ev.actor, "entidad": ev.entidad,
                     "entidad_id": ev.entidad_id, "resumen": ev.resumen, "datos": ev.datos}
        if ev.hash_anterior != anterior or not hmac.compare_digest(_hmac(anterior, contenido), ev.hash):
            return {"ok": False, "total": total, "evento_alterado": ev.id, "cabeza": anterior,
                    "mensaje": f"La cadena se rompe en el evento {ev.id}: alguien lo modificó o borró uno anterior."}
        anterior = ev.hash
    return {"ok": True, "total": total, "evento_alterado": None, "cabeza": anterior,
            "mensaje": f"Cadena íntegra: {total} eventos verificados con HMAC-SHA256."}


def exportar(bd: Session, formato: str = "csv") -> str:
    filas = [{"id": e.id, "ts": e.ts, "tipo": e.tipo, "actor": e.actor, "entidad": e.entidad, "entidad_id": e.entidad_id,
              "resumen": e.resumen, "datos": e.datos, "hash_anterior": e.hash_anterior, "hash": e.hash}
             for e in bd.execute(select(EventoAuditoria).order_by(EventoAuditoria.id)).scalars()]
    if formato == "jsonl":
        return "\n".join(json.dumps(f, ensure_ascii=False) for f in filas) + "\n"
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(filas[0].keys()) if filas else ["id"])
    w.writeheader()
    for f in filas:
        w.writerow({**f, "datos": json.dumps(f["datos"], ensure_ascii=False)})
    return buf.getvalue()
