"""
Kauta · Normalización y validación de facturas.

Todo formato de entrada (PDF leído por IA, CFDI de México, factura electrónica DIAN de Colombia,
Factura E de Argentina, invoice de EE. UU., correo o chat) se convierte en una FACTURA CANÓNICA
única ("kauta-factura/2"), con:

  * fechas ISO 8601, monedas ISO 4217, países ISO 3166-1 alfa-2 y montos decimales exactos;
  * identificaciones fiscales limpias y validadas con su dígito de verificación;
  * datos bancarios validados por riel (ABA, CLABE, CBU, IBAN, SWIFT, Pix, Bre-B);
  * una clave de deduplicación estable.

Algoritmos de verificación implementados (sin dependencias externas):
  NIT (CO) · CUIT/CUIL (AR) · RFC (MX) · CNPJ alfanumérico 2026 y CPF (BR) · RUT (CL) · RUC (PE)
  EIN (US, formato) · ABA routing (US) · CLABE (MX) · CBU/CVU (AR) · IBAN (ISO 13616) · BIC (ISO 9362)
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

VERSION_CANONICA = "kauta-factura/2"

# ---------------------------------------------------------------------------
# Resultado de una validación
# ---------------------------------------------------------------------------
@dataclass
class Validacion:
    tipo: str
    valor: str            # normalizado (sin puntos, guiones ni espacios)
    valido: bool | None   # None = no se puede verificar (sin dígito o tipo desconocido)
    detalle: str

    def a_dict(self) -> dict[str, Any]:
        return asdict(self)


def solo_alnum(s: str | None) -> str:
    return re.sub(r"[^0-9A-Za-zÑñ&]", "", s or "").upper()


def solo_digitos(s: str | None) -> str:
    return re.sub(r"\D", "", s or "")


# ---------------------------------------------------------------------------
# Identificaciones fiscales
# ---------------------------------------------------------------------------
PESOS_NIT = (3, 7, 13, 17, 19, 23, 29, 37, 41, 43, 47, 53, 59, 67, 71)


def dv_nit(base: str) -> str:
    """Dígito de verificación del NIT colombiano (DIAN): primos de derecha a izquierda, módulo 11."""
    suma = sum(int(d) * p for d, p in zip(reversed(base), PESOS_NIT))
    r = suma % 11
    return str(r if r in (0, 1) else 11 - r)


def validar_nit(valor: str) -> Validacion:
    s = solo_digitos(valor)
    if not 6 <= len(s) <= 16:
        return Validacion("NIT", s, False, "Un NIT tiene entre 6 y 15 dígitos más el dígito de verificación.")
    if "-" in (valor or "") or len(s) >= 10:
        base, dv = s[:-1], s[-1]
        esperado = dv_nit(base)
        if dv == esperado:
            return Validacion("NIT", f"{base}-{dv}", True, "Dígito de verificación correcto.")
        return Validacion("NIT", f"{base}-{dv}", False, f"El dígito de verificación debería ser {esperado}, no {dv}.")
    return Validacion("NIT", s, None, "Sin dígito de verificación: no se puede comprobar.")


def validar_cc(valor: str) -> Validacion:
    s = solo_digitos(valor)
    ok = 5 <= len(s) <= 10
    return Validacion("CC", s, ok if ok else False, "Cédula colombiana: no tiene dígito de verificación." if ok
                      else "Una cédula tiene entre 5 y 10 dígitos.")


def dv_cuit(base10: str) -> str:
    pesos = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)
    r = (11 - sum(int(d) * p for d, p in zip(base10, pesos)) % 11) % 11
    return "9" if r == 10 else str(r)  # misma convención que ARCA/stdnum para el caso 10


def validar_cuit(valor: str) -> Validacion:
    s = solo_digitos(valor)
    if len(s) != 11:
        return Validacion("CUIT", s, False, "El CUIT tiene 11 dígitos (NN-NNNNNNNN-N).")
    if s[:2] not in ("20", "23", "24", "25", "26", "27", "30", "33", "34", "50", "51", "55"):
        return Validacion("CUIT", s, False, f"El prefijo {s[:2]} no corresponde a un tipo de CUIT.")
    esperado = dv_cuit(s[:10])
    if s[-1] == esperado:
        return Validacion("CUIT", f"{s[:2]}-{s[2:10]}-{s[10]}", True, "Dígito verificador correcto.")
    return Validacion("CUIT", s, False, f"El dígito verificador debería ser {esperado}, no {s[-1]}.")


_RFC_ALFABETO = "0123456789ABCDEFGHIJKLMN&OPQRSTUVWXYZ Ñ"
RFC_GENERICOS = {"XEXX010101000": "Residente en el extranjero", "XAXX010101000": "Público en general"}


def dv_rfc(base: str) -> str:
    """Dígito verificador del RFC (homoclave, SAT). base = RFC sin el último carácter (11 o 12)."""
    b = base.rjust(12)  # las personas morales (11) se completan con un espacio a la izquierda
    suma = sum(_RFC_ALFABETO.index(c) * (13 - i) for i, c in enumerate(b))
    r = (11 - suma % 11) % 11
    return "A" if r == 10 else str(r)


def validar_rfc(valor: str) -> Validacion:
    s = solo_alnum(valor)
    if s in RFC_GENERICOS:
        return Validacion("RFC", s, True, f"RFC genérico SAT: {RFC_GENERICOS[s]}.")
    m = re.fullmatch(r"([A-ZÑ&]{3,4})(\d{2})(\d{2})(\d{2})([A-Z0-9]{2})([0-9A])", s)
    if not m:
        return Validacion("RFC", s, False, "Formato inválido: 3 o 4 letras, fecha AAMMDD y homoclave de 3 caracteres.")
    if not re.fullmatch(r"[1-9A-V][1-9A-Z]", m.group(5)):
        # la homoclave sale de una tabla del SAT: el primer carácter nunca pasa de la V y ninguno es 0
        return Validacion("RFC", s, False, f"La homoclave {m.group(5)} no puede existir en un RFC emitido por el SAT.")
    _, aa, mm, dd, _, _ = m.groups()
    try:
        date(2000 + int(aa), int(mm), int(dd))
    except ValueError:
        return Validacion("RFC", s, False, f"La fecha {aa}{mm}{dd} del RFC no existe.")
    esperado = dv_rfc(s[:-1])
    if s[-1] == esperado:
        tipo = "persona moral" if len(s) == 12 else "persona física"
        return Validacion("RFC", s, True, f"RFC de {tipo} con dígito verificador correcto.")
    return Validacion("RFC", s, False, f"El dígito verificador debería ser {esperado}, no {s[-1]}.")


def _dv_cnpj(cuerpo: str, pesos: tuple[int, ...]) -> str:
    suma = sum((ord(c) - 48) * p for c, p in zip(cuerpo, pesos))
    r = suma % 11
    return "0" if r < 2 else str(11 - r)


def validar_cnpj(valor: str) -> Validacion:
    """CNPJ numérico y alfanumérico (IN RFB 2.229/2024, vigente desde julio de 2026)."""
    s = re.sub(r"[^0-9A-Za-z]", "", valor or "").upper()
    if not re.fullmatch(r"[0-9A-Z]{12}\d{2}", s):
        return Validacion("CNPJ", s, False, "El CNPJ tiene 12 caracteres alfanuméricos y 2 dígitos verificadores.")
    d1 = _dv_cnpj(s[:12], (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2))
    d2 = _dv_cnpj(s[:12] + d1, (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2))
    if s[12:] == d1 + d2:
        return Validacion("CNPJ", s, True, "Dígitos verificadores correctos" + (" (formato alfanumérico)." if re.search("[A-Z]", s) else "."))
    return Validacion("CNPJ", s, False, f"Los dígitos verificadores deberían ser {d1}{d2}, no {s[12:]}.")


def validar_cpf(valor: str) -> Validacion:
    s = solo_digitos(valor)
    if len(s) != 11 or len(set(s)) == 1:
        return Validacion("CPF", s, False, "El CPF tiene 11 dígitos y no puede repetir un solo dígito.")
    def dv(cuerpo: str) -> str:
        n = len(cuerpo) + 1
        r = sum(int(c) * (n - i) for i, c in enumerate(cuerpo)) * 10 % 11
        return "0" if r == 10 else str(r)
    d1 = dv(s[:9]); d2 = dv(s[:9] + d1)
    ok = s[9:] == d1 + d2
    return Validacion("CPF", s, ok, "Dígitos verificadores correctos." if ok else f"Deberían ser {d1}{d2}.")


def validar_rut(valor: str) -> Validacion:
    s = re.sub(r"[^0-9Kk]", "", valor or "").upper()
    if not 2 <= len(s) <= 9:
        return Validacion("RUT", s, False, "Formato de RUT inválido.")
    cuerpo, dv = s[:-1], s[-1]
    suma = sum(int(d) * p for d, p in zip(reversed(cuerpo), [2, 3, 4, 5, 6, 7] * 2))
    r = 11 - suma % 11
    esperado = "0" if r == 11 else "K" if r == 10 else str(r)
    ok = dv == esperado
    return Validacion("RUT", f"{cuerpo}-{dv}", ok, "Dígito verificador correcto." if ok else f"El DV debería ser {esperado}.")


def validar_ruc(valor: str) -> Validacion:
    s = solo_digitos(valor)
    if len(s) != 11 or s[:2] not in ("10", "15", "16", "17", "20"):
        return Validacion("RUC", s, False, "El RUC tiene 11 dígitos y empieza por 10, 15, 16, 17 o 20.")
    pesos = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)
    esperado = str((11 - sum(int(d) * p for d, p in zip(s, pesos)) % 11) % 10)
    ok = s[-1] == esperado
    return Validacion("RUC", s, ok, "Dígito verificador correcto." if ok else f"El dígito debería ser {esperado}.")


def validar_ein(valor: str) -> Validacion:
    s = solo_digitos(valor)
    if len(s) != 9:
        return Validacion("EIN", s, False, "El EIN tiene 9 dígitos (NN-NNNNNNN).")
    if s[:2] in ("00", "07", "08", "09", "17", "18", "19", "28", "29", "49", "69", "70", "78", "79", "89", "96", "97"):
        return Validacion("EIN", f"{s[:2]}-{s[2:]}", False, f"El prefijo {s[:2]} no lo asigna el IRS.")
    return Validacion("EIN", f"{s[:2]}-{s[2:]}", None, "Formato correcto. El EIN no tiene dígito de verificación; "
                      "se confirma con el formulario W-9 o W-8BEN-E.")


VALIDADORES_FISCALES = {"NIT": validar_nit, "CC": validar_cc, "CUIT": validar_cuit, "CUIL": validar_cuit,
                        "RFC": validar_rfc, "CNPJ": validar_cnpj, "CPF": validar_cpf, "RUT": validar_rut,
                        "RUC": validar_ruc, "EIN": validar_ein}


def tipo_id_fiscal(texto: str | None, pais: str | None = None) -> str | None:
    """Deduce el tipo de identificación por su prefijo escrito o por el país."""
    t = (texto or "").upper()
    for tipo in ("NIT", "CUIT", "CUIL", "RFC", "CNPJ", "CPF", "RUT", "RUC", "EIN"):
        if re.search(rf"\b{tipo}\b", t):
            return tipo
    if re.search(r"\bC\.?\s?C\.?\b", t):
        return "CC"
    s = solo_alnum(texto)
    por_pais = {"CO": "NIT", "AR": "CUIT", "MX": "RFC", "BR": "CNPJ" if len(s) == 14 else "CPF",
                "CL": "RUT", "PE": "RUC", "US": "EIN"}
    return por_pais.get((pais or "").upper())


def validar_id_fiscal(texto: str | None, pais: str | None = None) -> Validacion:
    if not texto:
        return Validacion("?", "", None, "Sin identificación fiscal.")
    tipo = tipo_id_fiscal(texto, pais)
    sin_prefijo = re.sub(r"^\s*(NIT|C\.?\s?C\.?|RFC|CUIT|CUIL|CNPJ|CPF|RUT|RUC|EIN)\s*[:.]?\s*", "", texto, flags=re.I)
    if tipo in VALIDADORES_FISCALES:
        return VALIDADORES_FISCALES[tipo](sin_prefijo)
    return Validacion(tipo or "?", solo_alnum(texto), None, "Tipo de identificación no reconocido.")


# ---------------------------------------------------------------------------
# Datos bancarios por riel de pago
# ---------------------------------------------------------------------------
def validar_aba(valor: str) -> Validacion:
    s = solo_digitos(valor)
    if len(s) != 9:
        return Validacion("ABA", s, False, "El routing number (ABA) tiene 9 dígitos.")
    ok = sum(int(d) * p for d, p in zip(s, (3, 7, 1) * 3)) % 10 == 0
    return Validacion("ABA", s, ok, "Suma de control correcta (pesos 3-7-1)." if ok else "La suma de control no da múltiplo de 10.")


def validar_clabe(valor: str) -> Validacion:
    s = solo_digitos(valor)
    if len(s) != 18:
        return Validacion("CLABE", s, False, "La CLABE tiene 18 dígitos: banco (3), plaza (3), cuenta (11) y control (1).")
    suma = sum((int(d) * p) % 10 for d, p in zip(s[:17], (3, 7, 1) * 6))
    esperado = str((10 - suma % 10) % 10)
    ok = s[-1] == esperado
    return Validacion("CLABE", s, ok, f"Dígito de control correcto (banco {s[:3]})." if ok else f"El dígito de control debería ser {esperado}.")


def validar_cbu(valor: str) -> Validacion:
    s = solo_digitos(valor)
    if len(s) != 22:
        return Validacion("CBU", s, False, "El CBU/CVU tiene 22 dígitos en dos bloques.")
    def dv(bloque: str, pesos: tuple[int, ...]) -> str:
        return str((10 - sum(int(d) * p for d, p in zip(bloque, pesos)) % 10) % 10)
    d1 = dv(s[:7], (7, 1, 3, 9, 7, 1, 3)); d2 = dv(s[8:21], (3, 9, 7, 1, 3, 9, 7, 1, 3, 9, 7, 1, 3))
    ok = s[7] == d1 and s[21] == d2
    tipo = "CVU (billetera virtual)" if s.startswith("000") else "CBU"
    return Validacion("CBU", s, ok, f"{tipo} con dígitos verificadores correctos." if ok else f"Deberían ser {d1} y {d2}.")


# Estructura del BBAN por país según el registro IBAN de SWIFT (ISO 13616): n = dígitos, a = letras, c = alfanumérico.
_IBAN_ESTRUCTURAS = (
    "AD:4!n4!n12!c AE:3!n16!n AL:8!n16!c AT:5!n11!n AZ:4!a20!c BA:3!n3!n8!n2!n BE:3!n7!n2!n BG:4!a4!n2!n8!c "
    "BH:4!a14!c BI:5!n5!n11!n2!n BR:8!n5!n10!n1!a1!c BY:4!c4!n16!c CH:5!n12!c CR:4!n14!n CY:3!n5!n16!c "
    "CZ:4!n16!n DE:8!n10!n DJ:5!n5!n11!n2!n DK:4!n9!n1!n DO:4!c20!n EE:2!n14!n EG:4!n4!n17!n "
    "ES:4!n4!n1!n1!n10!n FI:3!n11!n FK:2!a12!n FO:4!n9!n1!n FR:5!n5!n11!c2!n GB:4!a6!n8!n GE:2!a16!n "
    "GI:4!a15!c GL:4!n9!n1!n GR:3!n4!n16!c GT:4!c20!c HN:4!a20!n HR:7!n10!n HU:3!n4!n1!n15!n1!n IE:4!a6!n8!n "
    "IL:3!n3!n13!n IQ:4!a3!n12!n IS:4!n2!n6!n10!n IT:1!a5!n5!n12!c JO:4!a4!n18!c KW:4!a22!c KZ:3!n13!c "
    "LB:4!n20!c LC:4!a24!c LI:5!n12!c LT:5!n11!n LU:3!n13!c LV:4!a13!c LY:3!n3!n15!n MC:5!n5!n11!c2!n "
    "MD:2!c18!c ME:3!n13!n2!n MK:3!n10!c2!n MN:4!n12!n MR:5!n5!n11!n2!n MT:4!a5!n18!c MU:4!a2!n2!n12!n3!n3!a "
    "NI:4!a20!n NL:4!a10!n NO:4!n6!n1!n OM:3!n16!c PK:4!a16!c PL:8!n16!n PS:4!a21!c PT:4!n4!n11!n2!n "
    "QA:4!a21!c RO:4!a16!c RS:3!n13!n2!n RU:9!n5!n15!c SA:2!n18!c SC:4!a2!n2!n16!n3!a SD:2!n12!n "
    "SE:3!n16!n1!n SI:5!n8!n2!n SK:4!n6!n10!n SM:1!a5!n5!n12!c SO:4!n3!n12!n ST:4!n4!n11!n2!n SV:4!a20!n "
    "TL:3!n14!n2!n TN:2!n3!n13!n2!n TR:5!n1!n16!c UA:6!n19!c VA:3!n15!n VG:4!a16!n XK:4!n10!n2!n "
    "YE:4!a4!n18!c "
)
IBAN_ESTRUCTURA: dict[str, str] = dict(t.split(":") for t in _IBAN_ESTRUCTURAS.split())


def _bban_regex(estructura: str) -> str:
    clases = {"n": "[0-9]", "a": "[A-Z]", "c": "[A-Z0-9]"}
    return "".join(f"{clases[t]}{{{n}}}" for n, t in re.findall(r"(\d+)!([nac])", estructura))


def _dv_ccc(digitos: str) -> str:
    """Dígito de control del CCC español (pesos 2^i módulo 11)."""
    r = sum(int(c) * 2 ** i for i, c in enumerate(digitos)) % 11
    return str(r if r < 2 else 11 - r)


def validar_iban(valor: str) -> Validacion:
    s = re.sub(r"[\s.-]", "", valor or "").upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}", s):
        return Validacion("IBAN", s, False, "Formato IBAN inválido.")
    estructura = IBAN_ESTRUCTURA.get(s[:2])
    if not estructura:
        return Validacion("IBAN", s, False, f"{s[:2]} no usa IBAN según el registro de SWIFT.")
    if not re.fullmatch(_bban_regex(estructura), s[4:]):
        largo = 4 + sum(int(n) for n in re.findall(r"(\d+)!", estructura))
        return Validacion("IBAN", s, False, f"Un IBAN de {s[:2]} tiene {largo} caracteres con la estructura {estructura}.")
    num = "".join(str(int(c, 36)) for c in s[4:] + s[:4])
    if int(num) % 97 != 1:
        return Validacion("IBAN", s, False, "El control módulo 97 no cuadra.")
    if s[:2] == "ES":  # control nacional: los dos dígitos del CCC (entidad, oficina y cuenta)
        ccc = s[4:]
        esperado = _dv_ccc("00" + ccc[:8]) + _dv_ccc(ccc[10:])
        if ccc[8:10] != esperado:
            return Validacion("IBAN", s, False, f"Los dígitos de control de la cuenta española deberían ser {esperado}.")
    return Validacion("IBAN", s, True, "Control ISO 13616 (módulo 97) y estructura del país correctos.")


def validar_bic(valor: str) -> Validacion:
    s = re.sub(r"\s", "", valor or "").upper()
    ok = bool(re.fullmatch(r"[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}([A-Z0-9]{3})?", s))
    return Validacion("BIC", s, ok, "Formato SWIFT/BIC (ISO 9362) correcto." if ok else "Formato SWIFT/BIC inválido.")


def tipo_llave_pix(valor: str) -> str:
    v = (valor or "").strip()
    if re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", v):
        return "aleatoria (EVP)"
    if "@" in v:
        return "correo"
    if v.startswith("+55"):
        return "teléfono"
    d = solo_digitos(v)
    return "CPF" if len(d) == 11 else "CNPJ" if len(d) == 14 else "desconocida"


def tipo_llave_breb(valor: str) -> str:
    v = (valor or "").strip()
    if v.startswith("@"):
        return "alfanumérica"
    if "@" in v:
        return "correo"
    d = solo_digitos(v)
    if len(d) == 10 and d.startswith("3"):
        return "celular"
    return "documento" if d else "desconocida"


RIELES = {
    "US": ("ACH o wire (Fedwire)", "routing ABA de 9 dígitos + número de cuenta; SWIFT/BIC si es internacional"),
    "MX": ("SPEI", "CLABE de 18 dígitos"),
    "CO": ("Bre-B o transferencia ACH local", "llave Bre-B (celular, documento, correo o alfanumérica) o banco + tipo + número de cuenta"),
    "BR": ("Pix", "chave Pix (CPF, CNPJ, teléfono, correo o aleatoria)"),
    "AR": ("Transferencia inmediata", "CBU o CVU de 22 dígitos, o alias"),
}


# ---------------------------------------------------------------------------
# Montos, fechas, monedas y textos
# ---------------------------------------------------------------------------
DECIMALES_MONEDA = {"USD": 2, "COP": 2, "MXN": 2, "BRL": 2, "ARS": 2, "CLP": 0, "PEN": 2, "EUR": 2}
MONEDA_LOCAL = {"US": "USD", "CO": "COP", "MX": "MXN", "BR": "BRL", "AR": "ARS", "CL": "CLP", "PE": "PEN"}


CODIGOS_ARCA = {"PES": "ARS", "DOL": "USD", "060": "EUR", "012": "BRL"}


def normalizar_moneda(texto: str | None, pais: str | None = None) -> str | None:
    """'US$', 'Dólar estadounidense', 'DOL' (ARCA) → USD. 'Pesos' y '$' solo se resuelven con el país."""
    if not texto:
        return None
    if "€" in texto:
        return "EUR"
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().upper().strip()
    if t in CODIGOS_ARCA:
        return CODIGOS_ARCA[t]
    if re.fullmatch(r"[A-Z]{3}", t):
        return t
    m = re.search(r"\b(USD|COP|MXN|BRL|ARS|CLP|PEN|EUR|CAD|GBP)\b", t)
    if m:
        return m.group(1)
    if re.search(r"US\$|U\$S|DOLAR", t):
        return "USD"
    if "R$" in t or "REAL" in t:
        return "BRL"
    if ("PESO" in t or "$" in t or "M.N." in t or "M/CTE" in t) and pais:
        return MONEDA_LOCAL.get(pais.upper())
    return None


def normalizar_monto(texto: Any, pais: str | None = None) -> Decimal | None:
    """Convierte '2.400,00' (LatAm), '1,800.00' (EE. UU.), '$7.680.000' o 27600 en Decimal exacto."""
    if texto is None or isinstance(texto, bool):
        return None
    if isinstance(texto, (int, float, Decimal)):
        return Decimal(str(texto))
    s = re.sub(r"[^\d,.\-]", "", str(texto))
    if not s or not re.search(r"\d", s):
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        partes = s.split(",")
        s = s.replace(",", ".") if len(partes) == 2 and len(partes[1]) != 3 else s.replace(",", "")
    elif s.count(".") > 1:
        s = s.replace(".", "")
    elif "." in s and len(s.split(".")[-1]) == 3 and (pais or "").upper() in ("CO", "AR", "BR", "CL"):
        s = s.replace(".", "")  # 2.400 en LatAm = dos mil cuatrocientos
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


MESES = {m: i for i, m in enumerate(["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"], 1)}
MESES.update({m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)})


def normalizar_fecha(texto: Any, pais: str | None = None) -> str | None:
    """Devuelve AAAA-MM-DD. En EE. UU. 10/01/2026 es 1 de octubre; en LatAm es 10 de enero."""
    if texto is None:
        return None
    if isinstance(texto, (date, datetime)):
        return texto.strftime("%Y-%m-%d")
    t = str(texto).strip().lower()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", t)
    if m:
        return f"{m[1]}-{m[2]}-{m[3]}"
    m = re.match(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})", t)
    if m:
        a, b, y = int(m[1]), int(m[2]), int(m[3])
        y = y + 2000 if y < 100 else y
        mes, dia = (a, b) if (pais or "").upper() == "US" else (b, a)
        try:
            return date(y, mes, dia).isoformat()
        except ValueError:
            return None
    m = re.match(r"([a-z]{3})[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})", t)           # Oct 1, 2026
    if m and m[1] in MESES:
        return date(int(m[3]), MESES[m[1]], int(m[2])).isoformat()
    m = re.match(r"(\d{1,2})\s+de\s+([a-z]{3})[a-z]*\.?\s+de\s+(\d{4})", t)  # 1 de octubre de 2026
    if m and m[2] in MESES:
        return date(int(m[3]), MESES[m[2]], int(m[1])).isoformat()
    return None


SUFIJOS_LEGALES = r"\b(S\s?A\s?S|S\s?A|S\s?R\s?L|S\s?C|S\s?DE\s?R\s?L|LLC|INC|CORP|LTDA|LTD|SPA|EIRL|SAC|ME|EPP)\b"


def clave_nombre(nombre: str | None) -> str:
    """Nombre comparable: sin tildes, sin puntuación y sin sufijo societario (S.A.S., LLC, S. de R.L.…)."""
    t = unicodedata.normalize("NFKD", nombre or "").encode("ascii", "ignore").decode().upper()
    t = re.sub(r"[.,]", "", t)
    t = re.sub(SUFIJOS_LEGALES, "", t)
    return re.sub(r"[^A-Z0-9]", "", t)


def clave_numero(numero: str | None) -> str:
    return re.sub(r"[^0-9A-Z]", "", (numero or "").upper())


# ---------------------------------------------------------------------------
# Factura canónica
# ---------------------------------------------------------------------------
TIPOS_DOCUMENTO = ("factura", "nota_credito", "nota_debito", "cuenta_cobro", "documento_soporte", "recibo_pago", "otro")


@dataclass
class Parte:
    nombre: str | None = None
    id_fiscal: str | None = None
    tipo_id: str | None = None
    id_valido: bool | None = None
    pais: str | None = None
    correo: str | None = None


@dataclass
class Impuesto:
    tipo: str                 # IVA, INC, ICA, ISR, IVA_RET, IIBB...
    tasa: Decimal | None
    base: Decimal | None
    monto: Decimal
    retencion: bool = False


@dataclass
class Linea:
    descripcion: str
    cantidad: Decimal = Decimal("1")
    unidad: str | None = None
    precio_unitario: Decimal | None = None
    total: Decimal | None = None
    codigo: str | None = None


@dataclass
class FacturaCanonica:
    version: str = VERSION_CANONICA
    tipo: str = "factura"
    numero: str | None = None
    fecha_emision: str | None = None
    fecha_vencimiento: str | None = None
    moneda: str | None = None
    emisor: Parte = field(default_factory=Parte)
    receptor: Parte = field(default_factory=Parte)
    lineas: list[Linea] = field(default_factory=list)
    impuestos: list[Impuesto] = field(default_factory=list)
    subtotal: Decimal | None = None
    total: Decimal | None = None
    total_a_pagar: Decimal | None = None
    tasa_cambio: Decimal | None = None
    metodo_pago: str | None = None         # PUE/PPD (MX), contado/crédito (CO)
    cuenta_destino: str | None = None      # últimos 4 dígitos
    id_fiscal_unico: str | None = None     # CUFE, UUID del CFDI, CAE, chave NFS-e...
    tipo_id_unico: str | None = None
    documento_relacionado: str | None = None
    orden_compra: str | None = None
    horas: Decimal | None = None
    metodo_lectura: str = "ia"             # xml_fiscal | ia | referencia
    confianza: dict[str, float] = field(default_factory=dict)
    alertas: list[str] = field(default_factory=list)
    validaciones: list[dict[str, Any]] = field(default_factory=list)

    # -- utilidades ---------------------------------------------------------
    def clave_duplicado(self) -> str:
        """Clave estable: el identificador fiscal único si existe; si no, emisor + tipo + número."""
        if self.id_fiscal_unico:
            return f"{self.tipo_id_unico}:{self.id_fiscal_unico.upper()}"
        return f"{solo_alnum(self.emisor.id_fiscal)}|{self.tipo}|{clave_numero(self.numero)}"

    def a_dict(self) -> dict[str, Any]:
        def conv(v: Any) -> Any:
            if isinstance(v, Decimal):
                return float(v)
            if isinstance(v, list):
                return [conv(x) for x in v]
            if isinstance(v, dict):
                return {k: conv(x) for k, x in v.items()}
            return v
        return conv(asdict(self))

    def a_extraccion_v1(self) -> dict[str, Any]:
        """Adaptador al contrato que usa el motor de reglas (versión 1)."""
        conf = {k: 1.0 for k in ["beneficiario", "id_fiscal", "numero_factura", "moneda", "monto", "fecha_vencimiento"]}
        conf.update(self.confianza or {})
        concepto = "; ".join(l.descripcion for l in self.lineas[:3]) or None
        a_pagar = self.total_a_pagar if self.total_a_pagar is not None else self.total
        f = lambda d: float(d) if d is not None else None
        return {
            "beneficiario": {"nombre": self.emisor.nombre, "id_fiscal": self.emisor.id_fiscal, "pais": self.emisor.pais},
            "contacto": self.emisor.correo, "numero_factura": self.numero, "fecha_emision": self.fecha_emision,
            "fecha_vencimiento": self.fecha_vencimiento, "moneda": self.moneda, "monto": f(a_pagar),
            "horas": f(self.horas), "concepto": concepto, "cuenta_destino": self.cuenta_destino,
            "confianza": conf, "alertas": list(self.alertas),
            # Campos de la versión 2 (el motor de reglas los usa si existen)
            "version": self.version, "tipo_documento": self.tipo, "metodo_lectura": self.metodo_lectura,
            "id_fiscal_unico": self.id_fiscal_unico, "tipo_id_unico": self.tipo_id_unico,
            "documento_relacionado": self.documento_relacionado, "orden_compra": self.orden_compra,
            "metodo_pago": self.metodo_pago, "tasa_cambio": f(self.tasa_cambio),
            "receptor": {"nombre": self.receptor.nombre, "id_fiscal": self.receptor.id_fiscal, "pais": self.receptor.pais},
            "subtotal": f(self.subtotal), "total": f(self.total),
            "impuestos": [{"tipo": i.tipo, "tasa": f(i.tasa), "base": f(i.base), "monto": f(i.monto), "retencion": i.retencion}
                          for i in self.impuestos],
            "lineas": [{"codigo": l.codigo, "descripcion": l.descripcion, "cantidad": f(l.cantidad), "unidad": l.unidad,
                        "precio_unitario": f(l.precio_unitario), "total": f(l.total)} for l in self.lineas],
            "validaciones": list(self.validaciones),
        }


def desde_extraccion_v1(ext: dict[str, Any], metodo: str = "ia") -> FacturaCanonica:
    """Convierte la salida de la IA (contrato v1) en factura canónica normalizada y validada."""
    b = ext.get("beneficiario") or {}
    pais = (b.get("pais") or "").upper() or None
    v = validar_id_fiscal(b.get("id_fiscal"), pais)
    f = FacturaCanonica(
        tipo=ext.get("tipo_documento") or "factura", numero=ext.get("numero_factura"),
        fecha_emision=normalizar_fecha(ext.get("fecha_emision"), pais),
        fecha_vencimiento=normalizar_fecha(ext.get("fecha_vencimiento"), pais),
        moneda=normalizar_moneda(ext.get("moneda"), pais),
        emisor=Parte(nombre=b.get("nombre"), id_fiscal=b.get("id_fiscal"), tipo_id=v.tipo, id_valido=v.valido,
                     pais=pais, correo=ext.get("contacto")),
        total_a_pagar=normalizar_monto(ext.get("monto"), pais), horas=normalizar_monto(ext.get("horas")),
        cuenta_destino=solo_digitos(ext.get("cuenta_destino"))[-4:] or None,
        lineas=[Linea(descripcion=ext["concepto"])] if ext.get("concepto") else [],
        metodo_lectura=metodo, confianza=dict(ext.get("confianza") or {}), alertas=list(ext.get("alertas") or []),
    )
    f.total = f.total_a_pagar
    return f
