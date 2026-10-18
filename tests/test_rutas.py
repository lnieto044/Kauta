"""Rutas de pago del reto: el motor de Kauta debe llegar a la misma respuesta que resumen_rutas.csv."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kauta import rutas  # noqa: E402

DATOS = rutas.cargar()


@pytest.mark.parametrize("historia", ["H1", "H2", "H3"])
def test_ruta_igual_a_la_referencia_del_reto(historia):
    r = rutas.optimizar_historia(historia)
    for tipo, ruta in (("BASE", r["base"]), ("KAUTA", r["kauta"])):
        ref = DATOS.referencia[f"{historia}-{tipo}"]
        assert ruta["costo_usd"] == pytest.approx(float(ref["costo_ruta_usd"]), abs=0.01)
        assert ruta["saldo_minimo_consolidado_usd"] == pytest.approx(float(ref["saldo_minimo_consolidado_usd"]), abs=0.01)
        assert ruta["saldo_final_usd"] == pytest.approx(float(ref["saldo_final_usd"]), abs=0.01)
        assert ruta["minimo_margen_individual_usd"] == pytest.approx(float(ref["minimo_margen_individual_usd"]), abs=0.01)
        assert ruta["cumple_reservas"] is (ref["cumple_reservas_todas_entidades"] == "SI")
    assert r["ahorro_usd"] == pytest.approx(float(DATOS.referencia[f"{historia}-KAUTA"]["ahorro_neto_usd"]), abs=0.01)


def test_ninguna_ruta_rompe_la_reserva_ni_mezcla_cajas():
    for h in ("H1", "H2", "H3"):
        r = rutas.optimizar_historia(h)
        assert all(e["margen_usd"] >= 0 for e in r["kauta"]["eventos"])
        entidades_factura = {DATOS.facturas[o["factura_id"]]["entidad_id"] for o in r["kauta"]["opciones"]}
        assert {e["entidad_id"] for e in r["kauta"]["eventos"]} <= entidades_factura   # cada pago sale de su propia entidad


def test_negociacion_conjunta_va_completa():
    opciones = {o["factura_id"]: o["tipo_opcion"] for o in rutas.optimizar_historia("H3")["kauta"]["opciones"]}
    assert opciones["SIM-H3-A-OBRA"] == opciones["SIM-H3-B-OBRA"] == "HITOS_VOLUMEN"


def test_la_ruta_marca_lo_que_necesita_una_persona():
    h1 = rutas.optimizar_historia("H1")["kauta"]
    assert h1["requiere_aprobacion"] and any("cobro previsto" in c for c in h1["condiciones"])
    h2 = rutas.optimizar_historia("H2")["kauta"]
    assert h2["requiere_aprobacion"] and any("MXN" in c for c in h2["condiciones"])


def test_general_respeta_revision_y_descuentos_vencidos():
    g = rutas.analizar_general()
    revision = [f for f in g["facturas"] if f["estado"] == "revision"]
    assert len(revision) == 15 and all(f["ahorro_usd"] == 0 and f["opcion"] is None for f in revision)
    for f in g["facturas"]:
        if f["estado"] != "revision":
            alt = next(o for o in DATOS.opciones[f["factura_id"]] if rutas.NOMBRES_OPCION[o["tipo_opcion"]] == f["opcion"])
            assert not rutas.vencida(alt, DATOS.fecha_corte)                      # nunca un descuento ya vencido
    assert g["ahorro_usd"] < g["ahorro_potencial_reto_usd"]                      # el potencial del reto no es todo ejecutable
    assert all(e["cumple_reserva"] for e in g["entidades"])
