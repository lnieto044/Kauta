"""
Mide qué tan bien lee la IA: compara la extracción contra data/referencia_extracciones.json.

Uso:
    python scripts/medir_extraccion.py --modo ia      # requiere ANTHROPIC_API_KEY
    python scripts/medir_extraccion.py --modo demo    # verificación del script (debe dar 100 %)

Guarda las extracciones de la IA en salidas/extracciones_ia.json (sirven de caché para la demo).
"""
import argparse
import json
import sys
if hasattr(sys.stdout, "reconfigure"):          # en una consola de Windows sin UTF-8, un «✓» no tumba el script
    sys.stdout.reconfigure(errors="replace")
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from kauta.extractor import ExtractorReferencia  # noqa: E402
from kauta.motor import normalizar_id  # noqa: E402

CAMPOS = ["id_fiscal", "numero_factura", "moneda", "monto", "fecha_vencimiento", "cuenta_destino"]

ap = argparse.ArgumentParser()
ap.add_argument("--modo", choices=["demo", "ia"], default="ia")
a = ap.parse_args()
if a.modo == "ia":
    from kauta.extractor import ExtractorIA
    ex = ExtractorIA()
else:
    ex = ExtractorReferencia()
ref = json.loads((RAIZ / "data" / "referencia_extracciones.json").read_text(encoding="utf-8"))


def valor(e, campo):
    if campo == "id_fiscal":
        return normalizar_id((e.get("beneficiario") or {}).get("id_fiscal"))
    if campo == "numero_factura":
        return normalizar_id(e.get("numero_factura"))
    return e.get(campo)


def igual(a_, b_, campo):
    if campo == "monto":
        return a_ is not None and b_ is not None and abs(float(a_) - float(b_)) < 0.01
    return (a_ or None) == (b_ or None)


totales = {c: 0 for c in CAMPOS}
guardado = {}
for nombre, r in sorted(ref.items()):
    p = RAIZ / "data" / "facturas" / nombre
    out = ex.extraer(nombre, p.read_bytes())["extraccion"]
    guardado[nombre] = out
    fallas = []
    for c in CAMPOS:
        if igual(valor(out, c), valor(r, c), c):
            totales[c] += 1
        else:
            fallas.append(f"{c}: leyó {valor(out, c)!r}, esperado {valor(r, c)!r}")
    alerta = " · alerta de instrucción" if "instruccion_sospechosa" in out.get("alertas", []) else ""
    conf = out.get("confianza", {}).get("monto")
    print(f"{r['factura_id']} {'OK ' if not fallas else 'REV'} confianza monto={conf}{alerta}")
    for f in fallas:
        print("      -", f)

n = len(ref)
print("\nPrecisión por campo:")
for c in CAMPOS:
    print(f"  {c:18s} {totales[c]}/{n}  ({100 * totales[c] / n:.0f} %)")
salida = RAIZ / "salidas"
salida.mkdir(exist_ok=True)
(salida / "extracciones_ia.json").write_text(json.dumps(guardado, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\nExtracciones guardadas en {salida / 'extracciones_ia.json'}")
print("Nota: en F13 (foto borrosa) lo correcto es que la confianza del monto sea baja, no que adivine.")
