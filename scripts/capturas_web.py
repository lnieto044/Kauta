"""
Capturas de la pantalla nueva (React) en celular, tableta y computador con Playwright.
Uso: python scripts/capturas_web.py [carpeta_salida] [--solo pagina1,pagina2]
Requiere el servidor corriendo en http://127.0.0.1:8000 (uvicorn servidor.main:app) u otro en KAUTA_URL.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = os.environ.get("KAUTA_URL", "http://127.0.0.1:8000").rstrip("/")
SALIDA = Path(sys.argv[1]) if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else Path("capturas_web")
SOLO = next((a.split("=", 1)[1].split(",") for a in sys.argv if a.startswith("--solo=")), None)
VISTAS = {"movil": (390, 844), "tableta": (834, 1112), "escritorio": (1440, 900)}
# Cada rol ve sus propias secciones: Finanzas opera y el CEO decide y controla
PAGINAS = {"mariana.torres@brisamar.example": ["resumen", "rendimiento", "rutas", "facturas", "facturas/F09", "facturas/F04", "pregunta",
                                               "proveedores", "wallet", "seguridad"],
           "carlos.rivera@brisamar.example": ["reglas", "auditoria"]}


def entrar(pag, correo: str, clave: str = "Kauta-30X-demo-2026") -> None:
    """Inicio de sesión real con el formulario (ya no hay acceso con un clic)."""
    pag.get_by_label("Correo").fill(correo)
    pag.get_by_label("Contraseña", exact=True).fill(clave)
    pag.get_by_role("button", name="Iniciar sesión").click()
    pag.wait_for_selector("main", timeout=15000)


def main() -> None:
    SALIDA.mkdir(parents=True, exist_ok=True)
    errores = []
    with sync_playwright() as p:
        try:
            nav = p.chromium.launch()
        except Exception:
            nav = p.chromium.launch(channel="chrome")   # sin el navegador de Playwright, el Chrome instalado
        for nombre, (w, h) in VISTAS.items():
            ctx = nav.new_context(viewport={"width": w, "height": h}, device_scale_factor=2 if nombre == "movil" else 1.5,
                                  locale="es-CO", timezone_id="America/Bogota")
            pag = ctx.new_page()
            pag.on("console", lambda m: errores.append(f"{m.type}: {m.text}") if m.type in ("error", "warning") else None)
            pag.on("pageerror", lambda e: errores.append(f"pageerror: {e}"))
            pag.goto(BASE + "/")
            pag.wait_for_load_state("networkidle")
            if not SOLO or "login" in SOLO:
                pag.screenshot(path=str(SALIDA / f"login_{nombre}.png"), full_page=True)
            if not SOLO or "registro" in SOLO:
                pag.get_by_role("button", name="Solicitar acceso").click()
                pag.wait_for_timeout(300)
                pag.screenshot(path=str(SALIDA / f"registro_{nombre}.png"), full_page=True)
                pag.get_by_role("button", name="Volver a iniciar sesión").click()
            for correo, rutas in PAGINAS.items():
                if SOLO and not set(rutas) & set(SOLO):
                    continue
                if pag.locator("main").count():
                    pag.context.clear_cookies()
                    pag.goto(BASE + "/")
                    pag.wait_for_load_state("networkidle")
                entrar(pag, correo)
                pag.wait_for_load_state("networkidle")
                for ruta in rutas:
                    if SOLO and ruta not in SOLO:
                        continue
                    pag.goto(f"{BASE}/#/{ruta}")
                    pag.wait_for_load_state("networkidle")
                    pag.wait_for_timeout(700)
                    pag.screenshot(path=str(SALIDA / f"{ruta.replace('/', '_')}_{nombre}.png"), full_page=True)
            ctx.close()

            # «Personas y roles» solo la ve administración: sesión aparte para no mezclar permisos
            if not SOLO or "personas" in SOLO:
                ctx2 = nav.new_context(viewport={"width": w, "height": h}, device_scale_factor=2 if nombre == "movil" else 1.5,
                                       locale="es-CO", timezone_id="America/Bogota")
                pag2 = ctx2.new_page()
                pag2.goto(BASE + "/")
                pag2.wait_for_load_state("networkidle")
                entrar(pag2, "equipo@kauta.example")
                pag2.goto(f"{BASE}/#/personas")
                pag2.wait_for_load_state("networkidle")
                expect(pag2.get_by_text("Cuentas (")).to_be_visible(timeout=15000)
                pag2.wait_for_timeout(500)
                pag2.screenshot(path=str(SALIDA / f"personas_{nombre}.png"), full_page=True)
                ctx2.close()
        nav.close()
    print("Capturas en", SALIDA)
    for e in sorted(set(errores))[:30]:
        print("  ", e)


if __name__ == "__main__":
    main()
