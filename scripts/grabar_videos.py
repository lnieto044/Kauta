"""
Kauta · videos de introducción por rol, grabados sobre la aplicación real con Playwright.

Cada video recorre lo que ese rol encuentra y hace, con subtítulos en pantalla y un cursor visible:
  * Finanzas: de la factura que llega hasta el pago con la ventana de PayPal y su resultado.
  * CEO: lo que espera su aprobación, aprobar un monto alto, rutas de pago, reglas, rendimiento y auditoría.
  * Administrador: la plataforma, personas y roles, seguridad, la conexión con PayPal y la supervisión en consulta.

Con locución: una voz neuronal colombiana (es-CO-SalomeNeural, la de la lectura en voz alta de Microsoft Edge, por medio de
la librería edge-tts) lee cada subtítulo, con las siglas dichas en palabras. Primero se genera toda la voz; el video espera
lo que dura cada frase y al final ffmpeg (imageio-ffmpeg) monta la voz en su momento exacto y comprime en VP9 + Opus.

Salida: web/public/videos/introduccion-<rol>.webm y web/public/videos/capitulos.json (los capítulos de cada video).
Necesita un servidor de Kauta en modo demo, recién iniciado y SIN credenciales de PayPal (la ventana de PayPal se
simula), Playwright con ffmpeg (python -m playwright install ffmpeg), edge-tts e imageio-ffmpeg
(pip install edge-tts imageio-ffmpeg) e internet para generar la voz. Uso:
  KAUTA_URL=http://localhost:8010 KAUTA_VAR=<carpeta var de ese servidor> python scripts/grabar_videos.py
"""
from __future__ import annotations

import ast
import asyncio
import email
import email.policy
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

RAIZ = Path(__file__).resolve().parents[1]
BASE = os.environ.get("KAUTA_URL", "http://localhost:8010").rstrip("/")
BUZON = Path(os.environ.get("KAUTA_VAR", RAIZ / "var")) / "correos"
SALIDA = RAIZ / "web" / "public" / "videos"
CLAVE = "Kauta-30X-demo-2026"
ANCHO, ALTO = 1280, 720
VOZ = "es-CO-SalomeNeural"          # colombiana, femenina
RITMO, TONO, VOLUMEN = "+10%", "+4Hz", "+10%"   # con energía: más ágil, un poco más aguda y con más presencia
CACHE_VOZ = RAIZ / "var" / "_voz"

# Lo que en pantalla va en siglas, la voz lo dice en palabras
DICHO = [
    (r"USD 3\.000", "tres mil dólares"), (r"USD 10\.000", "diez mil dólares"), (r"USD 15\.000", "quince mil dólares"),
    (r"\(R07\)", ""), (r"\bR07\b", "la regla siete"), (r"\bF12\b", "efe doce"), (r"\bOCR\b", "o ce erre"),
    (r"\bXML\b", "equis eme ele"), (r"\bPDF\b", "pe de efe"), (r"\bHMAC\b", "una firma criptográfica"),
    (r"\bsin IA\b", "sin inteligencia artificial"), (r"\bla IA\b", "la inteligencia artificial"), (r"\bel CEO\b", "el gerente general"),
    (r"\bCEO\b", "gerente general"), (r"·", ","), (r"«|»", ""),
]


def para_voz(texto: str) -> str:
    for a, b in DICHO:
        texto = re.sub(a, b, texto)
    return re.sub(r"\s{2,}", " ", texto).strip()


def frases_del_guion() -> list[str]:
    """Todo lo que la voz va a decir, leído del propio guion (los textos de decir() y tarjeta())."""
    salida = []
    for nodo in ast.walk(ast.parse(Path(__file__).read_text(encoding="utf-8"))):
        if isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Attribute) and nodo.func.attr in ("decir", "tarjeta"):
            args = [a.value for a in nodo.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
            if nodo.func.attr == "decir" and len(args) >= 2:
                salida.append(para_voz(args[1]))
            elif nodo.func.attr == "tarjeta" and len(args) >= 3:
                salida.append(para_voz(frase_tarjeta(*args[:3])))
    return salida


def frase_tarjeta(antes: str, titulo: str, texto: str) -> str:
    """La voz de una tarjeta de título; la del comienzo saluda."""
    saludo = "¡Hola! ¡Le damos la bienvenida a Kauta! " if antes.startswith("Introducción") else ""
    return f"{saludo}{titulo}{' ' if titulo[-1:] in '!?.' else '. '}{texto}"


def _clip(frase: str) -> Path:
    return CACHE_VOZ / (hashlib.sha1(f"{VOZ}|{RITMO}|{TONO}|{VOLUMEN}|{frase}".encode()).hexdigest()[:16] + ".mp3")


def duracion(ruta: Path) -> float:
    import imageio_ffmpeg
    r = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-i", str(ruta)], capture_output=True, text=True)
    h, m, sg = re.search(r"Duration: (\d+):(\d+):([\d.]+)", r.stderr).groups()
    return int(h) * 3600 + int(m) * 60 + float(sg)


def preparar_voz(frases: list[str]) -> dict[str, tuple[Path, float]]:
    """Genera (o toma de la caché) la voz de cada frase. Devuelve frase → (archivo, segundos)."""
    import edge_tts
    CACHE_VOZ.mkdir(parents=True, exist_ok=True)
    faltan = [f for f in dict.fromkeys(frases) if not _clip(f).exists()]

    async def una(frase: str, sem: asyncio.Semaphore):
        async with sem:
            for intento in range(3):
                try:
                    await edge_tts.Communicate(frase, VOZ, rate=RITMO, volume=VOLUMEN, pitch=TONO).save(str(_clip(frase)))
                    return
                except Exception:  # noqa: BLE001 - un corte de red se reintenta
                    await asyncio.sleep(1.5 * (intento + 1))
            raise RuntimeError(f"No se pudo generar la voz de: {frase[:60]}")

    async def todas():
        sem = asyncio.Semaphore(4)
        await asyncio.gather(*(una(f, sem) for f in faltan))
    if faltan:
        asyncio.run(todas())
    return {f: (_clip(f), duracion(_clip(f))) for f in dict.fromkeys(frases)}


def montar(video: Path, pistas: list[tuple[float, Path]], destino: Path, total: float) -> None:
    """Pone cada frase en su segundo exacto sobre el video y comprime: VP9 (pantalla nítida) + Opus (voz)."""
    import imageio_ffmpeg
    entradas, filtros = ["-i", str(video)], []
    for i, (t, clip) in enumerate(pistas, start=1):
        entradas += ["-i", str(clip)]
        ms = int(max(0.0, t) * 1000)
        filtros.append(f"[{i}:a]adelay={ms}|{ms},volume=1.15[a{i}]")
    mezcla = "".join(f"[a{i}]" for i in range(1, len(pistas) + 1))
    filtros.append(f"{mezcla}amix=inputs={len(pistas)}:normalize=0:dropout_transition=0,apad,atrim=0:{total:.2f}[voz]")
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y", *entradas,
                    "-filter_complex", ";".join(filtros), "-map", "0:v", "-map", "[voz]",
                    "-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "42", "-row-mt", "1", "-deadline", "good", "-cpu-used", "5", "-r", "20",
                    "-c:a", "libopus", "-b:a", "56k", "-ac", "1", "-t", f"{total:.2f}", str(destino)], check=True)

# Subtítulos, tarjetas de título y un cursor visible (Playwright no graba el puntero del sistema)
CAPA = """
(() => {
  if (window.__kautaCapa) return; window.__kautaCapa = true;
  const css = `
    #kv-sub{position:fixed;left:50%;bottom:26px;transform:translateX(-50%);max-width:980px;z-index:2147483646;pointer-events:none;
      background:rgba(11,23,54,.93);color:#fff;font:500 19px/1.45 Inter,system-ui,sans-serif;padding:14px 22px 14px 18px;border-radius:12px;
      box-shadow:0 10px 30px rgba(11,23,54,.35);display:flex;gap:14px;align-items:flex-start;opacity:0;transition:opacity .35s}
    #kv-sub b{flex:none;font:700 12px/1 Inter,system-ui;letter-spacing:.06em;text-transform:uppercase;background:#3B5BFD;padding:6px 8px;border-radius:6px;margin-top:3px}
    #kv-tarjeta{position:fixed;inset:0;z-index:2147483647;pointer-events:none;background:#0B1736;color:#fff;display:flex;flex-direction:column;
      align-items:center;justify-content:center;gap:14px;font-family:Inter,system-ui,sans-serif;opacity:0;transition:opacity .45s;text-align:center;padding:40px}
    #kv-tarjeta h1{font-size:44px;font-weight:700;margin:0;letter-spacing:-.02em} #kv-tarjeta p{font-size:21px;color:#C9D2E8;max-width:860px;margin:0;line-height:1.45}
    #kv-tarjeta small{font-size:14px;letter-spacing:.14em;text-transform:uppercase;color:#16C79A;font-weight:700}
    #kv-cursor{position:fixed;left:0;top:0;width:22px;height:22px;margin:-11px 0 0 -11px;border-radius:50%;z-index:2147483647;pointer-events:none;
      background:rgba(59,91,253,.35);border:2px solid #3B5BFD;box-shadow:0 0 0 3px rgba(255,255,255,.85);transition:transform .45s cubic-bezier(.2,.7,.2,1)}
    #kv-cursor.clic{animation:kvclic .45s ease-out} @keyframes kvclic{0%{box-shadow:0 0 0 3px rgba(255,255,255,.85),0 0 0 0 rgba(59,91,253,.5)}
      100%{box-shadow:0 0 0 3px rgba(255,255,255,.85),0 0 0 22px rgba(59,91,253,0)}}`;
  const montar = () => {
    const st = document.createElement("style"); st.textContent = css; document.head.appendChild(st);
    for (const id of ["kv-sub", "kv-tarjeta", "kv-cursor"]) { const d = document.createElement("div"); d.id = id; document.body.appendChild(d); }
    const c = document.getElementById("kv-cursor");
    const x = sessionStorage.getItem("kv-x"), y = sessionStorage.getItem("kv-y");
    c.style.transform = `translate(${x ?? 640}px, ${y ?? 360}px)`;
    addEventListener("mousemove", (e) => { c.style.transform = `translate(${e.clientX}px, ${e.clientY}px)`;
      sessionStorage.setItem("kv-x", e.clientX); sessionStorage.setItem("kv-y", e.clientY); }, true);
    addEventListener("mousedown", () => { c.classList.remove("clic"); void c.offsetWidth; c.classList.add("clic"); }, true);
    const sub = sessionStorage.getItem("kv-subtitulo");
    if (sub) { const s = JSON.parse(sub); window.__kautaSub(s.texto, s.etiqueta); }
  };
  window.__kautaSub = (texto, etiqueta) => {
    const s = document.getElementById("kv-sub"); if (!s) return;
    if (!texto) { s.style.opacity = 0; sessionStorage.removeItem("kv-subtitulo"); return; }
    s.innerHTML = ""; const b = document.createElement("b"); b.textContent = etiqueta; const t = document.createElement("span"); t.textContent = texto;
    s.append(b, t); s.style.opacity = 1; sessionStorage.setItem("kv-subtitulo", JSON.stringify({texto, etiqueta}));
  };
  window.__kautaTarjeta = (antes, titulo, texto) => {
    const t = document.getElementById("kv-tarjeta"); if (!t) return;
    if (!titulo) { t.style.opacity = 0; return; }
    t.innerHTML = ""; const a = document.createElement("small"); a.textContent = antes; const h = document.createElement("h1"); h.textContent = titulo;
    const p = document.createElement("p"); p.textContent = texto; t.append(a, h, p); t.style.opacity = 1;
  };
  if (document.body) montar(); else addEventListener("DOMContentLoaded", montar);
})();
"""


class Guion:
    """Lleva el tiempo del video y anota un capítulo por cada subtítulo nuevo."""

    def __init__(self, pag, rol: str, voces: dict[str, tuple[Path, float]] | None = None):
        self.pag, self.rol, self.t0, self.capitulos, self.n = pag, rol, time.monotonic(), [], 0
        self.voces, self.pistas = voces or {}, []

    def _hablar(self, frase: str) -> float:
        """Anota la frase en su segundo del video y devuelve cuánto dura (0 si no hay voz)."""
        clip = self.voces.get(para_voz(frase))
        if not clip:
            return 0.0
        self.pistas.append((self.ahora(), clip[0]))
        return clip[1]

    def ahora(self) -> float:
        return round(time.monotonic() - self.t0, 1)

    def decir(self, titulo: str, texto: str, minimo: float = 3.2) -> None:
        self.n += 1
        self.capitulos.append({"t": max(0.0, self.ahora() - 0.3), "titulo": titulo, "texto": texto})
        self.pag.evaluate("([t, e]) => window.__kautaSub && window.__kautaSub(t, e)", [texto, f"{self.n} · {titulo}"])
        voz = self._hablar(texto)
        self.pag.wait_for_timeout(int((voz + 0.25 if voz else max(minimo, len(texto) / 17)) * 1000))

    def tarjeta(self, antes: str, titulo: str, texto: str, ms: int = 3800) -> None:
        self.pag.evaluate("([a, b, c]) => window.__kautaTarjeta && window.__kautaTarjeta(a, b, c)", [antes, titulo, texto])
        voz = self._hablar(frase_tarjeta(antes, titulo, texto))
        self.pag.wait_for_timeout(int((voz + 0.35 if voz else ms / 1000) * 1000))
        self.pag.evaluate("() => window.__kautaTarjeta && window.__kautaTarjeta('', '', '')")
        self.pag.wait_for_timeout(350)

    def ir(self, ruta: str, espera: int = 900) -> None:
        self.pag.goto(f"{BASE}/#/{ruta}")
        self.pag.wait_for_load_state("networkidle")
        self.pag.wait_for_timeout(espera)

    def bajar(self, pixeles: int = 900, pasos: int = 6) -> None:
        for _ in range(pasos):
            self.pag.mouse.wheel(0, pixeles / pasos)
            self.pag.wait_for_timeout(190)

    def subir(self) -> None:
        self.pag.evaluate("() => window.scrollTo({top: 0, behavior: 'smooth'})")
        self.pag.wait_for_timeout(700)

    def clic(self, loc, espera: int = 700) -> None:
        loc.scroll_into_view_if_needed()
        loc.hover()
        self.pag.wait_for_timeout(300)
        loc.click()
        self.pag.wait_for_timeout(espera)

    def escribir(self, loc, texto: str) -> None:
        loc.scroll_into_view_if_needed()
        loc.hover()
        loc.click()
        loc.press_sequentially(texto, delay=18)
        self.pag.wait_for_timeout(300)


def token(correo: str, antes: set[Path]) -> str:
    for _ in range(40):
        nuevos = sorted(p for p in BUZON.glob("*.eml") if p not in antes and correo.split("@")[0].replace(".", "-") in p.name)
        if nuevos:
            texto = email.message_from_bytes(nuevos[-1].read_bytes(), policy=email.policy.default).get_content()
            return re.search(r"^\s+(\d{6})$", texto, re.M).group(1)
        time.sleep(0.25)
    raise RuntimeError(f"No llegó el token de {correo}")


def con_token(g: Guion, correo: str, campo: str) -> None:
    antes = set(BUZON.glob("*.eml")) if BUZON.exists() else set()
    g.clic(g.pag.get_by_role("button", name="Enviar token a mi correo"), 1200)
    g.escribir(g.pag.get_by_label(campo), token(correo, antes))


def entrar(g: Guion, correo: str) -> None:
    g.pag.goto(BASE + "/")
    g.pag.wait_for_load_state("networkidle")
    g.pag.wait_for_timeout(600)
    g.escribir(g.pag.get_by_label("Correo"), correo)
    g.escribir(g.pag.get_by_label("Contraseña", exact=True), CLAVE)
    g.clic(g.pag.get_by_role("button", name="Iniciar sesión"), 1500)
    g.pag.wait_for_selector("main")
    g.pag.wait_for_load_state("networkidle")


# ---------------------------------------------------------------------------------------------------------- guiones
def finanzas(g: Guion) -> None:
    p = g.pag
    g.tarjeta("Introducción · Finanzas", "¡Usted opera y paga!", "Responde lo que Kauta le pregunta, aprueba hasta USD 3.000 y paga con PayPal. ¡Vamos a verlo!")
    entrar(g, "mariana.torres@brisamar.example")
    g.decir("Resumen", "¡Este es su resumen, su trabajo del día! Lo que Kauta le pregunta, lo que ya puede pagar y cómo terminó cada pago.")
    g.bajar(700)
    g.decir("Resumen", "Y más abajo: los últimos pagos, el presupuesto del mes y por dónde llegan las facturas.", 3.6)
    g.subir()
    g.ir("facturas")
    g.decir("Facturas", "En Facturas tiene todo lo que llegó: correo, chat, PDF, foto o XML. ¡Con el canal, cómo se leyó y lo que decidió Kauta!")
    g.clic(p.get_by_role("tab", name=re.compile(r"^Chat")).first, 900)
    g.decir("Facturas", "¿Quiere ver solo los chats? Filtre por canal. Y mire la tira de colores: verde cumple, ámbar pregunta y rojo frena.", 3.6)
    g.clic(p.get_by_role("tab", name=re.compile(r"^Todos")).first, 600)
    g.clic(p.get_by_role("button", name=re.compile("Buzón de prueba")), 1500)
    g.decir("Buzón", "¡Llegó una factura al buzón! Kauta la lee sin IA, revisa las 13 reglas y decide en segundos.")
    fila = p.locator("li", has_text="P06").first
    g.clic(fila.get_by_role("button", name="Recibir"), 2200)
    g.decir("Buzón", "¡Esta cumplió todo y Kauta la pagó sola! Y a usted le llega el aviso con el documento adjunto.", 3.6)
    p.keyboard.press("Escape")
    p.wait_for_timeout(600)
    g.ir("lector")
    g.decir("Lectura (OCR)", "¿Tiene la foto de una factura? Pruébela aquí y vea paso a paso cómo la lee Kauta, sin crear nada.")
    g.clic(p.get_by_role("button", name="Foto (en portugués)"), 400)
    expect(p.get_by_text("Datos leídos").first).to_be_visible(timeout=30000)
    p.wait_for_timeout(600)
    g.bajar(560, 4)
    g.decir("Lectura (OCR)", "¡El OCR la leyó en el servidor! Cada dato con su confianza. Y si algo queda dudoso, Kauta pregunta en vez de adivinar.", 4.2)
    g.ir("pregunta")
    g.decir("Kauta pregunta", "Ahora, Kauta pregunta: aquí está lo que necesita de usted, con una pregunta clara por cada regla que falló.")
    g.clic(p.locator("a", has_text="Andrés Felipe Rojas").first, 1500)
    g.decir("Aprobar", "¡Ojo con esta! La factura F12 pide pagar a una cuenta nueva por chat (R07). Usted llama al proveedor y aprueba con su token.", 4)
    g.escribir(p.get_by_placeholder("Ej.: Llamé al número registrado"), "Llamé al número registrado: no cambió de banco.")
    con_token(g, "mariana.torres@brisamar.example", "Token de autorización")
    g.clic(p.get_by_role("button", name="Aprobar", exact=True), 1800)
    expect(p.get_by_text("Lista para pagar").first).to_be_visible(timeout=15000)
    g.decir("Aprobar", "¡Aprobada! Y queda lista para pagar, siempre a la cuenta registrada, nunca a la del chat.", 3.6)
    g.ir("pagos")
    g.decir("Pagos", "Vamos a Pagos: aquí está lo que falta por pagar. ¡Pulse Pagar!")
    g.clic(p.locator("li", has_text="F12").first.get_by_role("button", name="Pagar"), 1200)
    g.decir("Pagar con PayPal", "Elija cómo pagar: con la ventana de PayPal, donde usted aprueba o rechaza, o con el pago directo. Y pida su token.", 4)
    con_token(g, "mariana.torres@brisamar.example", "Token de pago")
    g.clic(p.get_by_role("button", name=re.compile("Ir a PayPal a pagar")), 1600)
    expect(p.get_by_role("button", name="Aprobar el pago")).to_be_visible(timeout=10000)
    g.decir("Pagar con PayPal", "¡Se abre PayPal! Con el sandbox conectado, entra con la cuenta de pruebas. Aquí ve la ventana simulada: ¡apruebe el pago!", 4)
    g.clic(p.get_by_role("button", name="Aprobar el pago"), 1800)
    expect(p.get_by_text("Pago exitoso").first).to_be_visible(timeout=15000)
    g.decir("Resultado", "¡Pago exitoso! Con su línea de tiempo y el comprobante. Y si PayPal lo rechaza, el dinero vuelve solito a la wallet.", 4.4)
    g.clic(p.get_by_role("button", name="Listo"), 900)
    g.clic(p.get_by_role("tab", name=re.compile("Exitoso")).first, 900)
    g.decir("Pagos", "Cada pago queda ordenado por resultado: exitoso, en proceso, fallido o negado. ¡Y los fallidos se reintentan aquí mismo!")
    g.ir("wallet")
    g.decir("Wallet", "Y en la wallet: el dinero por etapas, el libro mayor y la conciliación lista para Excel.", 3.8)
    p.evaluate("() => window.__kautaSub('')")
    g.tarjeta("Finanzas", "¡Listo!", "Responde, aprueba hasta USD 3.000 y paga con su token. ¡Lo que cumple las 13 reglas, Kauta lo paga sola!", 3600)


def ceo(g: Guion, fid: str) -> None:
    p = g.pag
    g.tarjeta("Introducción · CEO", "¡Usted decide!", "Aprueba lo que supera USD 3.000, define las reglas y aprueba las rutas de pago. ¡Y Finanzas paga!")
    entrar(g, "carlos.rivera@brisamar.example")
    g.decir("Resumen", "Su resumen arranca por lo importante: lo que espera su decisión, el presupuesto y cuánto resuelve Kauta sola.")
    g.bajar(900)
    g.decir("Impacto", "¡Y aquí el impacto en la empresa! Lo que vence, la exposición por moneda, los proveedores más grandes y dónde fallan las reglas.", 4)
    g.subir()
    g.ir("pregunta")
    g.decir("Aprobar lo alto", "En Kauta pregunta están las facturas que superan el umbral. ¡Esas son suyas!")
    g.ir(f"facturas/{fid}", 1500)
    g.decir("Aprobar lo alto", "Esta de Legal Puente supera USD 3.000. Revise las reglas, escriba por qué aprueba y confirme con su token.", 4)
    g.escribir(p.get_by_placeholder("Ej.: Llamé al número registrado"), "Proyecto especial aprobado por el comité de gerencia.")
    con_token(g, "carlos.rivera@brisamar.example", "Token de autorización")
    g.clic(p.get_by_role("button", name="Aprobar", exact=True), 1800)
    expect(p.get_by_text("Lista para pagar").first).to_be_visible(timeout=15000)
    g.decir("Aprobar lo alto", "¡Aprobada! Queda lista para pagar y la paga Finanzas. Así ningún pago grande depende de una sola persona.", 4.4)
    g.ir("pagos")
    g.decir("Pagos", "En Pagos ve qué falta por pagar y cómo terminó cada pago. ¡Todo a la vista!")
    g.ir("rutas", 1800)
    g.decir("Rutas de pago", "¡Rutas de pago! Kauta prueba pronto pago, prórroga, moneda local o pago parcial, y le propone la ruta más barata sin descuadrar la caja.", 4.2)
    g.clic(p.get_by_role("tab", name=re.compile("H2")), 900)
    g.escribir(p.get_by_placeholder("Ej.: Negociar"), "Confirmar el pago en MXN con la cotización del día.")
    g.clic(p.get_by_role("button", name="Aprobar ruta"), 1600)
    g.decir("Rutas de pago", "¡Y usted la aprueba! Negociaciones y cambios de moneda, con su firma en la auditoría.")
    g.ir("reglas")
    g.decir("Reglas", "En Reglas manda usted: el umbral, los límites y el presupuesto. Y antes de guardar, Kauta le muestra qué cambiaría.", 4)
    g.bajar(600, 4)
    g.ir("rendimiento", 1600)
    g.decir("Rendimiento", "Rendimiento y costos: cuánto cuesta resolver cada factura, cuánto se lee sin IA y cómo va frente al mes anterior.", 4)
    g.bajar(700, 5)
    g.ir("auditoria")
    g.decir("Auditoría", "Y la auditoría: cada decisión, firma y pago encadenados con HMAC. ¡Si alguien toca un registro, se nota!", 4)
    p.evaluate("() => window.__kautaSub('')")
    g.tarjeta("CEO", "¡Listo!", "Usted aprueba lo grande, las reglas y las rutas. Kauta paga lo que cumple y Finanzas paga lo que usted aprueba.", 3600)


def admin(g: Guion) -> None:
    p = g.pag
    g.tarjeta("Introducción · Administrador", "¡Usted gestiona la plataforma!", "Da accesos, cambia roles y cuida la seguridad y las integraciones. ¡Sin mover un peso!")
    entrar(g, "equipo@kauta.example")
    g.decir("Resumen", "Su resumen es la plataforma: personas activas, sesiones, registros nuevos y una auditoría íntegra.")
    g.bajar(600, 4)
    g.decir("Integraciones", "¡Y las integraciones! PayPal, el correo, el OCR y la IA, con lo que falta para conectar cada una.", 3.6)
    g.subir()
    g.ir("personas", 1500)
    g.decir("Personas y roles", "En Personas y roles: quien se registra entra como Finanzas, ¡y usted le cambia el rol con un clic!", 4)
    g.bajar(700, 5)
    g.decir("Personas y roles", "Esta tabla lo deja clarísimo: Finanzas opera y paga, el CEO aprueba lo grande y usted da los accesos.", 4)
    g.subir()
    g.clic(p.get_by_role("button", name="Invitar persona"), 1200)
    g.decir("Invitar", "¿Quiere invitar a alguien? Ponga el correo y el rol, y Kauta genera un código de un solo uso.")
    p.keyboard.press("Escape")
    p.wait_for_timeout(600)
    g.ir("seguridad")
    g.decir("Seguridad", "En Seguridad: su contraseña, el segundo factor, las sesiones abiertas ¡y la prueba del correo!")
    g.bajar(500, 4)
    g.ir("wallet", 1500)
    g.bajar(1400, 7)
    g.decir("PayPal", "Aquí revisa la conexión con PayPal: la lista dice qué falta y «Probar conexión» lo verifica sin mover dinero.", 4)
    g.ir("pagos")
    g.decir("Supervisión", "Pagos, facturas, wallet y reglas los ve en modo consulta. ¡Supervisa todo, pero no mueve dinero!", 4)
    g.ir("auditoria")
    g.decir("Auditoría", "Y la auditoría lo registra todo: se verifica con HMAC y se exporta en un clic.")
    p.evaluate("() => window.__kautaSub('')")
    g.tarjeta("Administrador", "¡Listo!", "Personas, roles, seguridad e integraciones en sus manos, y el resto bajo su supervisión.", 3600)


def preparar_ceo(pag) -> str:
    """Para el video del CEO: una factura de monto alto que llegó (como por correo) y espera su aprobación."""
    pag.goto(BASE + "/")
    pag.wait_for_load_state("networkidle")
    return pag.evaluate("""async () => {
        await fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({correo: 'equipo@kauta.example', contrasena: 'Kauta-30X-demo-2026'})});
        const yo = await (await fetch('/api/auth/yo')).json();
        const h = {'Content-Type': 'application/json', 'X-CSRF-Token': yo.usuario.csrf};
        const d = await (await fetch('/api/simulador/escenarios/supera_umbral?periodo=2026-11')).json();
        const f = await (await fetch('/api/simulador/factura', {method: 'POST', headers: h, body: JSON.stringify({...d, riel: 'PAYPAL'})})).json();
        await fetch('/api/auth/logout', {method: 'POST', headers: h});
        return f.id;
    }""")


def main() -> None:
    SALIDA.mkdir(parents=True, exist_ok=True)
    tmp = RAIZ / "var" / "_videos"
    shutil.rmtree(tmp, ignore_errors=True)
    frases = frases_del_guion()
    voces = preparar_voz(frases)
    print(f"  voz: {len(voces)} frases con {VOZ}, {sum(d for _, d in voces.values()) / 60:.1f} min de locución")
    capitulos = {}
    with sync_playwright() as pw:
        try:
            nav = pw.chromium.launch(slow_mo=40)
        except Exception:
            nav = pw.chromium.launch(channel="chrome", slow_mo=40)
        aux = nav.new_context()
        fid = preparar_ceo(aux.new_page())
        aux.close()
        for rol, guion in [("finanzas", finanzas), ("ceo", lambda g: ceo(g, fid)), ("admin", admin)]:
            # bypass_csp: la CSP de Kauta (style-src 'self') bloquearía los estilos de los subtítulos; solo afecta a esta grabación
            ctx = nav.new_context(viewport={"width": ANCHO, "height": ALTO}, device_scale_factor=1, locale="es-CO", bypass_csp=True,
                                  timezone_id="America/Bogota", record_video_dir=str(tmp / rol),
                                  record_video_size={"width": ANCHO, "height": ALTO})
            ctx.add_init_script("try { localStorage.setItem('kauta.intro.desactivada', '1') } catch (e) {}")   # sin la intro automática
            ctx.add_init_script(CAPA)
            pag = ctx.new_page()
            pag.goto(BASE + "/")
            g = Guion(pag, rol, voces)
            guion(g)
            total = g.ahora() + 0.5
            video = pag.video.path()
            ctx.close()
            destino = SALIDA / f"introduccion-{rol}.webm"
            montar(Path(video), g.pistas, destino, total)
            capitulos[rol] = {"video": f"/videos/{destino.name}", "duracion": round(total, 1), "voz": VOZ, "capitulos": g.capitulos}
            print(f"  {rol}: {total:.0f} s · {destino.stat().st_size / 1e6:.1f} MB · {len(g.capitulos)} capítulos · {len(g.pistas)} frases")
        nav.close()
    shutil.rmtree(tmp, ignore_errors=True)
    (SALIDA / "capitulos.json").write_text(json.dumps(capitulos, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Videos en", SALIDA)


if __name__ == "__main__":
    sys.exit(main())
