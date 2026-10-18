"""
Arma el kit que se entrega: kauta-kit-v2.zip, con todo lo necesario para correr Kauta.

Incluye el código (núcleo, servidor y pantalla ya compilada), los datos ficticios, las pruebas y
los archivos de despliegue. Deja fuera lo que no debe viajar: entornos virtuales, cachés, la base
de datos de la demo, las claves de var/ y node_modules.

Uso: python scripts/empaquetar.py [salida.zip]
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
SALIDA = Path(sys.argv[1]) if len(sys.argv) > 1 else RAIZ.parent / "entregas" / "kauta-kit-v2.zip"

CARPETAS = ["kauta", "servidor", "data", "scripts", "tests", "assets", "static", "web/src", "web/public", "web/dist",
            ".vscode", "facturas_de_prueba"]
SUELTOS = ["README.md", "requirements.txt", "requirements-servidor.txt", "Dockerfile", "Dockerfile.vercel", "docker-compose.yml",
           ".env.example", ".dockerignore", ".gitignore", ".gitattributes", ".vercelignore", "app.py", "web/package.json",
           "web/package-lock.json", "web/index.html", "web/tsconfig.json", "web/tsconfig.node.json", "web/vite.config.ts"]
EXCLUIR_PARTES = {"__pycache__", ".pytest_cache", "node_modules", ".venv", ".git", ".ruff_cache"}
EXCLUIR_SUFIJOS = {".pyc", ".pyo", ".log", ".db", ".sqlite", ".sqlite3"}


def incluir(p: Path) -> bool:
    if any(parte in EXCLUIR_PARTES for parte in p.parts):
        return False
    if p.suffix.lower() in EXCLUIR_SUFIJOS:
        return False
    if p.name.startswith(".") and p.parent.name != ".vscode":
        return p.name in (".env.example", ".dockerignore", ".gitignore")
    return True


def main() -> None:
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.unlink(missing_ok=True)
    n, bytes_ = 0, 0
    with zipfile.ZipFile(SALIDA, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for rel in SUELTOS:
            p = RAIZ / rel
            if p.exists():
                z.write(p, f"kauta/{rel}")
                n, bytes_ = n + 1, bytes_ + p.stat().st_size
        for carpeta in CARPETAS:
            base = RAIZ / carpeta
            if not base.exists():
                continue
            for p in sorted(base.rglob("*")):
                if p.is_file() and incluir(p.relative_to(RAIZ)):
                    z.write(p, f"kauta/{p.relative_to(RAIZ).as_posix()}")
                    n, bytes_ = n + 1, bytes_ + p.stat().st_size
    print(f"{SALIDA}  ·  {n} archivos  ·  {bytes_ / 1e6:.1f} MB sin comprimir  ·  "
          f"{SALIDA.stat().st_size / 1e6:.1f} MB comprimido")


if __name__ == "__main__":
    main()
