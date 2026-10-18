"""
Kauta · 30 facturas del dataset del reto, llegando por canales distintos.

Toma facturas por pagar de data/reto/facturas.csv con sus ítems de data/reto/detalle_factura.csv
(proveedor, código, descripción, cantidad, unidad, precio, descuento, impuesto, retención, orden de compra,
fechas y condiciones) y las convierte en documentos a nombre de Brisamar Labs, la empresa de la demo:

  data/reto/documentos/F21_… a F50_…    PDF, foto, captura, correo (.eml), chat (.txt) y XML CFDI 4.0
  data/reto/documentos/referencia.json  la extracción verificada de cada documento (modo demo, sin IA)
  data/reto/beneficiarios_reto.json     los proveedores con su orden de compra, cuenta registrada y estado

Las identificaciones fiscales y las cuentas son sintéticas pero con formato y dígito de verificación válidos.
Todo es ficticio. Uso: python scripts/generar_reto.py
"""
from __future__ import annotations

import csv
import json
import random
import re
import shutil
import sys
import uuid as _uuid
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "scripts"))
import generar_set as G  # noqa: E402  (plantillas de dibujo, correo, chat e imágenes del set original)
from reportlab.lib.colors import HexColor, white  # noqa: E402
from reportlab.lib.pagesizes import letter  # noqa: E402
from reportlab.pdfgen import canvas  # noqa: E402

from kauta.normalizacion import _dv_cnpj, dv_nit, dv_rfc, validar_id_fiscal  # noqa: E402

RETO = RAIZ / "data" / "reto"
DOCS = RETO / "documentos"
TMP = RETO / "_tmp"
W, H = letter
random.seed(2026)

# Orden de llegada (F21…F50) y canal de cada factura del dataset
SELECCION = [
    ("SIM-FAC-0059", "pdf"), ("SIM-FAC-0012", "pdf"), ("SIM-FAC-0013", "xml"), ("SIM-FAC-0030", "correo"),
    ("SIM-FAC-0016", "foto"), ("SIM-FAC-0035", "chat"), ("SIM-FAC-0011", "pdf"), ("SIM-FAC-0021", "correo"),
    ("SIM-FAC-0028", "xml"), ("SIM-FAC-0046", "pdf"), ("SIM-FAC-0063", "captura"), ("SIM-FAC-0047", "correo"),
    ("SIM-FAC-0036", "chat"), ("SIM-FAC-0061", "pdf"), ("SIM-FAC-0034", "xml"), ("SIM-FAC-0019", "correo"),
    ("SIM-FAC-0076", "foto"), ("SIM-FAC-0037", "pdf"), ("SIM-FAC-0045", "chat"), ("SIM-FAC-0078", "pdf"),
    ("SIM-FAC-0049", "xml"), ("SIM-FAC-0051", "correo"), ("SIM-FAC-0053", "chat"), ("SIM-FAC-0066", "captura"),
    ("SIM-FAC-0081", "pdf"), ("SIM-FAC-0079", "xml"), ("SIM-FAC-0083", "correo"), ("SIM-FAC-0069", "foto"),
    ("SIM-FAC-0084", "chat"), ("SIM-FAC-0062", "pdf"),
]
CANAL_KAUTA = {"pdf": "pdf", "xml": "xml", "correo": "correo", "chat": "chat", "foto": "imagen", "captura": "imagen"}
EXTENSION = {"pdf": "pdf", "xml": "xml", "correo": "eml", "chat": "txt", "foto": "jpg", "captura": "png"}
COLORES = ["#1F6FB2", "#0E8A6A", "#7A4FE0", "#B4457F", "#C46A12", "#2F4F9E", "#0B7A75", "#8A3FB0"]
IDIOMA = {"US": "en", "BR": "pt"}  # el resto, en español
D2 = Decimal("0.01")


def dec(v: str | None) -> Decimal:
    return Decimal(str(v or "0"))


def num(v: Decimal | float, moneda: str, idioma: str = "es") -> str:
    d = 0 if moneda == "COP" else 2
    s = f"{float(v):,.{d}f}"
    return s if idioma == "en" else s.replace(",", "§").replace(".", ",").replace("§", ".")


def fecha_txt(iso: str, idioma: str = "es") -> str:
    a, m, d = iso.split("-")
    return f"{m}/{d}/{a}" if idioma == "en" else f"{d}/{m}/{a}"


def slug(nombre: str) -> str:
    s = re.sub(r"^SIM\s+", "", nombre).lower()
    s = (s.replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u").replace("ñ", "n"))
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


# ---------------------------------------------------------------------------
# Identificaciones fiscales y cuentas sintéticas (formato y dígito de verificación válidos)
# ---------------------------------------------------------------------------
def id_fiscal(pais: str, n: int, nombre: str) -> str:
    if pais == "US":
        return f"EIN {['81', '82', '83', '84', '85', '86', '87', '88'][n % 8]}-{(n * 7919 + 1234567) % 10_000_000:07d}"
    if pais == "CO":
        base = f"9{(n * 104729 + 12_000_000) % 100_000_000:08d}"
        return f"NIT {base[:3]}.{base[3:6]}.{base[6:]}-{dv_nit(base)}"
    if pais == "MX":
        letras = "".join(w[0] for w in nombre.upper().split() if w.isalpha())[:3].ljust(3, "X")
        base = f"{letras}{10 + n % 15:02d}{n % 12 + 1:02d}{n % 27 + 1:02d}{'ABCDEFGHJKLMNPRSTUV'[n % 19]}{'123456789ABCDEFGH'[n % 17]}"
        return f"RFC {base}{dv_rfc(base)}"
    if pais == "BR":
        cuerpo = f"{(n * 7_654_321 + 11_223_344) % 100_000_000:08d}0001"
        d1 = _dv_cnpj(cuerpo, (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2))
        d2 = _dv_cnpj(cuerpo + d1, (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2))
        s = cuerpo + d1 + d2
        return f"CNPJ {s[:2]}.{s[2:5]}.{s[5:8]}/{s[8:12]}-{s[12:]}"
    return f"NIF B{(n * 3571 + 46_000_000) % 100_000_000:08d}"   # España: sin validador en Kauta (queda «no reconocido»)


def cuenta(n: int) -> str:
    return f"{(n * 37 + 1103) % 9000 + 1000}"


# ---------------------------------------------------------------------------
# Datos de cada factura desde los CSV
# ---------------------------------------------------------------------------
def cargar() -> list[dict]:
    fac = {r["factura_id"]: r for r in csv.DictReader(open(RETO / "facturas.csv", encoding="utf-8-sig"))}
    det: dict[str, list[dict]] = {}
    for r in csv.DictReader(open(RETO / "detalle_factura.csv", encoding="utf-8-sig")):
        det.setdefault(r["factura_id"], []).append(r)
    salida = []
    for i, (fid_reto, canal) in enumerate(SELECCION):
        r = fac[fid_reto]
        n = int(r["contraparte_id"].rsplit("-", 1)[-1])
        moneda, pais = r["moneda_factura"], r["contraparte_pais"]
        sub, desc, base = dec(r["subtotal_bruto"]), dec(r["descuento_comercial_valor"]), dec(r["base_imponible"])
        imp, ret, neto = dec(r["impuesto_valor"]), dec(r["retencion_valor"]), dec(r["saldo_contraparte"])
        anticipo = dec(r["anticipo_aplicado"])
        assert abs(sub - desc - base) <= D2 and abs(base + imp - ret - anticipo - neto) <= D2, fid_reto   # el CSV cuadra
        assert not (anticipo and canal == "xml"), f"{fid_reto}: un CFDI con anticipo necesita su propio comprobante"
        lineas = sorted(det[fid_reto], key=lambda x: int(x["numero_linea"]))
        d = {
            "id": f"F{21 + i}", "reto": fid_reto, "canal": canal, "n": n, "idioma": IDIOMA.get(pais, "es"),
            "proveedor": r["contraparte_nombre"], "pais": pais, "id_fiscal": id_fiscal(pais, n, r["contraparte_nombre"]),
            "contacto": r["contraparte_contacto"], "cuenta": cuenta(n), "numero": r["numero_factura"],
            "emision": r["fecha_emision"], "vence": r["fecha_vencimiento"], "recepcion": r["fecha_recepcion"],
            "plazo": r["plazo_pago_dias"], "moneda": moneda, "subtotal": sub, "descuento": desc, "base": base,
            "tasa_imp": dec(r["tasa_impuesto_pct"]), "impuesto": imp, "tasa_ret": dec(r["tasa_retencion_pct"]), "retencion": ret,
            "anticipo": anticipo, "total": neto, "oc": r["orden_compra_id"], "contrato": r["contrato_id"], "centro": r["centro_costo"],
            "proyecto": r["activo_proyecto_id"], "concepto": r["subcategoria"], "descripcion": r["descripcion_factura"],
            "condiciones": r["condiciones_pago_texto"], "periodo_servicio": (r["periodo_servicio_inicio"], r["periodo_servicio_fin"]),
            "estado": r["estado_documento"], "motivo_revision": r["motivo_revision"], "empresa_reto": r["empresa_referencia"],
            "oc_usd": dec(r["monto_orden_compra_usd"]), "desviacion_usd": dec(r["desviacion_orden_compra_usd"]),
            "contraparte_reto": r["contraparte_id"], "id_reto": r["contraparte_identificacion"],
            "lineas": [{"codigo": x["sku_servicio"], "descripcion": x["descripcion_concepto"], "unidad": x["unidad_medida"],
                        "cantidad": dec(x["cantidad"]), "precio": dec(x["precio_unitario"]), "importe": dec(x["importe_bruto_linea"]),
                        "descuento": dec(x["descuento_comercial_linea"]), "base": dec(x["base_neta_linea"]),
                        "impuesto": dec(x["impuesto_linea"]), "retencion": dec(x["retencion_linea"])} for x in lineas],
            "color": COLORES[i % len(COLORES)],
        }
        d["hora"] = f"{9 + n % 8:02d}:{(n * 7) % 60:02d}"
        d["archivo"] = f"{d['id']}_{slug(d['proveedor'])}_{d['numero']}.{EXTENSION[canal]}"
        salida.append(d)
    return salida


def cantidad_txt(c: Decimal, idioma: str) -> str:
    return num(c, "COP", idioma) if c == c.to_integral_value() else num(c, "USD", idioma)


# ---------------------------------------------------------------------------
# PDF con los ítems (idioma según el país del proveedor)
# ---------------------------------------------------------------------------
ET = {
    "es": dict(titulo="FACTURA", num="Factura N.°", fecha="Fecha de emisión", vence="Vencimiento", plazo="Plazo",
               dias="{d} días", moneda="Moneda", oc="Orden de compra", cc="Centro de costo", a="FACTURADO A",
               cols=["CÓDIGO", "DESCRIPCIÓN", "CANT.", "UNIDAD", "PRECIO UNIT.", "IMPORTE"], subtotal="Subtotal",
               desc="Descuento comercial", base="Base", imp="Impuesto (simulado) {t} %", ret="Retención (simulada) {t} %",
               anticipo="Anticipo aplicado", total="TOTAL A PAGAR", pago="INSTRUCCIONES DE PAGO", pago_txt="Transferencia a la cuenta registrada terminada en {c}.",
               ref="Cite la factura {n} y la orden de compra {oc} en el pago.", periodo="Periodo del servicio: {a} a {b}"),
    "en": dict(titulo="INVOICE", num="Invoice #", fecha="Invoice date", vence="Due date", plazo="Terms",
               dias="Net {d}", moneda="Currency", oc="PO number", cc="Cost center", a="BILL TO",
               cols=["CODE", "DESCRIPTION", "QTY", "UNIT", "UNIT PRICE", "AMOUNT"], subtotal="Subtotal",
               desc="Trade discount", base="Taxable base", imp="Tax (simulated) {t}%", ret="Withholding (simulated) {t}%",
               anticipo="Advance applied", total="AMOUNT DUE", pago="PAYMENT INSTRUCTIONS", pago_txt="Bank transfer to the registered account ending in {c}.",
               ref="Please reference invoice {n} and PO {oc} in your payment.", periodo="Service period: {a} to {b}"),
    "pt": dict(titulo="FATURA", num="Fatura n.º", fecha="Data de emissão", vence="Vencimento", plazo="Prazo",
               dias="{d} dias", moneda="Moeda", oc="Pedido de compra", cc="Centro de custo", a="FATURADO PARA",
               cols=["CÓDIGO", "DESCRIÇÃO", "QTD.", "UNIDADE", "PREÇO UNIT.", "VALOR"], subtotal="Subtotal",
               desc="Desconto comercial", base="Base", imp="Imposto (simulado) {t} %", ret="Retenção (simulada) {t} %",
               anticipo="Adiantamento aplicado", total="TOTAL A PAGAR", pago="INSTRUÇÕES DE PAGAMENTO", pago_txt="Transferência para a conta cadastrada final {c}.",
               ref="Informe a fatura {n} e o pedido {oc} no pagamento.", periodo="Período do serviço: {a} a {b}"),
}


def pdf_factura(path: Path, d: dict) -> None:
    e, idi, mon = ET[d["idioma"]], d["idioma"], d["moneda"]
    c = canvas.Canvas(str(path), pagesize=letter)
    c.setTitle(f"{e['titulo']} {d['numero']} - {d['proveedor']}")
    G.marca_agua(c)
    col = HexColor(d["color"])
    c.setFillColor(col)
    c.rect(0, H - 12, W, 12, stroke=0, fill=1)
    G.texto(c, 46, H - 62, d["proveedor"], 16, "Helvetica-Bold", col)
    G.texto(c, 46, H - 78, f"{d['id_fiscal']}  ·  {d['contacto']}", 8.4, color=G.GRIS)
    G.texto(c, 46, H - 90, {"US": "United States", "CO": "Colombia", "MX": "México", "ES": "España", "BR": "Brasil"}[d["pais"]],
            8.4, color=G.GRIS)
    G.texto(c, W - 46, H - 62, e["titulo"], 22, "Helvetica-Bold", G.NEGRO, "right")
    G.texto(c, W - 46, H - 80, f"{e['num']} {d['numero']}", 10, "Helvetica-Bold", align="right")
    G.caja(c, 46, H - 196, 250, 88)
    G.texto(c, 58, H - 126, e["a"], 7.5, "Helvetica-Bold", G.GRIS)
    rec = d.get("receptor") or {"nombre": "Brisamar Labs Inc.", "linea": "EIN 88-4410273 · Miami, FL, USA",
                                "correo": "cuentasporpagar@brisamar.example"}   # a quién va facturada (la empresa, salvo ventas)
    G.texto(c, 58, H - 142, rec["nombre"], 10.5, "Helvetica-Bold")
    G.texto(c, 58, H - 156, rec["linea"], 8.6)
    G.texto(c, 58, H - 169, rec["correo"], 8.6, color=G.GRIS)
    G.texto(c, 58, H - 182, e["periodo"].format(a=fecha_txt(d["periodo_servicio"][0], idi), b=fecha_txt(d["periodo_servicio"][1], idi)),
            8.2, color=G.GRIS)
    G.caja(c, W - 296, H - 196, 250, 88)
    filas = [(e["fecha"], fecha_txt(d["emision"], idi)), (e["vence"], fecha_txt(d["vence"], idi)),
             (e["plazo"], e["dias"].format(d=d["plazo"])), (e["moneda"], mon), (e["oc"], d["oc"]), (e["cc"], d["centro"])]
    for i, (k, v) in enumerate(filas):
        G.texto(c, W - 284, H - 124 - i * 13, k, 8.2, color=G.GRIS)
        G.texto(c, W - 58, H - 124 - i * 13, v, 8.4, "Helvetica-Bold", align="right")
    filas_items = [[x["codigo"], x["descripcion"][:44], cantidad_txt(x["cantidad"], idi), x["unidad"].replace("_", " "),
                    num(x["precio"], mon, idi), num(x["importe"], mon, idi)] for x in d["lineas"]]
    yy = G.tabla(c, 46, H - 218, e["cols"], filas_items, [78, 214, 40, 64, 62, 62], size=8.2)
    yy -= 16
    tot = [(e["subtotal"], d["subtotal"])]
    if d["descuento"]:
        tot += [(e["desc"], -d["descuento"]), (e["base"], d["base"])]
    if d["impuesto"]:
        tot.append((e["imp"].format(t=num(d["tasa_imp"], "COP")), d["impuesto"]))
    if d["retencion"]:
        tot.append((e["ret"].format(t=num(d["tasa_ret"], "COP")), -d["retencion"]))
    if d["anticipo"]:
        tot.append((e["anticipo"], -d["anticipo"]))
    for i, (k, v) in enumerate(tot):
        G.texto(c, W - 250, yy - i * 14, k, 8.6, color=G.GRIS)
        G.texto(c, W - 52, yy - i * 14, f"{mon} {num(v, mon, idi)}", 8.8, align="right")
    yt = yy - len(tot) * 14 - 22
    c.setFillColor(col)
    c.roundRect(W - 262, yt - 8, 216, 26, 4, stroke=0, fill=1)
    G.texto(c, W - 252, yt + 1, e["total"], 8.6, "Helvetica-Bold", white)
    G.texto(c, W - 54, yt, f"{mon} {num(d['total'], mon, idi)}", 11.5, "Helvetica-Bold", white, "right")
    G.texto(c, 46, yy, e["pago"], 7.6, "Helvetica-Bold", G.GRIS)
    G.texto(c, 46, yy - 14, e["pago_txt"].format(c=d["cuenta"]), 8.6)
    G.texto(c, 46, yy - 27, e["ref"].format(n=d["numero"], oc=d["oc"]), 8.2, color=G.GRIS)
    cond = d["condiciones"]
    G.texto(c, 46, yy - 44, cond[:96], 7.8, color=G.GRIS)
    if len(cond) > 96:
        G.texto(c, 46, yy - 55, cond[96:190], 7.8, color=G.GRIS)
    G.texto(c, 46, 44, f"Referencia del dataset del reto: {d['reto']} · contraparte {d['contraparte_reto']} · {d['id_reto']} · "
                       f"contrato {d['contrato']} · proyecto {d['proyecto']}", 6.8, color=G.GRIS)
    G.pie(c)
    c.save()


# ---------------------------------------------------------------------------
# Imágenes: foto con el celular y captura de pantalla
# ---------------------------------------------------------------------------
def foto(pdf: Path, salida: Path) -> None:
    from PIL import Image, ImageDraw, ImageFilter
    img = G.pdf_a_png(pdf, dpi=120).convert("RGB")
    w, h = img.size
    img = img.crop((0, 0, w, int(h * 0.78))).filter(ImageFilter.GaussianBlur(0.6))
    img = Image.blend(img, Image.new("RGB", img.size, (255, 238, 210)), 0.12)
    w, h = img.size
    fondo = Image.new("RGB", (int(w * 1.12), int(h * 1.14)), (92, 78, 66))
    rot = img.rotate(random.choice([-2.6, -1.8, 1.9, 2.4]), expand=True, fillcolor=(92, 78, 66), resample=Image.BICUBIC)
    fondo.paste(rot, (int(w * 0.05), int(h * 0.06)))
    vig = Image.new("L", fondo.size, 255)
    dib = ImageDraw.Draw(vig)
    fw, fh = fondo.size
    for i in range(24):
        dib.rectangle([i * 5, i * 5, fw - i * 5, fh - i * 5], outline=int(170 + 85 * (i / 24)))
    fondo = Image.composite(fondo, Image.new("RGB", fondo.size, (28, 22, 18)), vig.filter(ImageFilter.GaussianBlur(36)))
    fondo = Image.blend(fondo, Image.effect_noise(fondo.size, 18).convert("RGB"), 0.05)
    fondo.save(salida, "JPEG", quality=72)


def captura(pdf: Path, salida: Path) -> None:
    img = G.pdf_a_png(pdf, dpi=110).convert("RGB")
    w, h = img.size
    img.crop((0, 0, w, int(h * 0.80))).save(salida, "PNG", optimize=True)


# ---------------------------------------------------------------------------
# Correo y chat
# ---------------------------------------------------------------------------
def texto_items(d: dict, vineta: str = "•") -> list[str]:
    mon, idi = d["moneda"], d["idioma"]
    filas = [f"{vineta} {x['codigo']} · {x['descripcion']}: {cantidad_txt(x['cantidad'], idi)} {x['unidad'].replace('_', ' ')} × "
             f"{mon} {num(x['precio'], mon, idi)} = {mon} {num(x['importe'], mon, idi)}" for x in d["lineas"]]
    filas.append(f"Subtotal {mon} {num(d['subtotal'], mon, idi)}"
                 + (f" · descuento {mon} {num(d['descuento'], mon, idi)}" if d["descuento"] else "")
                 + (f" · impuesto {num(d['tasa_imp'], 'COP')} % {mon} {num(d['impuesto'], mon, idi)}" if d["impuesto"] else "")
                 + (f" · retención {num(d['tasa_ret'], 'COP')} % {mon} {num(d['retencion'], mon, idi)}" if d["retencion"] else "")
                 + (f" · anticipo aplicado {mon} {num(d['anticipo'], mon, idi)}" if d["anticipo"] else ""))
    filas.append(f"Total a pagar: {mon} {num(d['total'], mon, idi)}")
    return filas


def correo(path: Path, d: dict, pdf: Path) -> None:
    ingles = d["idioma"] == "en"
    cuerpo = (["Hello Brisamar team,", "", f"Please find attached invoice {d['numero']} for {d['concepto'].lower()}."]
              if ingles else ["Buenos días, equipo de Brisamar:", "",
                              f"Adjuntamos la factura {d['numero']} por {d['concepto'].lower()}."])
    cuerpo += ["", *texto_items(d, "-"), "",
               (f"Due date: {fecha_txt(d['vence'], 'en')} · PO {d['oc']} · cost center {d['centro']}." if ingles else
                f"Vence el {fecha_txt(d['vence'])} · orden de compra {d['oc']} · centro de costo {d['centro']}."),
               (f"Payment to the registered account ending in {d['cuenta']}." if ingles else
                f"El pago va a la cuenta registrada terminada en {d['cuenta']}."),
               "", "Regards," if ingles else "Saludos cordiales,", f"Facturación · {d['proveedor']}", d["contacto"]]
    asunto = (f"Invoice {d['numero']} · {d['concepto']}" if ingles else f"Factura {d['numero']} · {d['concepto']}")
    G.eml(path, f"{d['proveedor']} <{d['contacto']}>", "Cuentas por pagar Brisamar <cuentasporpagar@brisamar.example>",
          asunto, f"{d['recepcion']}T{d['hora']}:00", "\n".join(cuerpo), [pdf])


def chat(path: Path, d: dict) -> None:
    a, m, dd = d["recepcion"].split("-")
    t = f"[{dd}/{m}/{a[2:]}, {d['hora']}]"
    quien = f"{d['proveedor']} (facturación)"
    lineas = [f"{t} {quien}: Hola, les comparto la factura {d['numero']} de {d['concepto'].lower()}.",
              f"{t} {quien}: Detalle de los ítems:"]
    lineas += [f"{t} {quien}: {x}" for x in texto_items(d)]
    lineas += [f"{t} {quien}: Vence el {fecha_txt(d['vence'])}. Orden de compra {d['oc']}. "
               f"Pago a la cuenta registrada terminada en {d['cuenta']}.",
               f"{t} {quien}: Identificación: {d['id_fiscal']}.",
               f"{t} Mariana Torres (Brisamar): Recibida, gracias. Kauta la revisa contra la orden de compra."]
    G.chat(path, lineas)


# ---------------------------------------------------------------------------
# XML CFDI 4.0 (proveedores de México): Kauta lo lee exacto, sin IA
# ---------------------------------------------------------------------------
CLAVE_UNIDAD = {"horas": "HUR", "meses": "MON", "piezas": "H87", "licencias": "E48", "documentos": "E48"}


def f2(v: Decimal) -> str:
    return f"{v.quantize(D2, ROUND_HALF_UP)}"


def xml_cfdi(path: Path, d: dict) -> None:
    rfc = d["id_fiscal"].split()[-1]
    folio = d["numero"].rsplit("-", 1)[-1]
    uuid = str(_uuid.uuid5(_uuid.NAMESPACE_URL, f"kauta.example/reto/{d['reto']}")).upper()
    sello = G.b64_aleatorio(342)
    rfc_pac = "PSI150101AB" + dv_rfc("PSI150101AB")
    tasa_i, tasa_r = d["tasa_imp"] / 100, d["tasa_ret"] / 100
    conceptos = []
    for x in d["lineas"]:
        imps = (f'<cfdi:Traslados><cfdi:Traslado Base="{f2(x["base"])}" Impuesto="002" TipoFactor="Tasa" '
                f'TasaOCuota="{tasa_i:.6f}" Importe="{f2(x["impuesto"])}"/></cfdi:Traslados>')
        if x["retencion"]:
            imps += (f'<cfdi:Retenciones><cfdi:Retencion Base="{f2(x["base"])}" Impuesto="001" TipoFactor="Tasa" '
                     f'TasaOCuota="{tasa_r:.6f}" Importe="{f2(x["retencion"])}"/></cfdi:Retenciones>')
        conceptos.append(
            f'    <cfdi:Concepto ClaveProdServ="81111500" NoIdentificacion="{x["codigo"]}" Cantidad="{x["cantidad"]}" '
            f'ClaveUnidad="{CLAVE_UNIDAD.get(x["unidad"], "E48")}" Unidad="{x["unidad"]}" Descripcion="{x["descripcion"]}" '
            f'ValorUnitario="{f2(x["precio"])}" Importe="{f2(x["importe"])}"'
            + (f' Descuento="{f2(x["descuento"])}"' if x["descuento"] else "") + ' ObjetoImp="02">\n'
            f'      <cfdi:Impuestos>{imps}</cfdi:Impuestos>\n    </cfdi:Concepto>')
    ret_glob = (f'\n    <cfdi:Retenciones><cfdi:Retencion Impuesto="001" Importe="{f2(d["retencion"])}"/></cfdi:Retenciones>'
                if d["retencion"] else "")
    total_ret = f' TotalImpuestosRetenidos="{f2(d["retencion"])}"' if d["retencion"] else ""
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
{G.AVISO_XML}
<!-- Construido con los ítems de {d['reto']} del dataset del reto (facturas.csv y detalle_factura.csv). -->
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4" xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  xsi:schemaLocation="http://www.sat.gob.mx/cfd/4 http://www.sat.gob.mx/sitio_internet/cfd/4/cfdv40.xsd"
  Version="4.0" Serie="SIM" Folio="{folio}" Fecha="{d['emision']}T{d['hora']}:00" Sello="{sello}" FormaPago="99"
  NoCertificado="30001000000500000000" Certificado="{G.b64_aleatorio(400)}"
  CondicionesDePago="Fecha límite de pago: {fecha_txt(d['vence'])} · orden de compra {d['oc']}"
  SubTotal="{f2(d['subtotal'])}"{f' Descuento="{f2(d["descuento"])}"' if d['descuento'] else ''} Moneda="{d['moneda']}"{'' if d['moneda'] == 'MXN' else ' TipoCambio="18.40"'} Total="{f2(d['total'])}"
  TipoDeComprobante="I" Exportacion="02" MetodoPago="PPD" LugarExpedicion="06700">
  <cfdi:Emisor Rfc="{rfc}" Nombre="{d['proveedor'].upper()}" RegimenFiscal="601"/>
  <cfdi:Receptor Rfc="XEXX010101000" Nombre="BRISAMAR LABS INC" DomicilioFiscalReceptor="06700" ResidenciaFiscal="USA"
    NumRegIdTrib="884410273" RegimenFiscalReceptor="616" UsoCFDI="S01"/>
  <cfdi:Conceptos>
{chr(10).join(conceptos)}
  </cfdi:Conceptos>
  <cfdi:Impuestos TotalImpuestosTrasladados="{f2(d['impuesto'])}"{total_ret}>{ret_glob}
    <cfdi:Traslados><cfdi:Traslado Base="{f2(d['base'])}" Impuesto="002" TipoFactor="Tasa" TasaOCuota="{tasa_i:.6f}" Importe="{f2(d['impuesto'])}"/></cfdi:Traslados>
  </cfdi:Impuestos>
  <cfdi:Complemento>
    <tfd:TimbreFiscalDigital Version="1.1" UUID="{uuid}" FechaTimbrado="{d['emision']}T{d['hora']}:40" RfcProvCertif="{rfc_pac}"
      SelloCFD="{sello}" NoCertificadoSAT="00001000000700000000" SelloSAT="{G.b64_aleatorio(342)}"/>
  </cfdi:Complemento>
</cfdi:Comprobante>
"""
    path.write_text(xml, encoding="utf-8")


# ---------------------------------------------------------------------------
# Extracción verificada y proveedores
# ---------------------------------------------------------------------------
def referencia(d: dict) -> dict:
    canal = CANAL_KAUTA[d["canal"]]
    conf = {"pdf": 0.98, "correo": 0.97, "chat": 0.95, "imagen": 0.92 if d["canal"] == "foto" else 0.96}.get(canal, 0.98)
    f = float
    imp = [{"tipo": "Impuesto (simulado)", "tasa": f(d["tasa_imp"]), "base": f(d["base"]), "monto": f(d["impuesto"]), "retencion": False}]
    if d["retencion"]:
        imp.append({"tipo": "Retención (simulada)", "tasa": f(d["tasa_ret"]), "base": f(d["base"]), "monto": f(d["retencion"]),
                    "retencion": True})
    return {
        "factura_id": d["id"], "canal": canal, "recibida": f"{d['recepcion']}T{d['hora']}", "dataset_reto": d["reto"],
        "beneficiario": {"nombre": d["proveedor"], "id_fiscal": d["id_fiscal"], "pais": d["pais"]},
        "contacto": f"{d['proveedor']} (WhatsApp)" if canal == "chat" else d["contacto"],
        "numero_factura": d["numero"], "fecha_emision": d["emision"], "fecha_vencimiento": d["vence"],
        "moneda": d["moneda"], "monto": f(d["total"]), "horas": None, "concepto": d["descripcion"],
        "cuenta_destino": d["cuenta"], "alertas": [],
        "confianza": {"beneficiario": conf, "id_fiscal": round(conf - 0.01, 2), "numero_factura": conf, "moneda": 0.99,
                      "monto": conf, "fecha_vencimiento": round(conf - 0.02, 2)},
        "lineas": [{"codigo": x["codigo"], "descripcion": x["descripcion"], "cantidad": f(x["cantidad"]), "unidad": x["unidad"],
                    "precio_unitario": f(x["precio"]), "total": f(x["importe"])} for x in d["lineas"]],
        "impuestos": imp, "subtotal": f(d["subtotal"]), "total": f(d["total"]), "orden_compra": d["oc"],
        **({"anticipo": f(d["anticipo"])} if d["anticipo"] else {}),
    }


def beneficiario(i: int, d: dict) -> dict:
    total = d["total"]
    if d["desviacion_usd"] > 0:   # «Base facturada superior a orden de compra»: la orden vale menos que lo facturado
        acordado = (total * d["oc_usd"] / (d["oc_usd"] + d["desviacion_usd"])).quantize(D2, ROUND_HALF_UP)
    else:
        acordado = total
    disputa = d["estado"] == "EN_DISPUTA"
    return {
        "id": f"D{i + 1:02d}", "nombre": d["proveedor"], "id_fiscal": d["id_fiscal"], "pais": d["pais"], "tipo_persona": "juridica",
        "categoria": d["concepto"], "cuenta_registrada": d["cuenta"], "contactos": [d["contacto"]],
        "contrato": {"tipo": "orden_compra", "moneda": d["moneda"], "monto": float(acordado), "referencia": d["oc"]},
        "estado": "bloqueado" if disputa else "activo",
        "motivo_bloqueo": (f"Factura {d['numero']} en disputa: {d['motivo_revision'].lower()}. No se paga hasta resolverla."
                           if disputa else None),
        "dataset_reto": {"factura": d["reto"], "contraparte": d["contraparte_reto"], "empresa": d["empresa_reto"]},
    }


def main() -> None:
    datos = cargar()
    if DOCS.exists():
        shutil.rmtree(DOCS)
    DOCS.mkdir(parents=True)
    TMP.mkdir(exist_ok=True)
    ref, bens = {}, []
    for i, d in enumerate(datos):
        assert validar_id_fiscal(d["id_fiscal"], d["pais"]).valido is not False, d["id_fiscal"]
        ruta = DOCS / d["archivo"]
        canal = d["canal"]
        if canal == "xml":
            xml_cfdi(ruta, d)
        elif canal == "chat":
            chat(ruta, d)
        else:
            pdf = ruta if canal == "pdf" else TMP / f"{d['id']}_{d['numero']}.pdf"
            pdf_factura(pdf, d)
            if canal == "correo":
                correo(ruta, d, pdf)
            elif canal == "foto":
                foto(pdf, ruta)
            elif canal == "captura":
                captura(pdf, ruta)
        ref[d["archivo"]] = referencia(d)
        bens.append(beneficiario(i, d))
    shutil.rmtree(TMP)
    (DOCS / "referencia.json").write_text(json.dumps(ref, ensure_ascii=False, indent=2), encoding="utf-8")
    (RETO / "beneficiarios_reto.json").write_text(json.dumps(bens, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(datos)} facturas del dataset del reto en {DOCS}")
    for d in datos:
        p = DOCS / d["archivo"]
        print(f"  {d['archivo']:52s} {CANAL_KAUTA[d['canal']]:7s} {d['moneda']} {num(d['total'], d['moneda']):>16s}  "
              f"{p.stat().st_size / 1024:6.1f} KB")


if __name__ == "__main__":
    main()
