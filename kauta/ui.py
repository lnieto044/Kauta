"""Kauta · Estilos y componentes visuales de la pantalla (Streamlit)."""
from __future__ import annotations

import html

from .motor import fmt_dinero

NOCHE, MENTA, AMBAR, CORAL, AZUL = "#0B1736", "#16C79A", "#FFB547", "#FF5C5C", "#3B5BFD"
PIZARRA, BRUMA, NIEBLA = "#5B6782", "#E3E8F2", "#F5F7FB"

ESTADOS = {
    "pagada": ("Pagada", "#E3F8F1", "#0B7A5C", MENTA),
    "frenada": ("Frenada", "#FFE9E9", "#C7302F", CORAL),
    "pendiente": ("Pendiente de aprobación", "#FFF4E0", "#9A5800", AMBAR),
    "rechazada": ("Rechazada", "#EEF1F6", "#4A5570", "#9AA4BA"),
}
CANALES = {"pdf": "PDF", "imagen": "Imagen", "correo": "Correo", "chat": "Chat"}

CSS = f"""
<style>
@font-face {{ font-family: 'Inter'; font-weight: 400; src: url('app/static/fonts/Inter-Regular.otf'); }}
@font-face {{ font-family: 'Inter'; font-weight: 500; src: url('app/static/fonts/Inter-Medium.otf'); }}
@font-face {{ font-family: 'Inter'; font-weight: 600; src: url('app/static/fonts/Inter-SemiBold.otf'); }}
@font-face {{ font-family: 'Inter'; font-weight: 700; src: url('app/static/fonts/Inter-Bold.otf'); }}
@font-face {{ font-family: 'Inter'; font-weight: 800; src: url('app/static/fonts/Inter-ExtraBold.otf'); }}
@font-face {{ font-family: 'Inter Display'; font-weight: 800; src: url('app/static/fonts/InterDisplay-ExtraBold.otf'); }}
html, body, .stApp {{ font-family: 'Inter', system-ui, sans-serif; }}
.stMarkdown p, .stMarkdown div, .stMarkdown span, .stMarkdown td, .stMarkdown th, .stMarkdown b, .stMarkdown li, [data-testid="stWidgetLabel"] p, .stRadio p, .stButton p, .stDownloadButton p, input, textarea, [data-testid="stCaptionContainer"] p, .stAlert p, [data-testid="stExpander"] summary p {{ font-family: 'Inter', system-ui, sans-serif !important; }}
.stApp {{ background: {NIEBLA}; }}
#MainMenu, footer, header [data-testid="stToolbar"] {{ visibility: hidden; }}
header[data-testid="stHeader"] {{ background: transparent; height: 0; }}
.block-container {{ padding-top: 1.6rem; padding-bottom: 3rem; max-width: 1360px; }}
section[data-testid="stSidebar"] {{ background: {NOCHE}; }}
section[data-testid="stSidebar"] * {{ color: #E6EBF5; }}
section[data-testid="stSidebar"] .stRadio label p {{ font-size: 15px; font-weight: 500; }}
section[data-testid="stSidebar"] [data-testid="stCaptionContainer"] p {{ color: #AAB6D3 !important; }}
section[data-testid="stSidebar"] input {{ color: {NOCHE} !important; }}
section[data-testid="stSidebar"] .stButton button {{ background: #16254F; border: 1px solid #2A3C70; color: #fff; width: 100%; }}
section[data-testid="stSidebar"] .stButton button:hover {{ border-color: {MENTA}; color: {MENTA}; }}
section[data-testid="stSidebar"] .stButton button[kind="primary"] {{ background: {MENTA}; border-color: {MENTA}; color: {NOCHE}; font-weight: 700; }}
section[data-testid="stSidebar"] .stButton button[kind="primary"] p {{ color: {NOCHE} !important; }}
h1, h2, h3 {{ color: {NOCHE}; letter-spacing: -0.02em; }}
.k-titulo {{ font-family: 'Inter Display','Inter',sans-serif !important; font-weight: 800; font-size: 32px !important; line-height: 1.15; color: {NOCHE}; letter-spacing: -0.03em; margin: 0; }}
.k-sub {{ color: {PIZARRA}; font-size: 15px; margin: 6px 0 20px 0; }}
.k-card {{ background: #fff; border: 1px solid {BRUMA}; border-radius: 14px; padding: 16px 18px; }}
.k-kpi .lbl {{ white-space: nowrap; color: {PIZARRA}; font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: .04em; }}
.k-kpi .val {{ font-family: 'Inter Display','Inter',sans-serif !important; color: {NOCHE}; font-size: 30px; font-weight: 800; letter-spacing: -0.02em; margin-top: 4px; line-height: 1.1; }}
.k-kpi .det {{ color: {PIZARRA}; font-size: 13px; margin-top: 4px; }}
.k-kpi.ok {{ border-top: 4px solid {MENTA}; }} .k-kpi.warn {{ border-top: 4px solid {AMBAR}; }}
.k-kpi.stop {{ border-top: 4px solid {CORAL}; }} .k-kpi.info {{ border-top: 4px solid {AZUL}; }} .k-kpi.dark {{ border-top: 4px solid {NOCHE}; }}
.k-barra {{ height: 10px; background: {BRUMA}; border-radius: 99px; overflow: hidden; margin-top: 10px; }}
.k-barra > div {{ height: 100%; background: linear-gradient(90deg, {MENTA}, #12A984); border-radius: 99px; }}
.k-col-tit {{ display: flex; align-items: center; justify-content: space-between; padding: 10px 14px; border-radius: 12px; margin-bottom: 10px; font-weight: 700; font-size: 15px; }}
.k-col-tit .n {{ font-family: 'Inter Display','Inter',sans-serif; font-size: 20px; font-weight: 800; }}
.k-fac {{ background: #fff; border: 1px solid {BRUMA}; border-left: 5px solid var(--c); border-radius: 12px; padding: 12px 14px; margin-bottom: 10px; }}
.k-fac .top {{ display: flex; justify-content: space-between; align-items: baseline; gap: 8px; }}
.k-fac .id {{ font-weight: 700; color: {NOCHE}; font-size: 14px; }}
.k-fac .monto {{ font-weight: 700; color: {NOCHE}; font-size: 14.5px; white-space: nowrap; }}
.k-fac .ben {{ color: {NOCHE}; font-size: 14px; font-weight: 500; margin-top: 2px; display: flex; justify-content: space-between; gap: 8px; }}
.k-fac .ben .usd {{ color: {PIZARRA}; font-size: 12.5px; white-space: nowrap; }}
.k-fac .id {{ white-space: nowrap; }}
.k-fac .mot {{ color: {PIZARRA}; font-size: 12.8px; margin-top: 6px; line-height: 1.4; }}
.k-chip {{ display: inline-block; padding: 2px 8px; border-radius: 99px; font-size: 11.5px; font-weight: 600; border: 1px solid {BRUMA}; color: {PIZARRA}; background: {NIEBLA}; margin-right: 4px; }}
.k-badge {{ display: inline-block; padding: 3px 10px; border-radius: 99px; font-size: 12.5px; font-weight: 700; }}
.k-banner {{ border-radius: 14px; padding: 16px 18px; margin-bottom: 14px; border: 1px solid var(--b); background: var(--bg); }}
.k-banner .t {{ font-weight: 800; font-size: 18px; color: var(--tx); font-family: 'Inter Display','Inter',sans-serif; }}
.k-banner .m {{ color: {NOCHE}; font-size: 14.5px; margin-top: 6px; line-height: 1.5; }}
.k-regla {{ display: grid; grid-template-columns: 26px 46px 1fr; gap: 8px; padding: 9px 4px; border-bottom: 1px solid {BRUMA}; align-items: start; }}
.k-regla:last-child {{ border-bottom: none; }}
.k-regla .ico {{ width: 22px; height: 22px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 800; }}
.k-regla .rid {{ font-weight: 700; color: {PIZARRA}; font-size: 13px; padding-top: 2px; }}
.k-regla .nom {{ font-weight: 600; color: {NOCHE}; font-size: 13.5px; }}
.k-regla .det {{ color: {PIZARRA}; font-size: 12.8px; margin-top: 2px; line-height: 1.4; }}
.k-dato {{ display: flex; justify-content: space-between; gap: 10px; padding: 7px 0; border-bottom: 1px dashed {BRUMA}; font-size: 13.5px; }}
.k-dato .k {{ color: {PIZARRA}; }} .k-dato .v {{ color: {NOCHE}; font-weight: 600; text-align: right; }}
.k-conf {{ font-size: 11px; font-weight: 700; padding: 1px 6px; border-radius: 6px; margin-left: 6px; }}
.k-doc {{ background: #fff; border: 1px solid {BRUMA}; border-radius: 12px; padding: 14px 16px; font-family: 'DejaVu Sans Mono', ui-monospace, monospace; font-size: 12.5px; white-space: pre-wrap; color: #24304D; max-height: 560px; overflow: auto; line-height: 1.5; }}
.k-tabla {{ width: 100%; border-collapse: separate; border-spacing: 0; background: #fff; border: 1px solid {BRUMA}; border-radius: 14px; overflow: hidden; font-size: 13.5px; }}
.k-tabla th {{ text-align: left; background: #EEF1F7; color: {PIZARRA}; font-size: 11.5px; text-transform: uppercase; letter-spacing: .04em; padding: 10px 12px; }}
.k-tabla td {{ padding: 10px 12px; border-top: 1px solid {BRUMA}; color: {NOCHE}; vertical-align: top; }}
.k-tabla td.num {{ text-align: right; white-space: nowrap; font-weight: 600; }}
.k-tabla td.mot {{ color: {PIZARRA}; font-size: 12.8px; max-width: 520px; }}
.k-ev {{ background: #fff; border: 1px solid {BRUMA}; border-radius: 12px; padding: 12px 14px; margin-bottom: 8px; display: grid; grid-template-columns: 54px 190px 1fr; gap: 12px; }}
.k-ev .seq {{ font-family: 'Inter Display','Inter',sans-serif; font-weight: 800; color: {PIZARRA}; font-size: 18px; }}
.k-ev .meta {{ color: {PIZARRA}; font-size: 12.5px; line-height: 1.5; }}
.k-ev .txt {{ color: {NOCHE}; font-size: 13.5px; line-height: 1.45; }}
.k-ev .hash {{ font-family: 'DejaVu Sans Mono', monospace; color: #8A94AD; font-size: 11px; margin-top: 4px; }}
.k-ok {{ background: #E3F8F1; border: 1px solid #A8E8D3; color: #0B5E47; border-radius: 12px; padding: 12px 16px; font-weight: 600; }}
.k-bad {{ background: #FFE9E9; border: 1px solid #F7B4B4; color: #9F1D1D; border-radius: 12px; padding: 12px 16px; font-weight: 600; }}
.k-pilar {{ background: #fff; border: 1px solid {BRUMA}; border-radius: 14px; padding: 18px; height: 100%; }}
.k-pilar .t {{ font-weight: 800; font-size: 17px; color: {NOCHE}; }}
.k-pilar .v {{ font-family: 'Inter Display','Inter',sans-serif; font-size: 40px; font-weight: 800; letter-spacing: -0.03em; margin: 6px 0; }}
.k-pilar .d {{ color: {PIZARRA}; font-size: 13.5px; line-height: 1.5; }}
div[data-testid="stExpander"] details {{ background: #fff; border-radius: 12px; border: 1px solid {BRUMA}; }}
.stButton button {{ border-radius: 10px; font-weight: 600; }}
</style>
"""


def e(s) -> str:
    return html.escape(str(s if s is not None else "—"))


def badge(estado: str) -> str:
    nom, bg, tx, _ = ESTADOS[estado]
    return f'<span class="k-badge" style="background:{bg};color:{tx}">{nom}</span>'


def chip(t: str) -> str:
    return f'<span class="k-chip">{e(t)}</span>'


def kpi(lbl: str, val: str, det: str = "", tono: str = "dark", barra: float | None = None) -> str:
    b = f'<div class="k-barra"><div style="width:{max(0, min(100, barra)):.1f}%"></div></div>' if barra is not None else ""
    return f'<div class="k-card k-kpi {tono}"><div class="lbl">{e(lbl)}</div><div class="val">{val}</div><div class="det">{det}</div>{b}</div>'


def monto_txt(d) -> str:
    if d.monto is None:
        return "Monto ilegible"
    t = fmt_dinero(d.monto, d.moneda or "USD")
    if d.moneda and d.moneda != "USD" and d.monto_usd is not None:
        t += f' <span style="color:{PIZARRA};font-weight:500">· {fmt_dinero(d.monto_usd)}</span>'
    return t


def tarjeta_factura(f: dict, corto: bool = True) -> str:
    d = f["decision"]
    _, _, _, color = ESTADOS[f["estado"]]
    mot = d.motivo.split(":", 1)[-1].strip() if corto else d.motivo
    if corto and len(mot) > 150:
        mot = mot[:147].rsplit(" ", 1)[0] + "…"
    monto = fmt_dinero(d.monto, d.moneda or "USD") if d.monto is not None else "Monto ilegible"
    usd = (f'<span class="usd">≈ {fmt_dinero(round(d.monto_usd))}</span>'.replace(",00", "")
           if d.moneda and d.moneda != "USD" and d.monto_usd is not None else "")
    return (f'<div class="k-fac" style="--c:{color}"><div class="top"><span class="id">{e(f["factura_id"])} '
            f'{chip(CANALES.get(f["canal"], f["canal"]))}</span><span class="monto">{monto}</span></div>'
            f'<div class="ben"><span>{e(d.beneficiario_nombre)}</span>{usd}</div><div class="mot">{e(mot)}</div></div>')


def encabezado_columna(estado: str, n: int, total_usd: float | None = None) -> str:
    nom, bg, tx, _ = ESTADOS[estado]
    extra = f' <span style="font-weight:600;font-size:13px;opacity:.85">· {fmt_dinero(total_usd)}</span>' if total_usd else ""
    return f'<div class="k-col-tit" style="background:{bg};color:{tx}"><span>{nom}{extra}</span><span class="n">{n}</span></div>'


def banner_decision(f: dict) -> str:
    d = f["decision"]
    nom, bg, tx, color = ESTADOS[f["estado"]]
    titulos = {"pagada": "Kauta decidió pagar", "frenada": "Kauta frenó esta factura",
               "pendiente": "Kauta pide aprobación humana", "rechazada": "Rechazada por una persona"}
    if f.get("aprobacion"):
        titulos["pagada"] = "Pagada con aprobación humana"
    return (f'<div class="k-banner" style="--bg:{bg};--b:{color};--tx:{tx}"><div class="t">{titulos[f["estado"]]}</div>'
            f'<div class="m">{e(d.motivo)}</div></div>')


def lista_reglas(d) -> str:
    filas = []
    for r in d.reglas:
        if r.estado == "cumple":
            ico = '<div class="ico" style="background:#E3F8F1;color:#0B7A5C">✓</div>'
        elif r.estado == "no_aplica":
            ico = f'<div class="ico" style="background:{NIEBLA};color:#9AA4BA">–</div>'
        elif r.efecto == "frenar":
            ico = '<div class="ico" style="background:#FFE9E9;color:#C7302F">✕</div>'
        else:
            ico = '<div class="ico" style="background:#FFF4E0;color:#9A5800">!</div>'
        filas.append(f'<div class="k-regla">{ico}<div class="rid">{r.id}</div><div><div class="nom">{e(r.nombre)}'
                     f'<span class="k-chip" style="margin-left:8px">{"Frena" if r.efecto == "frenar" else "Escala"}</span></div>'
                     f'<div class="det">{e(r.detalle)}</div></div></div>')
    return '<div class="k-card" style="padding:6px 14px">' + "".join(filas) + "</div>"


def conf_chip(v: float | None, minimo: float) -> str:
    if v is None:
        return ""
    if v >= minimo:
        bg, tx = "#E3F8F1", "#0B7A5C"
    elif v >= 0.6:
        bg, tx = "#FFF4E0", "#9A5800"
    else:
        bg, tx = "#FFE9E9", "#C7302F"
    return f'<span class="k-conf" style="background:{bg};color:{tx}">{v:.2f}</span>'.replace(".", ",", 1)


def datos_extraidos(ext: dict, minimo: float) -> str:
    c = ext.get("confianza") or {}
    b = ext.get("beneficiario") or {}
    filas = [
        ("Beneficiario", b.get("nombre"), c.get("beneficiario")),
        ("Identificación fiscal", b.get("id_fiscal"), c.get("id_fiscal")),
        ("Número de factura", ext.get("numero_factura"), c.get("numero_factura")),
        ("Fecha de emisión", ext.get("fecha_emision"), None),
        ("Vence", ext.get("fecha_vencimiento"), c.get("fecha_vencimiento")),
        ("Moneda", ext.get("moneda"), c.get("moneda")),
        ("Monto total", fmt_dinero(ext.get("monto"), ext.get("moneda") or "USD") if ext.get("monto") is not None else None, c.get("monto")),
        ("Horas facturadas", ext.get("horas"), None),
        ("Concepto", ext.get("concepto"), None),
        ("Cuenta de destino", f"…{ext['cuenta_destino']}" if ext.get("cuenta_destino") else None, None),
    ]
    h = "".join(f'<div class="k-dato"><span class="k">{e(k)}</span><span class="v">{e(v)}{conf_chip(cf, minimo)}</span></div>'
                for k, v, cf in filas if v is not None or k in ("Monto total",))
    al = ext.get("alertas") or []
    if al:
        h += ('<div style="margin-top:10px" class="k-bad">⚠ Alerta: el documento contiene texto que intenta darle órdenes '
              'al agente. Se ignoró y se marcó para revisión.</div>')
    return '<div class="k-card">' + h + "</div>"
