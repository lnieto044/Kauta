"""
Mide el lector local (OCR, sin IA) contra las extracciones verificadas del set.
Uso: python scripts/medir_ocr.py            (requiere Tesseract con spa+eng)
"""
from __future__ import annotations

import json
import sys
if hasattr(sys.stdout, "reconfigure"):          # en una consola de Windows sin UTF-8, un «✓» no tumba el script
    sys.stdout.reconfigure(errors="replace")
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from kauta import ocr  # noqa: E402
from kauta.normalizacion import solo_alnum  # noqa: E402

CAMPOS = ["beneficiario", "id_fiscal", "numero_factura", "moneda", "monto", "cuenta_destino"]


def valor(ext, campo):
    if campo in ("beneficiario", "id_fiscal"):
        return (ext.get("beneficiario") or {}).get("nombre" if campo == "beneficiario" else "id_fiscal")
    return ext.get(campo)


def iguales(campo, a, b):
    if a is None or b is None:
        return a == b
    if campo == "monto":
        return abs(float(a) - float(b)) < 0.01
    if campo in ("beneficiario", "id_fiscal"):
        x, y = solo_alnum(str(a)).upper(), solo_alnum(str(b)).upper()
        return x.startswith(y[:14]) or y.startswith(x[:14])
    return str(a).strip().upper() == str(b).strip().upper()


def main() -> None:
    if not ocr.disponible():
        print("Tesseract con el idioma spa no está instalado; el lector local no se puede medir.")
        print("Debian/Ubuntu: sudo apt-get install tesseract-ocr tesseract-ocr-spa tesseract-ocr-eng")
        return
    ref = json.loads((RAIZ / "data" / "referencia_extracciones.json").read_text(encoding="utf-8"))
    aciertos = {c: [0, 0] for c in CAMPOS}
    filas = []
    for archivo, esperado in sorted(ref.items()):
        p = RAIZ / "data" / "facturas" / archivo
        if p.suffix.lower() not in (".pdf", ".jpg", ".jpeg", ".png"):
            continue
        leido = ocr.leer(p.name, p.read_bytes())
        if not leido:
            filas.append((archivo, "sin lectura", {}))
            continue
        detalle = {}
        for c in CAMPOS:
            e, l = valor(esperado, c), valor(leido, c)
            if e is None:
                continue
            aciertos[c][1] += 1
            bien = iguales(c, l, e)
            aciertos[c][0] += bien
            detalle[c] = (bien, l, e)
        filas.append((archivo, leido.get("metodo_lectura"), detalle))
    print(f"{'Documento':38s} {'Campos':>8s}  Diferencias")
    for archivo, _metodo, detalle in filas:
        malos = [f"{c}: leyó {v[1]!r} y es {v[2]!r}" for c, v in detalle.items() if not v[0]]
        n_ok = sum(1 for v in detalle.values() if v[0])
        print(f"{archivo[:38]:38s} {n_ok:>3d}/{len(detalle):<4d} {'· '.join(malos) if malos else 'todo correcto'}")
    print()
    total_ok = sum(v[0] for v in aciertos.values())
    total = sum(v[1] for v in aciertos.values())
    for c, (ok, n) in aciertos.items():
        print(f"  {c:16s} {ok:2d}/{n:<3d} {100 * ok / n if n else 0:5.1f} %")
    print(f"  {'TOTAL':16s} {total_ok:2d}/{total:<3d} {100 * total_ok / total if total else 0:5.1f} %")


if __name__ == "__main__":
    main()
