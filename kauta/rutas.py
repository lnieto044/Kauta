"""
Rutas de pago del reto: con la caja de cada entidad y las alternativas de cada factura (pago contractual,
pronto pago, prórroga, moneda local, hitos), Kauta busca la combinación de menor costo que nunca rompe la
reserva mínima. Lee los CSV del reto en data/reto (todos los datos son sintéticos).

Reglas, tomadas del diccionario de datos del reto:
  * Las alternativas de una factura son excluyentes: se elige exactamente una por factura.
  * Una alternativa con grupo de dependencia solo vale si su grupo se elige completo (negociación conjunta).
  * Cada entidad paga con su propia caja: nunca se mezclan fondos entre entidades.
  * Después de cada evento (pago o cobro previsto) el saldo menos la reserva mínima y los fondos de terceros
    restringidos debe ser cero o más. Los pagos de un mismo día van antes que los cobros (criterio conservador).
  * Los cobros previstos no están garantizados: si la ruta los necesita para cumplir la reserva, es una condición.
  * Las retenciones se entregan aparte: cuentan en el costo, no en el desembolso al proveedor.
  * Una factura que requiere revisión (disputa, falta de aprobación, exceso de orden de compra) no se ejecuta sola,
    y un descuento cuya fecha límite ya pasó a la fecha de corte no es ejecutable.
El resultado se compara con resumen_rutas.csv, la referencia del reto.
"""
from __future__ import annotations

import csv
import itertools
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

CARPETA = Path(__file__).resolve().parents[1] / "data" / "reto"
CENT = Decimal("0.01")
NOMBRES_OPCION = {"BASE": "Pago contractual", "PRONTO_PAGO": "Pronto pago", "PRORROGA": "Prórroga", "MONEDA_LOCAL": "Moneda local",
                  "MONEDA_LOCAL_PRONTO": "Moneda local con pronto pago", "HITOS_VOLUMEN": "Paquete por hitos"}


def _d(v: str | None) -> Decimal:
    return Decimal(v) if v not in (None, "") else Decimal("0")


def _f(v: Decimal) -> float:
    return float(v.quantize(CENT, ROUND_HALF_UP))


def _leer(nombre: str, carpeta: Path) -> list[dict[str, str]]:
    with open(carpeta / f"{nombre}.csv", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


@dataclass
class Datos:
    facturas: dict[str, dict[str, str]]
    opciones: dict[str, list[dict[str, str]]]          # factura_id -> alternativas
    entidades: dict[str, dict[str, str]]
    cobros: dict[str, list[dict[str, str]]]            # historia -> cobros previstos
    referencia: dict[str, dict[str, str]]              # ruta_id -> fila de resumen_rutas
    fecha_corte: date = field(default=date(2026, 11, 2))


@lru_cache(maxsize=4)
def cargar(carpeta: str | None = None) -> Datos:
    c = Path(carpeta) if carpeta else CARPETA
    facturas = {f["factura_id"]: f for f in _leer("facturas", c)}
    opciones: dict[str, list[dict[str, str]]] = {}
    for a in _leer("alternativas_pago", c):
        opciones.setdefault(a["factura_id"], []).append(a)
    cobros: dict[str, list[dict[str, str]]] = {}
    for m in _leer("movimientos_ruta", c):     # los cobros previstos son datos de entrada: se toman de la ruta base
        if m["tipo_evento"] == "COBRO_PREVISTO" and m["ruta_id"].endswith("-BASE"):
            cobros.setdefault(m["escenario_historia_id"], []).append(m)
    corte = next(iter(facturas.values()))["fecha_corte"]
    return Datos(facturas, opciones, {e["entidad_id"]: e for e in _leer("entidades_caja", c)}, cobros,
                 {r["ruta_id"]: r for r in _leer("resumen_rutas", c)}, date.fromisoformat(corte))


# ---------------------------------------------------------------- piezas
def costo(o: dict[str, str]) -> Decimal:
    return _d(o["costo_total_pendiente_usd"])


def requiere_aprobacion(o: dict[str, str]) -> bool:
    return o["requiere_aprobacion_humana"] == "SI" or o["estado_condicion"].startswith("PENDIENTE")


def vencida(o: dict[str, str], corte: date) -> bool:
    limite = o.get("fecha_limite_condicion") or ""
    return bool(limite) and date.fromisoformat(limite) < corte


def desembolsos(o: dict[str, str]) -> list[tuple[date, Decimal]]:
    salida = [(date.fromisoformat(o["fecha_pago_inicial"]), _d(o["desembolso_inicial_usd"]))]
    if _d(o["desembolso_final_usd"]) > 0:
        salida.append((date.fromisoformat(o["fecha_pago_final"]), _d(o["desembolso_final_usd"])))
    return salida


def _simular(datos: Datos, historia: str, elegidas: dict[str, dict[str, str]], con_cobros: bool = True) -> dict[str, Any]:
    """Recorre los eventos de caja en orden y calcula saldos y márgenes por entidad."""
    entidades = sorted({datos.facturas[f]["entidad_id"] for f in elegidas})
    saldo = {e: _d(datos.entidades[e]["saldo_inicial_usd"]) for e in entidades}
    piso = {e: _d(datos.entidades[e]["reserva_minima_usd"]) + _d(datos.entidades[e]["fondos_terceros_restringidos_usd"]) for e in entidades}
    inicio = min((date.fromisoformat(datos.entidades[e]["fecha_saldo_inicial"]) for e in entidades), default=datos.fecha_corte)
    eventos: list[tuple[date, int, str, str, str, Decimal, str]] = []
    for fid, o in elegidas.items():
        tramos = desembolsos(o)
        for i, (dia, monto) in enumerate(tramos):
            etiqueta = NOMBRES_OPCION.get(o["tipo_opcion"], o["tipo_opcion"]) + (f" · tramo {i + 1} de {len(tramos)}" if len(tramos) > 1 else "")
            eventos.append((dia, 0, datos.facturas[fid]["entidad_id"], "pago", fid, -monto, etiqueta))
    if con_cobros:
        for c in datos.cobros.get(historia, []):
            eventos.append((date.fromisoformat(c["fecha_evento"]), 1, c["entidad_id"], "cobro", "", _d(c["importe_firmado_usd"]), c["concepto"]))
    eventos.sort(key=lambda e: (e[0], e[1], e[2], e[4]))
    filas, minimo_consolidado, minimo_margen = [], sum(saldo.values()), min((saldo[e] - piso[e] for e in entidades), default=Decimal(0))
    for dia, _, ent, tipo, fid, importe, concepto in eventos:
        saldo[ent] += importe
        margen = saldo[ent] - piso[ent]
        minimo_margen = min(minimo_margen, margen)
        minimo_consolidado = min(minimo_consolidado, sum(saldo.values()))
        filas.append({"fecha": dia.isoformat(), "dia": (dia - inicio).days, "entidad_id": ent, "tipo": tipo, "factura_id": fid or None,
                      "concepto": concepto, "importe_usd": _f(importe), "saldo_usd": _f(saldo[ent]), "reserva_usd": _f(piso[ent]),
                      "margen_usd": _f(margen), "cumple": margen >= 0})
    return {"eventos": filas, "saldo_final_usd": _f(sum(saldo.values())), "saldo_minimo_consolidado_usd": _f(minimo_consolidado),
            "minimo_margen_individual_usd": _f(minimo_margen), "cumple_reservas": minimo_margen >= 0,
            "entidades": [{"entidad_id": e, "nombre": datos.entidades[e]["entidad_nombre"], "saldo_inicial_usd": _f(_d(datos.entidades[e]["saldo_inicial_usd"])),
                           "reserva_usd": _f(piso[e])} for e in entidades], "inicio": inicio.isoformat()}


def _ruta(datos: Datos, historia: str, elegidas: dict[str, dict[str, str]], base: dict[str, dict[str, str]]) -> dict[str, Any]:
    sim = _simular(datos, historia, elegidas)
    sin_cobros = _simular(datos, historia, elegidas, con_cobros=False)
    condiciones = []
    for fid, o in elegidas.items():
        f = datos.facturas[fid]
        if o["estado_condicion"].startswith("PENDIENTE"):
            condiciones.append(f"Negociar con {f['contraparte_nombre']}: {o['descripcion_opcion'].rstrip('.')}.")
        elif o["moneda_liquidacion"] != o["moneda_factura"]:
            condiciones.append(f"Confirmar con {f['contraparte_nombre']} el pago en {o['moneda_liquidacion']} y la cotización antes de ejecutar.")
    if not sin_cobros["cumple_reservas"]:
        for c in datos.cobros.get(historia, []):
            dia = (date.fromisoformat(c["fecha_evento"]) - date.fromisoformat(sim["inicio"])).days
            condiciones.append(f"Depende del cobro previsto de USD {_f(_d(c['importe_firmado_usd'])):,.0f} el día {dia} ({c['entidad_id']}); no está garantizado.")
    opciones = []
    for fid, o in sorted(elegidas.items()):
        f = datos.facturas[fid]
        opciones.append({"factura_id": fid, "numero": f["numero_factura"], "entidad_id": f["entidad_id"], "contraparte": f["contraparte_nombre"],
                         "concepto": f["subcategoria"], "opcion_id": o["opcion_id"], "tipo_opcion": o["tipo_opcion"],
                         "nombre_opcion": NOMBRES_OPCION.get(o["tipo_opcion"], o["tipo_opcion"]), "descripcion": o["descripcion_opcion"],
                         "fecha_pago_inicial": o["fecha_pago_inicial"], "fecha_pago_final": o["fecha_pago_final"],
                         "moneda_liquidacion": o["moneda_liquidacion"], "riel": o["riel_pago"], "costo_usd": _f(costo(o)),
                         "ahorro_vs_base_usd": _f(costo(base[fid]) - costo(o)), "requiere_aprobacion": requiere_aprobacion(o),
                         "estado_condicion": o["estado_condicion"]})
    return {"costo_usd": _f(sum(costo(o) for o in elegidas.values())), "opciones": opciones, "condiciones": list(dict.fromkeys(condiciones)),
            "requiere_aprobacion": any(requiere_aprobacion(o) for o in elegidas.values()), **sim}


def optimizar_historia(historia: str, datos: Datos | None = None) -> dict[str, Any]:
    """Prueba todas las combinaciones de alternativas de la historia y elige la más barata que cumple todo."""
    datos = datos or cargar()
    fids = sorted(f for f, x in datos.facturas.items() if x["escenario_historia_id"] == historia and x["direccion_factura"] == "POR_PAGAR")
    menus = [[o for o in datos.opciones.get(f, []) if not vencida(o, datos.fecha_corte)] for f in fids]
    base = {f: next(o for o in datos.opciones[f] if o["tipo_opcion"] == "BASE") for f in fids}
    grupos: dict[str, set[str]] = {}
    for f in fids:
        for o in datos.opciones.get(f, []):
            if o["grupo_dependencia_id"]:
                grupos.setdefault(o["grupo_dependencia_id"], set()).add(f)
    evaluadas, factibles, mejor = 0, 0, None
    for combo in itertools.product(*menus):
        evaluadas += 1
        elegidas = dict(zip(fids, combo))
        if any(len({elegidas[f]["grupo_dependencia_id"] == g for f in miembros}) > 1 for g, miembros in grupos.items()):
            continue                                       # un grupo de negociación va completo o no va
        sim = _simular(datos, historia, elegidas)
        if not sim["cumple_reservas"]:
            continue
        factibles += 1
        clave = (sum(costo(o) for o in elegidas.values()), sum(requiere_aprobacion(o) for o in elegidas.values()))
        if mejor is None or clave < mejor[0]:
            mejor = (clave, elegidas)
    ruta_base = _ruta(datos, historia, base, base)
    ruta_kauta = _ruta(datos, historia, mejor[1], base) if mejor else ruta_base
    ahorro = Decimal(str(ruta_base["costo_usd"])) - Decimal(str(ruta_kauta["costo_usd"]))
    ref = datos.referencia.get(f"{historia}-KAUTA", {})
    primera = datos.facturas[fids[0]] if fids else {}
    return {"historia": historia, "empresa": primera.get("empresa_referencia"), "perfil": primera.get("perfil_operativo"),
            "facturas": len(fids), "combinaciones_evaluadas": evaluadas, "combinaciones_factibles": factibles,
            "base": ruta_base, "kauta": ruta_kauta, "ahorro_usd": _f(ahorro),
            "ahorro_pct": _f(ahorro / Decimal(str(ruta_base["costo_usd"])) * 100) if ruta_base["costo_usd"] else 0.0,
            "referencia": {"ruta_id": ref.get("ruta_id"), "nombre": ref.get("nombre_ruta"),
                           "costo_usd": float(ref["costo_ruta_usd"]) if ref else None,
                           "coincide": bool(ref) and abs(float(ref["costo_ruta_usd"]) - ruta_kauta["costo_usd"]) < 0.01}}


def analizar_general(datos: Datos | None = None) -> dict[str, Any]:
    """Facturas del día a día: la alternativa ejecutable más barata de cada una, sin tocar las que piden revisión."""
    datos = datos or cargar()
    filas, por_entidad = [], {}
    for fid, f in sorted(datos.facturas.items()):
        if f["escenario_historia_id"] != "GENERAL" or f["direccion_factura"] != "POR_PAGAR":
            continue
        opciones = datos.opciones.get(fid, [])
        base = next(o for o in opciones if o["tipo_opcion"] == "BASE")
        ejecutables = [o for o in opciones if not vencida(o, datos.fecha_corte) and not o["estado_condicion"].startswith("PENDIENTE")]
        mejor = min(ejecutables, key=lambda o: (costo(o), requiere_aprobacion(o)))
        vencidas = [o for o in opciones if vencida(o, datos.fecha_corte)]
        bloqueada = f["requiere_revision"] == "SI"
        estado = "revision" if bloqueada else ("optimizada" if mejor["opcion_id"] != base["opcion_id"] else "contractual")
        ahorro = Decimal(0) if bloqueada else costo(base) - costo(mejor)
        e = por_entidad.setdefault(f["entidad_id"], {"entidad_id": f["entidad_id"], "empresa": f["empresa_referencia"], "facturas": 0,
                                                     "costo_base_usd": Decimal(0), "costo_kauta_usd": Decimal(0), "ahorro_usd": Decimal(0),
                                                     "en_revision": 0, "caja_utilizable_usd": _d(datos.entidades[f["entidad_id"]]["caja_utilizable_inicial_usd"])})
        e["facturas"] += 1
        e["costo_base_usd"] += costo(base)
        e["costo_kauta_usd"] += costo(base) if bloqueada else costo(mejor)
        e["ahorro_usd"] += ahorro
        e["en_revision"] += bloqueada
        filas.append({"factura_id": fid, "numero": f["numero_factura"], "empresa": f["empresa_referencia"], "entidad_id": f["entidad_id"],
                      "contraparte": f["contraparte_nombre"], "pais": f["contraparte_pais"], "categoria": f["categoria"],
                      "moneda": f["moneda_factura"], "vencimiento": f["fecha_vencimiento"], "costo_base_usd": _f(costo(base)),
                      "opcion": None if bloqueada else NOMBRES_OPCION.get(mejor["tipo_opcion"], mejor["tipo_opcion"]),
                      "fecha_pago": None if bloqueada else mejor["fecha_pago_inicial"], "riel": mejor["riel_pago"],
                      "costo_kauta_usd": _f(costo(base) if bloqueada else costo(mejor)), "ahorro_usd": _f(ahorro),
                      "ahorro_potencial_reto_usd": _f(_d(f["ahorro_individual_potencial_usd"])), "estado": estado,
                      "motivo": f["motivo_revision"] if bloqueada else ("Descuento vencido a la fecha de corte: no se toma" if vencidas and estado == "contractual" else ""),
                      "descuentos_vencidos": len(vencidas)})
    entidades = []
    for e in por_entidad.values():
        e["margen_usd"] = e["caja_utilizable_usd"] - e["costo_kauta_usd"]
        entidades.append({k: (_f(v) if isinstance(v, Decimal) else v) for k, v in e.items()} | {"cumple_reserva": e["margen_usd"] >= 0})
    cobrar = [f for f in datos.facturas.values() if f["escenario_historia_id"] == "GENERAL" and f["direccion_factura"] == "POR_COBRAR"]
    return {"facturas": filas, "entidades": sorted(entidades, key=lambda x: x["entidad_id"]),
            "ahorro_usd": _f(sum((Decimal(str(x["ahorro_usd"])) for x in filas), Decimal(0))),
            "ahorro_potencial_reto_usd": _f(sum((_d(datos.facturas[x["factura_id"]]["ahorro_individual_potencial_usd"]) for x in filas), Decimal(0))),
            "en_revision": sum(1 for x in filas if x["estado"] == "revision"),
            "por_cobrar": {"facturas": len(cobrar), "total_usd": _f(sum((_d(f["caja_total_pendiente_usd"]) / _d(f["unidades_moneda_por_usd"]) for f in cobrar), Decimal(0)))}}


def resumen(datos: Datos | None = None) -> dict[str, Any]:
    datos = datos or cargar()
    historias = [optimizar_historia(h, datos) for h in ("H1", "H2", "H3")]
    general = analizar_general(datos)
    return {"fecha_corte": datos.fecha_corte.isoformat(), "historias": historias, "general": general,
            "ahorro_historias_usd": _f(sum((Decimal(str(h["ahorro_usd"])) for h in historias), Decimal(0))),
            "coinciden_con_el_reto": sum(1 for h in historias if h["referencia"]["coincide"]), "historias_total": len(historias)}
