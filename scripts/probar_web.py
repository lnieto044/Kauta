"""
Prueba de punta a punta de la pantalla (React + FastAPI) con Playwright, clic a clic y con los tres roles:
se parte de la demo con sus 50 facturas; llega una factura de monto alto (se prepara con la API de datos de la demo, como si
hubiera llegado por correo); Finanzas no puede aprobarla (supera el umbral); el CEO la aprueba con su token; el CEO aprueba
una ruta de pago del reto y la auditoría queda íntegra; Finanzas la paga en «Pagos» con su token y la ventana de PayPal
(simulada si el servidor no tiene credenciales del sandbox) y ve el resultado.
Guarda capturas para la documentación.
Uso: python scripts/probar_web.py [carpeta_salida]
Servidor en modo demo y sin SMTP (los tokens se leen del buzón de la demo). Por defecto http://127.0.0.1:8000 y var/;
otro servidor con KAUTA_URL y KAUTA_VAR. Si Playwright no descargó su navegador, usa el Chrome instalado.
"""
from __future__ import annotations

import email
import email.policy
import os
import re
import sys
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = os.environ.get("KAUTA_URL", "http://127.0.0.1:8000").rstrip("/")
SALIDA = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("capturas_web")
BUZON = Path(os.environ.get("KAUTA_VAR", Path(__file__).resolve().parents[1] / "var")) / "correos"
CLAVE = "Kauta-30X-demo-2026"
CORREOS = {"Equipo Kauta": "equipo@kauta.example", "Mariana Torres": "mariana.torres@brisamar.example",
           "Carlos Rivera": "carlos.rivera@brisamar.example"}
COMENTARIO = "Ej.: Llamé al número registrado"


def entrar(pag, nombre: str) -> None:
    """Inicio de sesión real: correo y contraseña en el formulario."""
    pag.goto(BASE + "/")
    pag.wait_for_load_state("networkidle")
    pag.get_by_label("Correo").fill(CORREOS[nombre])
    pag.get_by_label("Contraseña", exact=True).fill(CLAVE)
    pag.get_by_role("button", name="Iniciar sesión").click()
    pag.wait_for_selector("main")
    pag.wait_for_load_state("networkidle")


def salir(pag, movil: bool) -> None:
    """Cierra la sesión desde el menú de la cuenta."""
    if movil:
        pag.get_by_role("button", name="Más").click()
        pag.get_by_role("button", name="Cerrar sesión").click()
    else:
        pag.locator("button[aria-haspopup=menu]").click()
        pag.get_by_role("menuitem", name="Cerrar sesión").click()
    pag.wait_for_timeout(500)


def cambiar_a(pag, nombre: str, movil: bool, ruta: str) -> None:
    salir(pag, movil)
    entrar(pag, nombre)
    pag.goto(f"{BASE}/#/{ruta}")
    pag.wait_for_load_state("networkidle")


def preparar_factura(pag, escenario: str) -> str:
    """Hace llegar una factura del set de casos de la demo (equivale a que entre por correo) y devuelve su id."""
    return pag.evaluate("""async (esc) => {
        const yo = await (await fetch('/api/auth/yo')).json();
        const h = {'Content-Type': 'application/json', 'X-CSRF-Token': yo.usuario.csrf};
        const d = await (await fetch(`/api/simulador/escenarios/${esc}?periodo=2026-11`)).json();
        const r = await fetch('/api/simulador/factura', {method: 'POST', headers: h, body: JSON.stringify({...d, riel: 'PAYPAL'})});
        if (!r.ok) throw new Error(await r.text());
        return (await r.json()).id;
    }""", escenario)


def reiniciar_demo(pag) -> None:
    """Vuelve la demo a sus 50 facturas de ejemplo (endpoint solo de modo demo, sin botón en la pantalla)."""
    estado = pag.evaluate("""async () => {
        const yo = await (await fetch('/api/auth/yo')).json();
        const r = await fetch('/api/demo/restablecer', {method: 'POST', body: JSON.stringify({con_set: true}),
            headers: {'Content-Type': 'application/json', 'X-CSRF-Token': yo.usuario.csrf}});
        return r.status;
    }""")
    assert estado == 200, f"No se pudo restablecer la demo ({estado})"
    pag.reload()
    pag.wait_for_load_state("networkidle")


def autorizar(pag, correo: str, campo: str = "Token de autorización") -> None:
    """Pide el token (de aprobación o de pago) y lo escribe, leyéndolo del buzón de la demo."""
    antes = set(BUZON.glob("*.eml")) if BUZON.exists() else set()
    pag.get_by_role("button", name="Enviar token a mi correo").click()
    pag.wait_for_timeout(1200)
    nuevos = sorted(p for p in BUZON.glob("*.eml") if p not in antes and correo.split("@")[0].replace(".", "-") in p.name)
    texto = email.message_from_bytes(nuevos[-1].read_bytes(), policy=email.policy.default).get_content()
    pag.get_by_label(campo).press_sequentially(re.search(r"^\s+(\d{6})$", texto, re.M).group(1), delay=30)  # tecla a tecla


def main() -> None:
    SALIDA.mkdir(parents=True, exist_ok=True)
    errores: list[str] = []
    with sync_playwright() as p:
        try:
            nav = p.chromium.launch()
        except Exception:
            nav = p.chromium.launch(channel="chrome")
        for nombre_vista, (w, h, esc) in {"escritorio": (1440, 900, 1.5), "movil": (390, 844, 2)}.items():
            movil = nombre_vista == "movil"
            ctx = nav.new_context(viewport={"width": w, "height": h}, device_scale_factor=esc, locale="es-CO", timezone_id="America/Bogota")
            ctx.add_init_script("try { localStorage.setItem('kauta.intro.desactivada', '1') } catch (e) {}")  # sin la intro automática
            pag = ctx.new_page()
            pag.on("pageerror", lambda e: errores.append(f"pageerror: {e}"))
            pag.on("console", lambda m: errores.append(m.text) if m.type == "error" and "401" not in m.text else None)

            # 1. Administración restablece la demo (el Administrador no aprueba ni paga)
            entrar(pag, "Equipo Kauta")
            reiniciar_demo(pag)                       # ya no está en la pantalla: se usa la API, solo en modo demo
            fid = preparar_factura(pag, "supera_umbral")
            pag.goto(f"{BASE}/#/facturas/{fid}")
            pag.wait_for_load_state("networkidle")
            expect(pag.get_by_role("button", name="Enviar token a mi correo")).to_have_count(0)  # no puede aprobar

            # 2. Finanzas no aprueba montos altos: la factura le corresponde al CEO
            cambiar_a(pag, "Mariana Torres", movil, f"facturas/{fid}")
            expect(pag.get_by_text("la aprueba el CEO").first).to_be_visible(timeout=8000)
            expect(pag.get_by_role("button", name="Enviar token a mi correo")).to_have_count(0)

            # 3. El CEO la aprueba con su token: queda lista para pagar (aprobar no paga)
            cambiar_a(pag, "Carlos Rivera", movil, f"facturas/{fid}")
            pag.get_by_placeholder(COMENTARIO).fill("Proyecto especial aprobado por el comité de gerencia.")
            autorizar(pag, CORREOS["Carlos Rivera"])
            pag.get_by_role("button", name="Aprobar", exact=True).click()
            expect(pag.get_by_text("Lista para pagar").first).to_be_visible(timeout=15000)

            # 4. El CEO aprueba la ruta de pago de una historia del reto
            pag.goto(f"{BASE}/#/rutas")
            pag.wait_for_load_state("networkidle")
            expect(pag.get_by_text("3 de 3")).to_be_visible(timeout=15000)
            pag.get_by_role("tab", name=re.compile("H2")).click()
            pag.get_by_placeholder("Ej.: Negociar").fill("Confirmar con el proveedor el pago en MXN y la cotización del día.")
            pag.get_by_role("button", name="Aprobar ruta").click()
            expect(pag.get_by_text("Aprobada por Carlos Rivera").first).to_be_visible(timeout=8000)
            pag.wait_for_timeout(4800)
            pag.screenshot(path=str(SALIDA / f"ruta_aprobada_{nombre_vista}.png"), full_page=True)

            # 5. Auditoría íntegra
            pag.goto(f"{BASE}/#/auditoria")
            expect(pag.get_by_text("Cadena íntegra").first).to_be_visible(timeout=8000)

            # 6. Finanzas la paga en «Pagos» con su token y la ventana de PayPal, y ve el resultado
            cambiar_a(pag, "Mariana Torres", movil, "pagos")
            fila = pag.locator("li", has_text=fid).first
            fila.get_by_role("button", name="Pagar").click()
            autorizar(pag, CORREOS["Mariana Torres"], "Token de pago")
            pag.get_by_role("button", name=re.compile("Ir a PayPal a pagar")).click()
            if "sandbox.paypal.com" in pag.url:
                print("  (PayPal real: la ventana del sandbox pide la cuenta de pruebas; se deja ahí)")
            else:
                expect(pag.get_by_role("button", name="Aprobar el pago")).to_be_visible(timeout=10000)
                pag.get_by_role("button", name="Aprobar el pago").click()
                expect(pag.get_by_text("Pago exitoso").first).to_be_visible(timeout=15000)
                pag.wait_for_timeout(800)
                pag.screenshot(path=str(SALIDA / f"pago_paypal_{nombre_vista}.png"), full_page=False)
                pag.get_by_role("button", name="Listo").click()
            pag.goto(f"{BASE}/#/resumen")
            pag.wait_for_load_state("networkidle")
            pag.wait_for_timeout(600)
            pag.screenshot(path=str(SALIDA / f"resumen_final_{nombre_vista}.png"), full_page=True)
            ctx.close()
        nav.close()
    print("Flujo completo superado. Capturas en", SALIDA)
    for e in sorted(set(errores)):
        print("  ", e)


if __name__ == "__main__":
    main()
