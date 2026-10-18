"""
Kauta · Agente: une extracción (IA) + motor de reglas (código) + registro de auditoría.

Ciclo por factura:
  1. Extraer datos del documento (IA o referencia).
  2. Evaluar con el motor de reglas determinista.
  3. Guardar la decisión con su explicación en el registro encadenado.
  4. Si quedó "pendiente", una persona aprueba o rechaza. Al aprobar, el motor vuelve a revisar
     las reglas duras: ni siquiera una aprobación humana puede romper saldo, duplicados,
     bloqueos o el máximo por pago.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from . import motor
from .registro import Registro

RAIZ = Path(__file__).resolve().parents[1]
ESTADO_POR_DECISION = {"pagar": "pagada", "frenar": "frenada", "escalar": "pendiente"}


def cargar_json(nombre: str) -> Any:
    return json.loads((RAIZ / "data" / nombre).read_text(encoding="utf-8"))


class Agente:
    def __init__(self, reglas: dict, beneficiarios: list[dict], extractor: Any, registro: Registro | None = None):
        self.reglas = copy.deepcopy(reglas)
        self.beneficiarios = copy.deepcopy(beneficiarios)
        self.extractor = extractor
        self.registro = registro or Registro()
        self.facturas: dict[str, dict[str, Any]] = {}   # en orden de llegada

    # ------------------------------------------------------------------ util
    def _historial(self) -> list[dict[str, Any]]:
        h = []
        for f in self.facturas.values():
            d = f.get("decision")
            if not d:
                continue
            h.append({
                "factura_id": f["factura_id"], "beneficiario_clave": f["beneficiario_clave"],
                "numero_factura": f["extraccion"].get("numero_factura"), "periodo": d.periodo,
                "estado": f["estado"], "monto_usd": d.monto_usd, "hashes": f["hashes"],
                "id_fiscal_unico": f["extraccion"].get("id_fiscal_unico"),
            })
        return h

    def _clave(self, ext: dict) -> str:
        ben, _ = motor.buscar_beneficiario(ext, self.beneficiarios)
        return motor.clave_beneficiario(ben, ext)

    def _registrar(self, evento: str, f: dict, actor: str, extra: dict | None = None) -> None:
        d = f["decision"]
        self.registro.agregar(
            evento, factura_id=f["factura_id"], archivo=f["archivo"], canal=f["canal"], actor=actor,
            decision=d.decision, estado=f["estado"], beneficiario=d.beneficiario_nombre,
            monto=d.monto, moneda=d.moneda, monto_usd=d.monto_usd, periodo=d.periodo, motivo=d.motivo,
            reglas=[{"id": r.id, "estado": r.estado, "detalle": r.detalle} for r in d.reglas],
            version_reglas=d.version_reglas, modelo_extraccion=f.get("modelo"),
            hash_documento=f["hashes"][0] if f["hashes"] else None, **(extra or {}))

    def nuevo_id(self, nombre: str) -> str:
        pref = Path(nombre).name.split("_")[0]
        if pref[:1] in "FN" and pref[1:].isdigit() and pref not in self.facturas:
            return pref
        n = 1
        while f"N{n:02d}" in self.facturas:
            n += 1
        return f"N{n:02d}"

    # --------------------------------------------------------------- procesar
    def procesar(self, nombre: str, datos: bytes, factura_id: str | None = None) -> dict[str, Any]:
        fid = factura_id or self.nuevo_id(nombre)
        r = self.extractor.extraer(nombre, datos)
        f = {"factura_id": fid, "archivo": nombre, "canal": r["canal"], "extraccion": r["extraccion"],
             "hashes": r["hashes"], "texto": r.get("texto", ""), "modelo": r.get("modelo"),
             "beneficiario_clave": self._clave(r["extraccion"]), "decision": None, "estado": "nueva",
             "aprobacion": None}
        self.facturas[fid] = f
        f["decision"] = motor.evaluar({"factura_id": fid, "extraccion": f["extraccion"], "hashes": f["hashes"]},
                                      self.reglas, self.beneficiarios, self._historial())
        f["estado"] = ESTADO_POR_DECISION[f["decision"].decision]
        f["decision_inicial"] = copy.deepcopy(f["decision"])  # lo que Kauta decidió sola al llegar la factura
        self._registrar("decision", f, actor="Agente Kauta")
        return f

    def procesar_carpeta(self, carpeta: Path) -> list[dict[str, Any]]:
        salida = []
        for p in sorted(Path(carpeta).iterdir()):
            if p.is_file() and not p.name.startswith("."):
                salida.append(self.procesar(p.name, p.read_bytes()))
        return salida

    # ------------------------------------------------------- acciones humanas
    def aprobar(self, factura_id: str, persona: str, comentario: str = "", correcciones: dict | None = None) -> dict[str, Any]:
        f = self.facturas[factura_id]
        if f["estado"] != "pendiente":
            return {"ok": False, "mensaje": f"Solo se aprueban facturas pendientes (estado actual: {f['estado']})."}
        revisadas = [r.id for r in f["decision"].fallas("escalar")]
        corregidos = {k: v for k, v in (correcciones or {}).items() if v not in (None, "")}
        if correcciones:
            ext = copy.deepcopy(f["extraccion"])
            for k, v in correcciones.items():
                if v not in (None, ""):
                    ext[k] = v
                    ext.setdefault("confianza", {})[k] = 1.0
            f["extraccion"] = ext
        d = motor.evaluar({"factura_id": factura_id, "extraccion": f["extraccion"], "hashes": f["hashes"]},
                          self.reglas, self.beneficiarios, self._historial())
        duras = d.fallas("frenar")
        if duras:
            f["decision"] = d
            self._registrar("aprobacion_bloqueada", f, actor=persona,
                            extra={"comentario": comentario, "bloqueos": [r.id for r in duras]})
            return {"ok": False, "mensaje": "La aprobación no procede por una regla dura: " + duras[0].detalle}
        aceptadas = [r.id for r in d.fallas("escalar")]
        d.decision = "pagar"
        partes = [f"Pagada con aprobación de {persona}, que revisó: "
                  + "; ".join(f"{motor.CATALOGO[rid]['falla'].lower()} ({rid})" for rid in revisadas) + "."]
        if corregidos:
            partes.append("Datos corregidos por la persona: " + ", ".join(f"{k} = {v}" for k, v in corregidos.items()) + ".")
        if comentario:
            partes.append(f"Comentario: «{comentario}».")
        partes.append("Kauta volvió a verificar las reglas duras (saldo, duplicados, bloqueos y máximo por pago) y se cumplen.")
        d.motivo = " ".join(partes)
        f["decision"] = d
        f["estado"] = "pagada"
        f["aprobacion"] = {"persona": persona, "comentario": comentario, "reglas_revisadas": revisadas,
                           "reglas_aceptadas": aceptadas, "correcciones": corregidos}
        self._registrar("aprobacion", f, actor=persona, extra={"comentario": comentario, "reglas_revisadas": revisadas,
                                                                "correcciones": corregidos})
        return {"ok": True, "mensaje": d.motivo}

    def rechazar(self, factura_id: str, persona: str, comentario: str = "") -> dict[str, Any]:
        f = self.facturas[factura_id]
        if f["estado"] != "pendiente":
            return {"ok": False, "mensaje": f"Solo se rechazan facturas pendientes (estado actual: {f['estado']})."}
        f["estado"] = "rechazada"
        f["decision"].motivo = f"Rechazada por {persona}." + (f" Comentario: «{comentario}»." if comentario else "")
        self._registrar("rechazo", f, actor=persona, extra={"comentario": comentario})
        return {"ok": True, "mensaje": f["decision"].motivo}

    # ---------------------------------------------------- cambios de reglas
    def actualizar_reglas(self, nuevas: dict, persona: str) -> None:
        cambios = {k: {"antes": self.reglas.get(k), "despues": v} for k, v in nuevas.items()
                   if k != "version" and self.reglas.get(k) != v}
        if not cambios:
            return
        self.reglas.update(copy.deepcopy(nuevas))
        self.reglas["version"] = int(self.reglas.get("version", 1)) + 1
        self.registro.agregar("cambio_reglas", actor=persona, version_reglas=self.reglas["version"],
                              motivo="Cambio de reglas: " + "; ".join(f"{k}: {v['antes']} → {v['despues']}" for k, v in cambios.items()),
                              cambios=cambios)

    def reevaluar(self, persona: str = "Agente Kauta") -> list[str]:
        """Vuelve a evaluar, en orden, las facturas frenadas o pendientes (las pagadas no se tocan)."""
        cambiadas = []
        for fid, f in self.facturas.items():
            if f["estado"] not in ("frenada", "pendiente"):
                continue
            antes = f["estado"]
            f["estado"] = "en_revision"
            d = motor.evaluar({"factura_id": fid, "extraccion": f["extraccion"], "hashes": f["hashes"]},
                              self.reglas, self.beneficiarios, self._historial())
            f["decision"] = d
            f["estado"] = ESTADO_POR_DECISION[d.decision]
            if f["estado"] != antes:
                cambiadas.append(fid)
                self._registrar("reevaluacion", f, actor=persona, extra={"estado_anterior": antes})
        return cambiadas

    # --------------------------------------------------------------- métricas
    def metricas(self) -> dict[str, Any]:
        fs = list(self.facturas.values())
        tot = len(fs)
        por = {e: [f for f in fs if f["estado"] == e] for e in ("pagada", "frenada", "pendiente", "rechazada")}
        # Autonomía: facturas que Kauta resolvió sola (pagar o frenar) en su primera decisión, sin pedir ayuda
        autonomas = [f for f in fs if (f.get("decision_inicial") or f["decision"]).decision in ("pagar", "frenar")]
        periodo = self.reglas.get("periodo_actual")
        pagado = sum(f["decision"].monto_usd or 0 for f in por["pagada"] if f["decision"].periodo == periodo)
        indebidos = 0
        for f in por["pagada"]:
            d = f["decision"]
            if f["aprobacion"] is None and any(r.estado == "falla" for r in d.reglas):
                indebidos += 1
            if f["aprobacion"] is not None and d.fallas("frenar"):
                indebidos += 1
        return {
            "total": tot, "pagadas": len(por["pagada"]), "frenadas": len(por["frenada"]),
            "pendientes": len(por["pendiente"]), "rechazadas": len(por["rechazada"]),
            "autonomia_pct": round(100 * len(autonomas) / tot, 1) if tot else 0.0,
            "pagado_usd": round(pagado, 2), "presupuesto_usd": float(self.reglas["presupuesto_periodo_usd"]),
            "saldo_usd": round(float(self.reglas["presupuesto_periodo_usd"]) - pagado, 2),
            "pagos_fuera_de_reglas": indebidos,
            "explicadas_pct": round(100 * sum(1 for f in fs if f["decision"] and f["decision"].motivo) / tot, 1) if tot else 0.0,
        }
