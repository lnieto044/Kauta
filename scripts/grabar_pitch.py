"""
Kauta · pitch de 3 minutos en video: escenas animadas (el problema, la solución, los roles, la tecnología, los resultados,
el equipo y el contacto) y en medio una demo corta sobre la aplicación real, narrado por una voz neuronal en español.

El guion (textos, voz, ritmo, equipo y contacto) está en pitch/guion_pitch.json y las escenas en pitch/escenas.html.
Cada parte tiene su «texto» (el subtítulo) y, si hace falta, su «dicho» (lo que dice la voz: siglas y cifras en palabras).
La voz se genera con edge-tts y trae la marca de tiempo de cada palabra: con ella los subtítulos salen justo cuando se
dicen. La demo corre MIENTRAS la voz habla; al final ffmpeg (imageio-ffmpeg) pone cada frase en su segundo exacto.

Salida, FUERA del proyecto y de la aplicación (es para presentar): ../pitch-kauta/pitch-kauta-3min.mp4 (1080p, H.264 +
AAC: se reproduce en cualquier computador, proyector o TV) y ../pitch-kauta/pitch-kauta-3min.srt (los subtítulos aparte,
por si se sube a YouTube o Drive). Otra carpeta: KAUTA_PITCH_SALIDA=<carpeta>.
Necesita un servidor de Kauta en modo demo, recién iniciado y SIN credenciales de PayPal (la ventana de PayPal se
simula), Playwright con ffmpeg, edge-tts e imageio-ffmpeg, e internet para generar la voz. Uso:
  KAUTA_URL=http://localhost:8010 KAUTA_VAR=<carpeta var de ese servidor> python scripts/grabar_pitch.py
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import grabar_videos as gv  # noqa: E402 - reutiliza la capa de subtítulos y cursor, el buzón y los tokens
from playwright.sync_api import expect, sync_playwright  # noqa: E402

RAIZ = gv.RAIZ
BASE = gv.BASE
GUION = RAIZ / "pitch" / "guion_pitch.json"
ESCENAS = (RAIZ / "pitch" / "escenas.html").as_uri()
CACHE = RAIZ / "var" / "_voz_pitch"
SALIDA = Path(os.environ.get("KAUTA_PITCH_SALIDA", RAIZ.parent / "pitch-kauta"))
MP4 = SALIDA / "pitch-kauta-3min.mp4"
SRT = MP4.with_suffix(".srt")
LIMITE = 180.0
ANCHO, ALTO = 1280, 720                       # se graba a 720p y el MP4 se entrega en 1080p
CORTE = re.compile(r"(?<=[.?!:;])\s+")
MAX_LINEA = 96

# Subtítulos programados con la voz: sobreviven a una recarga de la página; en las escenas no hay cursor
CAPA_PITCH = """
(() => {
  if (window.__pitchCapa) return; window.__pitchCapa = true;
  let relojes = [];
  const aplicar = (plan) => {
    relojes.forEach(clearTimeout); relojes = [];
    const ya = Date.now() - plan.inicio;
    plan.lineas.forEach((l, i) => {
      const fin = i + 1 < plan.lineas.length ? plan.lineas[i + 1].t * 1000 : Infinity;
      if (fin <= ya) return;
      relojes.push(setTimeout(() => window.__kautaSub && window.__kautaSub(l.texto, plan.etiqueta), Math.max(0, l.t * 1000 - ya)));
    });
  };
  window.__pitchSubs = (lineas, etiqueta, ya = 0) => {
    const plan = {inicio: Date.now() - ya * 1000, lineas, etiqueta};
    try { sessionStorage.setItem("kv-plan", JSON.stringify(plan)); } catch (e) {}
    aplicar(plan);
  };
  window.__pitchLimpiar = () => {
    relojes.forEach(clearTimeout); relojes = [];
    try { sessionStorage.removeItem("kv-plan"); } catch (e) {}
    window.__kautaSub && window.__kautaSub("");
  };
  const alCargar = () => {
    const st = document.createElement("style");
    st.textContent = "#kv-sub{font-size:21px;max-width:1060px}" + (location.protocol === "file:" ? "#kv-cursor{display:none}" : "");
    document.head.appendChild(st);
    try { const p = sessionStorage.getItem("kv-plan"); if (p) aplicar(JSON.parse(p)); } catch (e) {}
  };
  if (document.body) alCargar(); else addEventListener("DOMContentLoaded", alCargar);
})();
"""


# ---------------------------------------------------------------------------------------------------------------- voz
def dicho(parte: dict) -> str:
    return parte.get("dicho", parte["texto"])


def _clip(cfg: dict, texto: str) -> Path:
    return CACHE / (hashlib.sha1(f"palabras|{cfg['voz']}|{cfg['ritmo']}|{cfg['tono']}|{texto}".encode()).hexdigest()[:16] + ".mp3")


def preparar_voz(cfg: dict) -> dict[str, tuple[Path, float, list[dict]]]:
    """Genera (o toma de la caché) la voz de cada parte con la marca de tiempo de cada palabra.
    Devuelve id → (archivo, segundos, líneas de subtítulo con su segundo dentro de la frase)."""
    import edge_tts
    CACHE.mkdir(parents=True, exist_ok=True)

    async def una(texto: str, sem: asyncio.Semaphore):
        destino = _clip(cfg, texto)
        async with sem:
            for intento in range(3):
                try:
                    palabras = []
                    com = edge_tts.Communicate(texto, cfg["voz"], rate=cfg["ritmo"], pitch=cfg["tono"], boundary="WordBoundary")
                    with open(destino, "wb") as f:
                        async for trozo in com.stream():
                            if trozo["type"] == "audio":
                                f.write(trozo["data"])
                            elif trozo["type"] == "WordBoundary":
                                palabras.append({"t": trozo["offset"] / 1e7, "p": trozo["text"]})
                    destino.with_suffix(".json").write_text(json.dumps(palabras, ensure_ascii=False), encoding="utf-8")
                    return
                except Exception:  # noqa: BLE001 - un corte de red se reintenta
                    await asyncio.sleep(1.5 * (intento + 1))
            raise RuntimeError(f"No se pudo generar la voz de: {texto[:60]}")

    async def todas(faltan: list[str]):
        sem = asyncio.Semaphore(4)
        await asyncio.gather(*(una(t, sem) for t in faltan))

    faltan = [dicho(p) for p in cfg["partes"] if not _clip(cfg, dicho(p)).with_suffix(".json").exists()]
    if faltan:
        asyncio.run(todas(faltan))
    voces = {}
    for p in cfg["partes"]:
        clip = _clip(cfg, dicho(p))
        dur = gv.duracion(clip)
        palabras = json.loads(clip.with_suffix(".json").read_text(encoding="utf-8"))
        voces[p["id"]] = (clip, dur, lineas(p["texto"], dicho(p), palabras, dur))
    return voces


def _norm(p: str) -> str:
    return re.sub(r"\W", "", p).lower()


def lineas(texto: str, voz: str, palabras: list[dict], dur: float) -> list[dict]:
    """Corta el subtítulo por frases y le da a cada trozo el segundo en que la voz dice su primera palabra."""
    trozos, dichos = CORTE.split(texto.strip()), CORTE.split(voz.strip())
    inicios, j = [], 0
    if len(trozos) == len(dichos):
        for d in dichos:
            primera = _norm((re.findall(r"\w+", d) or [""])[0])
            k = next((k for k in range(j, len(palabras)) if _norm(palabras[k]["p"]) == primera), None)
            inicios.append(palabras[k]["t"] if k is not None else None)
            j = k + 1 if k is not None else j
    if len(inicios) != len(trozos) or None in inicios:      # sin marcas confiables: proporcional al largo
        total, acum = sum(len(t) for t in trozos), 0
        inicios = []
        for t in trozos:
            inicios.append(dur * acum / total)
            acum += len(t)
    salida: list[dict] = []
    for t, ini in zip(trozos, inicios):
        if salida and len(salida[-1]["texto"]) + 1 + len(t) <= MAX_LINEA:
            salida[-1]["texto"] += " " + t
        else:
            salida.append({"t": round(max(0.0, ini - 0.08), 2), "texto": t})
    return salida


# ------------------------------------------------------------------------------------------------------------- pitch
class Pitch:
    """Lleva el reloj: la voz arranca, la demo corre mientras habla y la parte siguiente espera a que termine."""

    def __init__(self, pag, cfg: dict, voces: dict):
        self.pag, self.voces = pag, voces
        self.partes = {p["id"]: p for p in cfg["partes"]}
        self.t0, self.pistas, self.inicio, self.fin, self.capitulos, self.huecos = time.monotonic(), [], 0.0, 0.0, [], []
        self.actual: tuple[list, str] | None = None

    def ahora(self) -> float:
        return time.monotonic() - self.t0

    def esperar(self, pausa: float = 0.0) -> None:
        falta = self.fin + pausa - self.ahora()
        if falta > 0:
            self.pag.wait_for_timeout(int(falta * 1000))

    def hasta(self, segundo: float) -> None:
        """Espera a que la voz de esta parte llegue a ese segundo."""
        falta = self.inicio + segundo - self.ahora()
        if falta > 0:
            self.pag.wait_for_timeout(int(falta * 1000))

    def narrar(self, pid: str) -> None:
        clip, dur, subs = self.voces[pid]
        t = self.ahora()
        if self.fin and t - self.fin > 1.2:
            self.huecos.append((pid, round(t - self.fin, 1)))
        self.inicio, self.fin = t, t + dur
        self.pistas.append((t, clip))
        p = self.partes[pid]
        self.capitulos.append({"t": round(t, 2), "fin": round(t + dur, 2), "titulo": p["etiqueta"], "lineas": subs})
        self.actual = (subs, p["etiqueta"])
        self.pag.evaluate("([l, e]) => window.__pitchSubs(l, e)", [subs, p["etiqueta"]])

    def _retomar(self) -> None:
        """Tras cambiar de documento a mitad de una frase, los subtítulos siguen donde iba la voz."""
        if self.actual and self.ahora() < self.fin:
            self.pag.evaluate("([l, e, ya]) => window.__pitchSubs(l, e, ya)", [*self.actual, self.ahora() - self.inicio])

    def reposo(self) -> None:
        """Aparta el cursor de los subtítulos."""
        self.pag.mouse.move(1262, 400, steps=6)

    # ----- navegación
    def _limpiar(self) -> None:
        try:
            self.pag.evaluate("() => window.__pitchLimpiar && window.__pitchLimpiar()")
        except Exception:  # noqa: BLE001 - la página puede estar cambiando
            pass

    def escena(self, nombre: str) -> None:
        if not self.pag.url.startswith("file:"):
            self._limpiar()
            self.pag.goto(f"{ESCENAS}#{nombre}")
            self._retomar()
            self.pag.wait_for_timeout(250)
        else:
            self.pag.evaluate("(h) => { location.hash = h }", nombre)
            self.pag.wait_for_timeout(120)

    def app(self, ruta: str, espera: int = 500, recargar: bool = False) -> None:
        self._limpiar()
        self.pag.goto(f"{BASE}/#/{ruta}")
        if recargar:
            self.pag.reload()
        self.pag.wait_for_load_state("networkidle")
        self._retomar()
        self.pag.wait_for_timeout(espera)

    def deslizar(self, objetivo, ms: int = 0) -> None:
        """Lleva un elemento a la vista con un desplazamiento suave (como lo haría una persona)."""
        objetivo.first.evaluate("(el) => el.scrollIntoView({behavior: 'smooth', block: 'start'})")
        self.pag.wait_for_timeout(ms or 900)

    def clic(self, loc, espera: int = 400) -> None:
        loc.scroll_into_view_if_needed()
        loc.hover()
        self.pag.wait_for_timeout(250)
        loc.click()
        self.pag.wait_for_timeout(espera)

    def escribir(self, loc, texto: str, retraso: int = 22) -> None:
        loc.scroll_into_view_if_needed()
        loc.hover()
        loc.click()
        loc.press_sequentially(texto, delay=retraso)
        self.pag.wait_for_timeout(200)

    def token(self, correo: str, campo: str) -> None:
        antes = set(gv.BUZON.glob("*.eml")) if gv.BUZON.exists() else set()
        self.clic(self.pag.get_by_role("button", name="Enviar token a mi correo"), 500)
        self.escribir(self.pag.get_by_label(campo), gv.token(correo, antes), 45)


def quizas(accion) -> None:
    """Un gesto de cámara (pasar el cursor por encima): si no se puede, el pitch sigue."""
    try:
        accion()
    except Exception:  # noqa: BLE001
        pass


def fila_buzon(pag, codigo: str):
    return pag.locator("li", has_text=f"{codigo} ·").first


def recibir(g: Pitch, codigo: str) -> None:
    """«Recibir» en el buzón de prueba: la factura llega como si la enviara el proveedor y Kauta decide."""
    fila = fila_buzon(g.pag, codigo)
    g.clic(fila.get_by_role("button", name="Recibir"), 200)
    expect(fila.get_by_role("link")).to_be_visible(timeout=20000)
    quizas(lambda: fila.get_by_role("link").hover(timeout=1500))


MARIANA = "mariana.torres@brisamar.example"
CARLOS = "carlos.rivera@brisamar.example"


def sesion(pag, correo: str) -> None:
    """Cambia la sesión del navegador sin pasar por la pantalla de entrada (no aporta al pitch)."""
    pag.evaluate("""async ([correo, clave]) => {
        const yo = await fetch('/api/auth/yo');
        if (yo.ok) {
            const u = (await yo.json()).usuario;
            if (u) await fetch('/api/auth/logout', {method: 'POST', headers: {'X-CSRF-Token': u.csrf}});
        }
        const r = await fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({correo, contrasena: clave})});
        if (!r.ok) throw new Error('No se pudo entrar como ' + correo);
    }""", [correo, gv.CLAVE])


def pitch(g: Pitch) -> None:
    p = g.pag
    # 1 · El problema, la solución y los roles
    g.narrar("gancho"); g.esperar(0.5)
    g.escena("kauta"); g.narrar("kauta"); g.esperar(0.5)
    g.escena("roles"); g.narrar("roles"); g.esperar(0.4)

    # 3 · Demo: el fraude del chat, aprobar, pagar con PayPal
    g.narrar("resumen")
    g.hasta(0.9)
    g.app("resumen", 300)
    g.hasta(2.6)
    p.mouse.move(640, 420)
    p.mouse.wheel(0, 260)
    g.esperar(0.2)

    # 2 · Demo: el agente solo. Tres facturas llegan al buzón y Kauta decide sin nadie
    g.narrar("agente")
    g.app("facturas", 300)
    g.clic(p.get_by_role("button", name=re.compile("Buzón de prueba")), 400)
    g.hasta(3.7)
    recibir(g, "P09")                                    # correo que cumple las 13 reglas: la paga sola
    g.reposo()
    g.esperar(0.2)

    g.narrar("bloqueado")
    recibir(g, "P05")                                    # XML de un proveedor bloqueado por disputa: la frena
    g.reposo()
    g.esperar(0.2)

    g.narrar("trampa")
    recibir(g, "P01")                                    # PDF con una orden escondida para el agente: pregunta (R13)
    g.hasta(5.6)
    g.clic(fila_buzon(p, "P01").get_by_role("link"), 500)
    g.reposo()
    g.esperar(0.3)

    g.app("facturas/F12", 600)
    g.narrar("fraude")
    quizas(lambda: p.get_by_text("Andrés").first.hover(timeout=1500))
    g.hasta(6.6)
    g.deslizar(p.get_by_text("Las 13 reglas"), 700)
    g.hasta(9.4)
    quizas(lambda: p.locator("li", has_text="falla").first.hover(timeout=1500))      # la regla que falla va primero
    g.esperar(0.2)

    g.narrar("aprobar")
    g.deslizar(p.get_by_text("Kauta te pregunta"), 500)
    g.escribir(p.get_by_placeholder("Ej.: Llamé al número registrado"), "Llamé al número registrado: no cambió de banco.", 14)
    g.token(MARIANA, "Token de autorización")
    g.clic(p.get_by_role("button", name="Aprobar", exact=True), 300)
    expect(p.get_by_text("Lista para pagar").first).to_be_visible(timeout=15000)
    g.reposo()
    g.esperar(0.3)

    g.app("pagos", 500)
    g.narrar("pagar")
    g.clic(p.locator("li", has_text="F12").first.get_by_role("button", name="Pagar"), 600)
    g.token(MARIANA, "Token de pago")
    g.clic(p.get_by_role("button", name=re.compile("Ir a PayPal a pagar")), 300)
    expect(p.get_by_role("button", name="Aprobar el pago")).to_be_visible(timeout=10000)
    g.reposo()
    g.esperar(0.2)

    g.narrar("pagado")
    g.hasta(0.8)
    g.clic(p.get_by_role("button", name="Aprobar el pago"), 200)
    expect(p.get_by_text("Pago exitoso").first).to_be_visible(timeout=15000)
    g.reposo()
    g.esperar(0.6)

    # 4 · Demo: la foto leída con OCR y la vista del gerente
    g.app("lector", 500)
    g.narrar("ocr")
    g.clic(p.get_by_role("button", name="Foto (en portugués)"), 200)
    expect(p.get_by_text("Datos leídos").first).to_be_visible(timeout=30000)
    p.wait_for_timeout(500)
    g.reposo()
    g.hasta(6.2)
    g.deslizar(p.get_by_text("Datos leídos"), 600)
    g.esperar(0.2)

    g.narrar("ceo")
    sesion(p, CARLOS)
    g.app("resumen", 300, recargar=True)
    g.hasta(2.2)
    g.deslizar(p.get_by_text("Impacto en la empresa"), 600)
    g.esperar(0.4)

    # 5 · Tecnología, resultados, equipo y contacto
    g.escena("tecnologias"); g.narrar("tecnologias"); g.esperar(0.5)
    g.escena("resultados"); g.narrar("resultados"); g.esperar(0.6)
    g.escena("cierre"); g.narrar("cierre"); g.esperar(2.5)     # el cierre se sostiene hasta completar la duración


# ------------------------------------------------------------------------------------------------------------ montaje
def ffmpeg(*args: str) -> None:
    import imageio_ffmpeg
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def montar(video: Path, desde: float, pistas: list[tuple[float, Path]], total: float, tmp: Path) -> None:
    """Mezcla la voz en su segundo exacto (con volumen de presentación) y comprime en MP4."""
    voz = tmp / "voz.wav"
    entradas, filtros = [], []
    for i, (t, clip) in enumerate(pistas):
        entradas += ["-i", str(clip)]
        ms = int(max(0.0, t) * 1000)
        filtros.append(f"[{i}:a]adelay={ms}|{ms}[a{i}]")
    mezcla = "".join(f"[a{i}]" for i in range(len(pistas)))
    filtros.append(f"{mezcla}amix=inputs={len(pistas)}:normalize=0:dropout_transition=0,apad,atrim=0:{total:.2f},"
                   "loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000[voz]")
    ffmpeg(*entradas, "-filter_complex", ";".join(filtros), "-map", "[voz]", "-ac", "2", str(voz))
    comun = ["-ss", f"{desde:.2f}", "-i", str(video), "-i", str(voz), "-map", "0:v", "-map", "1:a", "-t", f"{total:.2f}"]
    MP4.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg(*comun, "-vf", "scale=1920:1080:flags=lanczos", "-c:v", "libx264", "-preset", "slow", "-crf", "20",
           "-tune", "stillimage", "-pix_fmt", "yuv420p", "-r", "25",
           "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(MP4))


def srt(capitulos: list[dict]) -> str:
    def marca(s: float) -> str:
        ms = int(round(s * 1000))
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
    salida, n = [], 0
    for c in capitulos:
        for i, linea in enumerate(c["lineas"]):
            ini = c["t"] + linea["t"]
            fin = c["t"] + c["lineas"][i + 1]["t"] if i + 1 < len(c["lineas"]) else c["fin"] + 0.3
            n += 1
            salida.append(f"{n}\n{marca(ini)} --> {marca(fin)}\n{linea['texto']}\n")
    return "\n".join(salida)


def main() -> int:
    cfg = json.loads(GUION.read_text(encoding="utf-8"))
    voces = preparar_voz(cfg)
    voz_total = sum(d for _, d, _ in voces.values())
    print(f"  voz: {len(voces)} partes con {cfg['voz']}, {voz_total:.1f} s de locución")
    tmp = RAIZ / "var" / "_pitch"
    shutil.rmtree(tmp, ignore_errors=True)
    with sync_playwright() as pw:
        try:
            nav = pw.chromium.launch()
        except Exception:  # noqa: BLE001
            nav = pw.chromium.launch(channel="chrome")
        # bypass_csp: la CSP de Kauta (style-src 'self') bloquearía los estilos de los subtítulos; solo afecta a esta grabación
        ctx = nav.new_context(viewport={"width": ANCHO, "height": ALTO}, device_scale_factor=1, locale="es-CO",
                              bypass_csp=True, timezone_id="America/Bogota", record_video_dir=str(tmp),
                              record_video_size={"width": ANCHO, "height": ALTO})
        ctx.add_init_script("try { localStorage.setItem('kauta.intro.desactivada', '1') } catch (e) {}")
        ctx.add_init_script(gv.CAPA)
        ctx.add_init_script(CAPA_PITCH)
        aux = ctx.new_page()                       # entra como Mariana fuera de cámara (la cookie es del contexto)
        aux.goto(BASE + "/")
        aux.wait_for_load_state("networkidle")
        sesion(aux, MARIANA)
        aux.close()
        pag = ctx.new_page()
        creada = time.monotonic()
        pag.goto(f"{ESCENAS}#gancho")
        pag.wait_for_timeout(400)
        g = Pitch(pag, cfg, voces)
        desde = g.t0 - creada
        pitch(g)
        total = g.ahora()
        duracion = float(cfg.get("duracion") or 0)
        if duracion and total <= duracion:                # el cierre (equipo y contacto) queda en pantalla hasta el segundo exacto
            pag.wait_for_timeout(int((duracion - total) * 1000) + 300)
            total = duracion
        video = Path(pag.video.path())
        ctx.close()
        nav.close()
    montar(video, desde, g.pistas, total, tmp)
    SRT.write_text(srt(g.capitulos), encoding="utf-8")
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"  pitch: {total:.1f} s ({int(total // 60)}:{int(total % 60):02d}) · {MP4} ({MP4.stat().st_size / 1e6:.1f} MB)")
    for pid, hueco in g.huecos:
        print(f"  aviso: antes de «{pid}» hubo {hueco} s sin voz (la demo tardó más que la frase)")
    if total > LIMITE:
        print(f"  ERROR: dura {total:.1f} s y pasa de {LIMITE:.0f} s: acorte el guion o suba el ritmo de la voz")
    print("  capítulos:", " · ".join(f"{c['titulo']} {c['t']:.0f}s" for c in g.capitulos))
    return 0


if __name__ == "__main__":
    sys.exit(main())
