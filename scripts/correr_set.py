"""
Corre Kauta sobre una carpeta de facturas y muestra cada decisión con su motivo.

Uso:
    python scripts/correr_set.py                 # modo demo (sin IA), set de 20 facturas
    python scripts/correr_set.py --modo ia       # lee con IA (requiere ANTHROPIC_API_KEY)
    python scripts/correr_set.py --carpeta otra/ # otra carpeta de documentos
El registro de auditoría queda en salidas/registro.jsonl.
"""
import argparse
import csv
import sys
if hasattr(sys.stdout, "reconfigure"):          # en una consola de Windows sin UTF-8, un «✓» no tumba el script
    sys.stdout.reconfigure(errors="replace")
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from kauta.agente import Agente, cargar_json  # noqa: E402
from kauta.extractor import ExtractorReferencia  # noqa: E402
from kauta.registro import Registro  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--modo", choices=["demo", "ia"], default="demo")
ap.add_argument("--carpeta", default=str(RAIZ / "data" / "facturas"))
a = ap.parse_args()

if a.modo == "ia":
    from kauta.extractor import ExtractorIA
    extractor = ExtractorIA()
else:
    extractor = ExtractorReferencia()

salida = RAIZ / "salidas"
salida.mkdir(exist_ok=True)
(salida / "registro.jsonl").unlink(missing_ok=True)
ag = Agente(cargar_json("reglas.json"), cargar_json("beneficiarios.json"), extractor, Registro(salida / "registro.jsonl"))

esperado = {}
p_esp = RAIZ / "data" / "esperado.csv"
if p_esp.exists():
    esperado = {r["factura_id"]: r["decision_esperada"] for r in csv.DictReader(open(p_esp, encoding="utf-8"))}

COLOR = {"pagar": "\033[32m", "frenar": "\033[31m", "escalar": "\033[33m"}
aciertos = 0
for p in sorted(Path(a.carpeta).iterdir()):
    if not p.is_file():
        continue
    try:
        f = ag.procesar(p.name, p.read_bytes())
    except Exception as e:  # noqa: BLE001
        print(f"{p.name}: no se pudo leer ({e})")
        continue
    d = f["decision"]
    ok = ""
    if f["factura_id"] in esperado:
        bien = esperado[f["factura_id"]] == d.decision
        aciertos += bien
        ok = "✓" if bien else f"✗ (esperado {esperado[f['factura_id']]})"
    print(f"{COLOR[d.decision]}{f['factura_id']} {d.decision.upper():8s}\033[0m {ok}  {d.motivo}")

m = ag.metricas()
print("\n" + "-" * 80)
print(f"Facturas: {m['total']} · pagadas {m['pagadas']} · frenadas {m['frenadas']} · pendientes {m['pendientes']}")
print(f"Autonomía: {m['autonomia_pct']} % · Pagos indebidos: {m['pagos_fuera_de_reglas']} · Explicadas: {m['explicadas_pct']} %")
if esperado:
    print(f"Decisiones correctas frente a esperado.csv: {aciertos}/{len(esperado)}")
print(f"Registro íntegro: {ag.registro.verificar()[0]} · {salida / 'registro.jsonl'}")
