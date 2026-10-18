"""
Kauta · Lector local sin IA: OCR de imágenes y PDF escaneados, y extracción de campos por reglas.

Por qué existe: muchas facturas llegan como foto de celular o como PDF escaneado, sin una sola
letra que el computador pueda leer. Este módulo las lee **dentro del servidor de la empresa**: el
documento no sale hacia ningún servicio externo, no cuesta por página y funciona sin internet.

Cómo encaja en Kauta (la IA sigue siendo opcional):

    XML fiscal exacto  →  texto incrustado del PDF  →  OCR local  →  IA, solo si hace falta

Lo que entrega es lo mismo que entrega la IA: los campos de la factura con una **confianza de 0 a 1
por campo**. Esa confianza la calcula el propio OCR (qué tan seguro está de cada palabra) y se
castiga cuando el dato no se puede verificar. El motor de 13 reglas decide igual que siempre: si un
campo crítico queda por debajo de la confianza mínima, la factura escala en lugar de pagarse.

Requisitos: Tesseract 5 con los idiomas spa y eng. Si no está instalado, `disponible()` devuelve
False y Kauta sigue funcionando con los otros lectores.
"""
from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from . import normalizacion as N

IDIOMAS = "spa+eng"
MIN_LADO = 2200          # si la imagen es pequeña, se agranda antes de leerla (Tesseract lee mejor letra grande)
MAX_LADO = 3500          # y si es enorme, se reduce: Tesseract no mejora por encima de esto
PPP_PDF = 300            # resolución a la que se rasteriza cada página de un PDF escaneado
MAX_PAGINAS = 5
CONF_MINIMA_PALABRA = 35  # por debajo de esto, la palabra se considera ruido


# ---------------------------------------------------------------------------
# Disponibilidad
# ---------------------------------------------------------------------------
def _binario() -> str | None:
    """Tesseract en KAUTA_TESSERACT, en el PATH o donde lo deja el instalador de Windows (para todos o solo el usuario)."""
    propio = os.environ.get("KAUTA_TESSERACT", "").strip()
    if propio and Path(propio).is_file():
        return propio
    encontrado = shutil.which("tesseract")
    if encontrado:
        return encontrado
    for base in (os.environ.get("LOCALAPPDATA"), os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
        if base and (Path(base) / "Programs" / "Tesseract-OCR" / "tesseract.exe").is_file():
            return str(Path(base) / "Programs" / "Tesseract-OCR" / "tesseract.exe")
        if base and (Path(base) / "Tesseract-OCR" / "tesseract.exe").is_file():
            return str(Path(base) / "Tesseract-OCR" / "tesseract.exe")
    return None


def idiomas_instalados() -> list[str]:
    exe = _binario()
    if not exe:
        return []
    try:
        salida = subprocess.run([exe, "--list-langs"], capture_output=True, text=True, timeout=20)
        return [l.strip() for l in salida.stdout.splitlines()[1:] if l.strip()]
    except Exception:
        return []


def disponible() -> bool:
    return bool(_binario()) and "spa" in idiomas_instalados()


def version() -> str:
    exe = _binario()
    if not exe:
        return "no instalado"
    try:
        salida = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=20)
        return salida.stdout.splitlines()[0].strip()
    except Exception:
        return "desconocida"


# ---------------------------------------------------------------------------
# Preparar la imagen: enderezar, escalar y aumentar el contraste
# ---------------------------------------------------------------------------
def preparar(imagen):
    """Deja la foto en condiciones de ser leída: gris (sin perder el texto de color), derecha y con buen tamaño."""
    from PIL import Image, ImageChops, ImageOps

    im = ImageOps.exif_transpose(imagen)
    if im.mode in ("RGB", "RGBA", "P"):          # el canal más oscuro: el texto de color (naranja, azul) queda oscuro
        r, g, b = im.convert("RGB").split()
        im = ImageChops.darker(ImageChops.darker(r, g), b)
    else:
        im = im.convert("L")
    angulo = _inclinacion(im)
    if abs(angulo) > 0.3:
        im = im.rotate(angulo, resample=Image.BICUBIC, expand=True, fillcolor=255)
    lado = max(im.size)
    if lado < MIN_LADO:
        k = MIN_LADO / lado
        im = im.resize((round(im.width * k), round(im.height * k)), Image.LANCZOS)
    elif lado > MAX_LADO:
        k = MAX_LADO / lado
        im = im.resize((round(im.width * k), round(im.height * k)), Image.LANCZOS)
    return im


def _inclinacion(im) -> float:
    """Estima cuánto está torcido el papel probando varios ángulos (proyección de filas de texto)."""
    try:
        import numpy as np
    except ImportError:
        return 0.0
    from PIL import Image

    chica = im.resize((min(900, im.width), round(im.height * min(900, im.width) / im.width)), Image.BILINEAR)
    base = np.asarray(chica, dtype="float32")
    tinta = 255.0 - base
    tinta[tinta < 60] = 0.0
    mejor, mejor_a = -1.0, 0.0
    for a in [x / 2 for x in range(-10, 11)]:  # de -5° a +5° en pasos de medio grado
        rot = np.asarray(Image.fromarray(tinta).rotate(a, resample=Image.BILINEAR, fillcolor=0), dtype="float32")
        perfil = rot.sum(axis=1)
        puntaje = float(((perfil[1:] - perfil[:-1]) ** 2).sum())  # líneas de texto bien separadas
        if puntaje > mejor:
            mejor, mejor_a = puntaje, a
    return mejor_a


# ---------------------------------------------------------------------------
# OCR
# ---------------------------------------------------------------------------
def _tsv(im) -> list[dict[str, Any]]:
    """Corre Tesseract y devuelve las palabras con su confianza y su posición."""
    exe = _binario()
    if not exe:
        raise RuntimeError("Tesseract no está instalado.")
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    proc = subprocess.run([exe, "stdin", "stdout", "-l", IDIOMAS, "--psm", "3", "--oem", "1", "tsv"],
                          input=buf.getvalue(), capture_output=True, timeout=180)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", "replace")[:200])
    filas = []
    lineas = proc.stdout.decode("utf-8", "replace").splitlines()
    if not lineas:
        return filas
    cab = lineas[0].split("\t")
    for linea in lineas[1:]:
        c = linea.split("\t")
        if len(c) != len(cab):
            continue
        d = dict(zip(cab, c))
        texto = (d.get("text") or "").strip()
        if not texto:
            continue
        try:
            conf = float(d.get("conf", -1))
        except ValueError:
            conf = -1.0
        if conf < CONF_MINIMA_PALABRA:
            continue
        filas.append({"texto": texto, "conf": conf / 100.0, "linea": (d.get("page_num"), d.get("block_num"),
                                                                     d.get("par_num"), d.get("line_num")),
                      "top": int(d.get("top", 0)), "alto": int(d.get("height", 0))})
    return filas


def _texto_de(palabras: list[dict[str, Any]]) -> str:
    lineas: dict[tuple, list[str]] = {}
    for p in palabras:
        lineas.setdefault(p["linea"], []).append(p["texto"])
    return "\n".join(" ".join(v) for v in lineas.values())


def leer_imagen(datos: bytes) -> dict[str, Any]:
    """OCR de una imagen. Devuelve el texto, las palabras con su confianza y la confianza media."""
    from PIL import Image

    im = preparar(Image.open(io.BytesIO(datos)))
    palabras = _tsv(im)
    return _resultado(palabras, 1)


def leer_pdf(datos: bytes) -> dict[str, Any]:
    """OCR de un PDF escaneado: rasteriza cada página a 300 ppp y la lee."""
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(io.BytesIO(datos))
    palabras: list[dict[str, Any]] = []
    paginas = min(len(doc), MAX_PAGINAS)
    for i in range(paginas):
        im = doc[i].render(scale=PPP_PDF / 72).to_pil()
        palabras += _tsv(preparar(im))
    return _resultado(palabras, paginas)


def _resultado(palabras: list[dict[str, Any]], paginas: int) -> dict[str, Any]:
    confs = [p["conf"] for p in palabras]
    return {"texto": _texto_de(palabras), "palabras": palabras, "paginas": paginas,
            "confianza_media": round(sum(confs) / len(confs), 4) if confs else 0.0,
            "motor": f"Tesseract {version().split()[-1] if version()[0].isalpha() else version()} · {IDIOMAS}"}


# ---------------------------------------------------------------------------
# De texto a campos: reglas, sin IA
# ---------------------------------------------------------------------------
TIPOS = [
    ("nota_credito", r"nota\s+(de\s+)?cr[eé]dito|credit\s+note"),
    ("nota_debito", r"nota\s+(de\s+)?d[eé]bito|debit\s+note"),
    ("recibo_pago", r"recibo\s+de\s+caja|recibo\s+de\s+pago|comprobante\s+de\s+pago|payment\s+receipt|\brecibimos\s+de\b"),
    ("cuenta_cobro", r"cuenta\s+de\s+cobro"),
    ("documento_soporte", r"documento\s+soporte"),
    ("factura", r"factura\s+electr[oó]nica|factura\s+de\s+venta|\bfactura\b|\bfatura\b|\binvoice\b"),
]
# El total se busca por etiqueta, de la más específica a la más general: la primera que aparezca manda
ETIQUETAS_TOTAL = [
    (r"total\s+a\s+pagar|valor\s+a\s+pagar|neto\s+a\s+pagar|total\s+due|amount\s+due|balance\s+due", 1.00),
    (r"gran\s+total|total\s+factura|total\s+general|importe\s+total|monto\s+total|la\s+suma\s+de|\bvalor\s*:", 0.95),
    (r"\btotal\b", 0.80),
]
ETIQUETAS_NUM = (r"(?:factura|fatura|invoice|comprobante|recibo|documento|folio|serie)?\s*"
                 r"(?:electr[oó]nica\s*(?:de\s*venta)?)?\s*(?:n[.º°o]{1,2}|#|nro\.?|num\.?|number|folio)\s*[:\-]?\s*")
# Líneas que mencionan un número que NO es el de la factura
RUIDO_NUM = r"resoluci[oó]n|autorizaci[oó]n|rango|prefijo|cufe|uuid|\bcae\b|r[eé]gimen|actividad|nit|rfc|cuit|\bein\b|tel|celular"
# Dónde empieza el bloque del cliente: lo que viene después no es el emisor
ETIQUETAS_RECEPTOR = (r"adquiriente|adquirente|facturado\s+a|facturar\s+a|faturado\s+para|faturar\s+a|tomador|destinat[aá]rio|"
                      r"cliente|bill\s+to|sold\s+to|receptor|se[ñn]or\(?es\)?|recibimos\s+de")
SUFIJOS_EMPRESA = r"S\.?A\.?S\.?|S\.?A\.?|S\.?R\.?L\.?|S\.?C\.?|LLC|L\.?L\.?C|INC|LTDA|LTD|CORP|GMBH|E\.?U\.?|S\. de R\.L\."
# Identificaciones que nunca son del proveedor: genéricos del SAT para extranjeros
IDS_GENERICOS = {"XEXX010101000", "XAXX010101000"}
ETIQUETAS_EMISION = r"(fecha\s+de\s+emisi\w{1,3}|fecha\s+de\s+expedici\w{1,3}|data\s+de\s+emiss\w{1,3}|issue\s+date|\w?nvoice\s+date|\bfecha\b|(?<!due )\bdate\b)"
ETIQUETAS_VENCE = (r"(fecha\s+de\s+vencimiento|vence|vencimiento|vencimento|fecha\s+l[ií]mite(?:\s+de\s+pago)?|"
                   r"due\s+date|payment\s+due)")
MONEDAS = {"USD": r"\bUSD\b|\bUS\$|\bd[oó]lares\b", "COP": r"\bCOP\b|\bpesos\s+colombianos\b",
           "MXN": r"\bMXN\b|\bpesos\s+mexicanos\b", "ARS": r"\bARS\b|\bpesos\s+argentinos\b",
           "EUR": r"\bEUR\b|\beuros?\b|€", "BRL": r"\bBRL\b|\breais\b"}
RE_MONTO = r"[-+]?\$?\s?\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{1,2})?|\d+[.,]\d{2}"
RE_CUENTA = (r"(?:terminad[ao]\s+en|termina\s+en|terminaci[oó]n|ending\s+in|(?:conta|cuenta)[\w\s]{0,20}?\bfinal|"
             r"cuenta\s*(?:n[.º°o]*|#)?\s*[:\-]?\s*\*{0,4}|account\s*#?\s*)\s*\*?(\d{4,20})")


def _conf_de(palabras: list[dict[str, Any]], fragmento: str) -> float:
    """Confianza del OCR en las palabras que componen un dato leído."""
    if not palabras or not fragmento:
        return 0.0
    buscadas = [t for t in re.split(r"\s+", fragmento.strip()) if t]
    usadas = []
    for t in buscadas:
        limpio = re.sub(r"[^\wÁÉÍÓÚÑáéíóúñ.,:/-]", "", t)
        for p in palabras:
            if limpio and limpio in p["texto"]:
                usadas.append(p["conf"])
                break
    if not usadas:
        return 0.0
    return round(sum(usadas) / len(usadas), 4)


def _linea_con(texto: str, patron: str) -> str | None:
    for linea in texto.splitlines():
        if re.search(patron, linea, re.I):
            return linea
    return None


def _valor_tras(texto: str, patron: str, valor: str) -> str | None:
    """Busca «etiqueta … valor» en la misma línea y, si no, en la siguiente (facturas en dos columnas)."""
    lineas = texto.splitlines()
    for i, linea in enumerate(lineas):
        m = re.search(patron, linea, re.I)
        if not m:
            continue
        resto = linea[m.end():]
        v = re.search(valor, resto, re.I)
        if v:
            return v.group(0).strip()
        for j in (i + 1, i + 2):
            if j < len(lineas):
                v = re.search(valor, lineas[j], re.I)
                if v and not re.search(r"[a-zA-ZÁÉÍÓÚÑ]{4,}", lineas[j].split(v.group(0))[0] or ""):
                    return v.group(0).strip()
    return None


def tipo_documento(texto: str) -> tuple[str, float]:
    t = texto.lower()
    for tipo, patron in TIPOS:
        if re.search(patron, t, re.I):
            return tipo, 0.95 if tipo != "factura" else 0.97
    return "desconocido", 0.4


def _lineas(texto: str) -> list[str]:
    return [re.sub(r"\s{2,}", " ", l).strip() for l in texto.splitlines() if l.strip()]


def _bloque_receptor(lineas: list[str]) -> set[int]:
    """Marca las líneas que pertenecen al cliente, para no confundirlo con el proveedor."""
    marcadas: set[int] = set()
    for i, l in enumerate(lineas):
        if re.search(ETIQUETAS_RECEPTOR, l, re.I):
            marcadas.update(range(i, min(len(lineas), i + 4)))
    return marcadas


def _emitida_por_cliente(lineas: list[str], receptor: set[int], cliente: dict | None) -> bool:
    """El encabezado (quien emite) es la propia empresa y el documento va «facturado a» otro: es una factura de venta."""
    if not cliente or not receptor:
        return False
    id_c, clave = N.solo_digitos(cliente.get("id_fiscal")), N.clave_nombre(cliente.get("nombre") or "")
    cabeza = [linea for i, linea in enumerate(lineas[:4]) if i not in receptor]
    nombre_arriba = bool(clave) and any(clave in N.clave_nombre(linea) for linea in cabeza[:2])
    id_arriba = bool(id_c) and any(id_c in N.solo_digitos(linea) for linea in cabeza)
    return nombre_arriba and id_arriba


def _identificacion(lineas: list[str], receptor: set[int], pais_pista: str | None, cliente: dict | None = None):
    """Identificación fiscal del proveedor: la primera que no sea del cliente ni un genérico."""
    id_cliente = N.solo_digitos((cliente or {}).get("id_fiscal"))
    patrones = [("CO", r"\bNIT[.:\s]*(\d[\d.\s]{6,15}-?\s?\d?)"), ("CO", r"\bC\.?\s?C\.?[.:\s]*(\d[\d.\s]{5,15})"),
                ("MX", r"\bRFC[.:\s]*([A-ZÑ&]{3,4}\s?\d{6}\s?[A-Z0-9]{3})"), ("AR", r"\bCUIT[.:\s]*(\d{2}-?\d{8}-?\d)"),
                ("US", r"\bEIN[.:\s]*(\d{2}-?\d{7})"), ("BR", r"\bCNPJ[.:\s]*([\w./-]{14,20})"),
                ("ES", r"\bNIF[.:\s]*([A-Z]\d{7}[A-Z0-9]|\d{8}[A-Z])\b")]
    suplentes = []
    for i, linea in enumerate(lineas):
        for pais, patron in patrones:
            m = re.search(patron, linea, re.I)
            if not m:
                continue
            crudo = re.sub(r"\s+", "", m.group(0)).replace(":", "")
            etiqueta = re.match(r"(NIT|C\.?C\.?|RFC|CUIT|EIN|CNPJ|NIF)", crudo, re.I)
            valor = crudo[etiqueta.end():] if etiqueta else crudo
            texto_id = f"{etiqueta.group(0).upper()} {valor}" if etiqueta else crudo
            if N.solo_alnum(valor) in IDS_GENERICOS or (id_cliente and N.solo_digitos(valor) == id_cliente):
                continue                              # genérico del SAT o la identificación de la propia empresa
            if i in receptor:
                suplentes.append((texto_id, pais, i, m.group(0)))
                continue
            return texto_id, pais, i, m.group(0)
    if suplentes:  # solo hay identificaciones en el bloque del cliente: se usa, pero con menos confianza
        return suplentes[0]
    return None, pais_pista, None, None


def _nombre_emisor(lineas: list[str], receptor: set[int], idx_id: int | None, cliente: dict | None = None) -> str | None:
    """El nombre del proveedor: se puntúan las líneas candidatas y gana la mejor."""
    clave_cliente = N.clave_nombre((cliente or {}).get("nombre") or "")
    basura = r"@|https?:|www\.|factura|invoice|electr[oó]nica|de\s+venta|recibo|nota\s+de|documento|cuenta\s+de\s+cobro|" \
             r"resoluci[oó]n|r[eé]gimen|cfdi|versi[oó]n|timbrad|certificad|adquiriente|facturado|cliente|bill\s+to|" \
             r"fecha|moneda|forma\s+de\s+pago|medio\s+de\s+pago|subtotal|total|iva|direcci[oó]n|correo|tel|nit|rfc|cuit|ein|" \
             r"fatura|faturado|cnpj|vencimento|emiss[aã]o|debe\s+a\b|^(hola|hello|hi|buen[oa]s?|saludos|estimad[oa]s?|dear)\b"
    ciudades = r"^[A-ZÁÉÍÓÚÑ][\w\s]*,\s*(?:[A-Z]{2}|[A-ZÁÉÍÓÚÑ][\w\s]+)(?:,\s*[\w\s.]+)?$"
    mejor, puntaje_mejor = None, 0
    tope = min(len(lineas), 14)
    indices = list(range(tope)) + ([i for i in range(max(0, (idx_id or 0) - 4), (idx_id or 0) + 1) if i >= tope] if idx_id else [])
    titulos = r"(FACTURA\s+ELECTR[OÓ]NICA(\s+DE\s+VENTA)?|FACTURA\s+DE\s+VENTA|FACTURA|FATURA|INVOICE|CUENTA\s+DE\s+COBRO|RECIBO\s+DE\s+CAJA|NOTA\s+(DE\s+)?CR[EÉ]DITO)"
    for i in sorted(set(indices)):
        l = re.sub(titulos, " ", lineas[i], flags=re.I)          # el título del documento no es el nombre
        l = re.sub(r"\s{2,}", " ", l).strip(" .·-:|")
        if i in receptor or not (4 < len(l) < 70) or re.search(basura, l, re.I) or re.search(r"\d{3}", l):
            continue
        if clave_cliente and clave_cliente in N.clave_nombre(l):
            continue                                  # el nombre de la propia empresa
        if re.match(ciudades, l) and not re.search(SUFIJOS_EMPRESA, l, re.I):
            continue
        palabras_l = [w for w in re.split(r"\s+", l) if w]
        puntaje = 0
        if re.search(SUFIJOS_EMPRESA, l, re.I):
            puntaje += 5
        if 1 < len(palabras_l) <= 7 and sum(1 for w in palabras_l if w[:1].isupper()) >= max(2, len(palabras_l) - 1):
            puntaje += 3
        if i > 0 and re.search(r"\b(debe\s+a|p[aá]guese\s+a|pagar\s+a|a\s+favor\s+de)\s*:?\s*$", lineas[i - 1], re.I):
            puntaje += 5            # «DEBE A:» y en la línea siguiente, quien cobra (cuenta de cobro colombiana)
        if idx_id is not None and 0 < idx_id - i <= 3:
            puntaje += 3            # pegada a la identificación fiscal: casi siempre es la razón social
        elif i < 4:
            puntaje += 1            # encabezado del documento
        if puntaje > puntaje_mejor:
            mejor, puntaje_mejor = re.sub(r"\s*(FACTURA|FATURA|INVOICE).*$", "", l, flags=re.I).strip(), puntaje
    return mejor if puntaje_mejor >= 3 else None


def _total(lineas: list[str], pais: str | None):
    """Busca el total por etiqueta. Si no hay etiqueta clara, no inventa un número."""
    def montos(txt):
        salida = []
        for m in re.finditer(RE_MONTO, txt):
            crudo = m.group(0).strip()
            if not re.search(r"[.,]", crudo) and not re.search(r"(USD|COP|MXN|ARS|EUR|BRL|\$)\s*$", txt[:m.start()], re.I):
                continue  # un entero suelto (una cantidad, un consecutivo) no es un total
            v = N.normalizar_monto(crudo, pais)
            if v is not None and v > 0:
                salida.append((v, crudo))
        return salida

    mejores = []
    for patron, peso in ETIQUETAS_TOTAL:
        for i, linea in enumerate(lineas):
            m = re.search(patron, linea, re.I)
            if not m:
                continue
            cands = montos(linea[m.end():])
            if cands:
                mejores.append((peso, max(cands)[0], max(cands)[1]))
            elif i + 1 < len(lineas):
                cands = montos(lineas[i + 1])
                if cands:
                    mejores.append((peso * 0.9, max(cands)[0], max(cands)[1]))
        if mejores:
            break
    if not mejores:
        return None, None, 0.0
    peso, valor, crudo = max(mejores)
    return valor, crudo, peso


def _numero(lineas: list[str]) -> str | None:
    """
    Número del documento. Se recogen candidatos de todo el texto y se puntúan: la resolución de
    facturación, el rango autorizado, el CUFE y el CAE también traen números, y no son el de la factura.
    """
    texto = "\n".join(lineas)
    prefijos = {m.group(1).upper() for m in re.finditer(r"(?:prefijo|pref\.?|serie)\s*[:\-]?\s*([A-Z]{1,4})\b", texto, re.I)}
    cands: dict[str, int] = {}

    def anotar(valor: str, puntos: int, linea: str):
        v = valor.strip(" .·-").upper()
        if len(v) < 3 or not re.search(r"\d", v):
            return
        if re.search(r"SKU|^0000|^\d{4}-\d{4}$|^(?:SIM-)?OC-|^PO-", v) or len(v) > 24:
            return                                    # código de ítem, orden de compra, resolución o rango autorizado
        if re.search(r"cufe|uuid|cae\b|folio\s+fiscal|nit|rfc|cuit|\bein\b|orden\s+de\s+compra|pedido|purchase\s+order|"
                     r"centro\s+de\s+cust", linea, re.I) and not re.search(r"factura|fatura|invoice", linea[:linea.upper().find(v) + 1], re.I):
            return
        if re.fullmatch(r"[A-Z]{1,4}-\d{2,8}(?:-\d{1,8})?", v):
            puntos += 3
        if v.split("-")[0] in prefijos:
            puntos += 3
        cands[v] = max(cands.get(v, 0), puntos)

    for linea in lineas:
        for m in re.finditer(ETIQUETAS_NUM + r"([A-Z0-9][A-Z0-9/-]{2,24})", linea, re.I):
            antes = linea[max(0, m.start() - 26):m.start()]
            anotar(m.group(1), 4 if not re.search(r"rango|resoluci|prefijo", antes, re.I) else 2, linea)
        for m in re.finditer(r"\b(?:factura|fatura|invoice)\s+([A-Z]{1,5}-[A-Z0-9][A-Z0-9-]{1,22})\b", linea, re.I):
            anotar(m.group(1), 4, linea)              # «la factura SIM-2026-000035», sin «N.°»
        for m in re.finditer(r"\b([A-Z]{1,4}-\d{2,8}(?:-\d{1,8})?)\b", linea):
            anotar(m.group(1), 1, linea)
    # formatos compuestos: «Serie TM Folio 455» (México) y «Punto de venta 0003 · Comp. N.° 00000077» (Argentina)
    m = re.search(r"serie\s*[:\-]?\s*([A-Z]{1,4})\b.{0,40}?folio\s*[:\-]?\s*(\d{1,10})\b", texto, re.I | re.S)
    if m:
        cands[f"{m.group(1).upper()}-{m.group(2)}"] = 8
    m = re.search(r"punto\s+de\s+venta\s*[:\-]?\s*(\d{3,5})\b.{0,60}?comp\.?\s*n[.º°o]{0,2}\s*[:\-]?\s*(\d{6,10})\b",
                  texto, re.I | re.S)
    if m:
        cands[f"{m.group(1)}-{m.group(2)}"] = 8
    if not cands:
        return None
    return max(cands.items(), key=lambda kv: (kv[1], len(kv[0])))[0]


def campos_desde_texto(texto: str, palabras: list[dict[str, Any]] | None = None,
                       pais_pista: str | None = None, cliente: dict | None = None) -> dict[str, Any]:
    """
    Convierte el texto reconocido en los campos de una factura, con su confianza. Sin IA.
    Con OCR, la confianza de cada campo es la del OCR en esas palabras. Con texto digital (PDF con texto, chat o
    correo), las letras son exactas: la confianza es la de la interpretación (etiqueta clara, alta; deducido, menor).
    """
    palabras = palabras or []
    digital = not palabras

    def conf_de(fragmento, base):
        if not fragmento:
            return 0.0
        return base if digital else _conf_de(palabras, fragmento)

    lineas = _lineas(texto)
    receptor = _bloque_receptor(lineas)
    alertas: list[str] = []

    id_fiscal, pais, idx_id, crudo_id = _identificacion(lineas, receptor, pais_pista, cliente)
    conf_id = conf_de(crudo_id, 0.95)
    if id_fiscal and idx_id in receptor:
        conf_id *= 0.6
        alertas.append("identificacion_dudosa")

    nombre = _nombre_emisor(lineas, receptor, idx_id, cliente)
    conf_nombre = conf_de(nombre, 0.9 if re.search(SUFIJOS_EMPRESA, nombre or "", re.I) or idx_id is not None else 0.8)

    tipo, conf_tipo = tipo_documento(texto)
    if _emitida_por_cliente(lineas, receptor, cliente):          # la emitió la propia empresa: es por cobrar
        tipo, conf_tipo = "por_cobrar", 0.95
        alertas.append("emitida_por_la_empresa")
    numero = _numero(lineas)
    conf_num = conf_de(numero, 0.92)

    moneda, conf_mon = None, 0.0
    for cod, patron in MONEDAS.items():
        if re.search(patron, texto, re.I):
            moneda, conf_mon = cod, (0.95 if digital else _conf_de(palabras, cod) or 0.8)
            break
    if not moneda and "$" in texto:
        moneda, conf_mon = N.normalizar_moneda("$", pais), 0.5

    monto, crudo_monto, peso = _total(lineas, pais)
    conf_monto = round(((0.97 if digital else _conf_de(palabras, crudo_monto)) or 0.75) * peso, 4) if monto is not None else 0.0
    if monto is None:
        alertas.append("sin_total_legible")

    def fecha(patron):
        v = _valor_tras(texto, patron, r"\d{4}-\d{2}-\d{2}|\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}|"
                                       r"\d{1,2}\s+de\s+[a-záéíóú]{4,10}\s+(?:del?\s+)?\d{4}|"     # 9 de octubre de 2026
                                       r"[A-Z][a-z]{2,8}\.?\s+\d{1,2},?\s+\d{4}")                  # Oct 14, 2026
        if not v:
            return None, 0.0
        # «28/10/2026» con un EIN no puede ser mes/día: si un orden es imposible, vale el otro
        return N.normalizar_fecha(v, pais) or N.normalizar_fecha(v, "US" if pais != "US" else "CO"), conf_de(v, 0.92)

    emision, _ = fecha(ETIQUETAS_EMISION)
    vence, conf_vence = fecha(ETIQUETAS_VENCE)

    cuenta = None
    m = re.search(RE_CUENTA, texto, re.I)
    if m:
        cuenta = m.group(1)[-4:]

    horas = None
    m = re.search(r"(\d{1,3}(?:[.,]\d{1,2})?)\s*(?:horas|hrs?\.?|hours)\b", texto, re.I)
    if m:
        h = N.normalizar_monto(m.group(1), pais)
        horas = float(h) if h is not None else None

    if len(texto) < 120:
        alertas.append("texto_insuficiente")

    conf = {"beneficiario": conf_nombre, "id_fiscal": conf_id, "numero_factura": conf_num,
            "moneda": conf_mon, "monto": conf_monto, "fecha_vencimiento": conf_vence}
    return {
        "tipo_documento": tipo,
        "beneficiario": {"nombre": nombre, "id_fiscal": id_fiscal, "pais": pais},
        "contacto": None,
        "numero_factura": numero,
        "fecha_emision": emision,
        "fecha_vencimiento": vence,
        "moneda": moneda,
        "monto": float(monto) if monto is not None else None,
        "horas": horas,
        "concepto": None,
        "cuenta_destino": cuenta,
        "confianza": {k: round(min(1.0, v), 4) for k, v in conf.items()},
        "alertas": alertas,
        "confianza_tipo": conf_tipo,
    }


def leer(nombre: str, datos: bytes, texto_incrustado: str = "", cliente: dict | None = None) -> dict[str, Any] | None:
    """
    Lee un documento con OCR (o con el texto que el PDF ya trae) y devuelve los campos.
    Devuelve None si no hay nada legible o si Tesseract no está instalado.
    """
    ext = nombre.lower().rsplit(".", 1)[-1] if "." in nombre else ""
    usa_ocr = False
    if texto_incrustado and len(texto_incrustado.strip()) >= 200:
        texto, palabras, paginas, motor = texto_incrustado, [], 1, "texto incrustado del PDF (sin OCR)"
    elif not disponible():
        return None
    else:
        usa_ocr = True
        if ext == "pdf" or datos[:5] == b"%PDF-":
            r = leer_pdf(datos)
        elif ext in ("png", "jpg", "jpeg", "webp", "tif", "tiff") or datos[:4] in (b"\x89PNG", b"\xff\xd8\xff\xe0"):
            r = leer_imagen(datos)
        else:
            return None
        texto, palabras, paginas, motor = r["texto"], r["palabras"], r["paginas"], r["motor"]
    if not texto.strip():
        return None
    campos = campos_desde_texto(texto, palabras, cliente=cliente)
    campos["metodo_lectura"] = "ocr" if usa_ocr else "texto_pdf"
    campos["ocr"] = {"motor": motor, "paginas": paginas, "palabras": len(palabras),
                     "confianza_media": round(sum(p["conf"] for p in palabras) / len(palabras), 4) if palabras else None,
                     "caracteres": len(texto)}
    campos["_texto"] = texto
    campos["_palabras"] = [{"texto": w["texto"], "conf": round(w["conf"], 3), "linea": "-".join(map(str, w["linea"]))}
                           for w in palabras[:3000]]
    return campos
