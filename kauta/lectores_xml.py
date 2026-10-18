"""
Kauta · Lectura determinista de facturas electrónicas: XML fiscal, ZIP y códigos QR. Sin IA.

Cuando una factura llega con su XML fiscal, Kauta no necesita IA para leerla: el XML es el
documento legal y trae los datos exactos. Se soportan:

  * México    · CFDI 4.0 (Anexo 20 del SAT) con su Timbre Fiscal Digital (UUID).
  * Colombia  · Factura electrónica de venta DIAN (UBL 2.1), notas crédito y débito, y el
                contenedor AttachedDocument que se envía al comprador (ZIP con XML + PDF).
  * Argentina · el QR de ARCA (JSON en Base64) que llevan las facturas electrónicas.
  * En PDF e imagen: CUFE, UUID, CAE y los enlaces de verificación (DIAN, SAT, ARCA).

Seguridad del lector (archivos que vienen de afuera = datos no confiables):
  * defusedxml: bloquea DTD, entidades y referencias externas (XXE, «billion laughs»).
  * Límites de tamaño; en ZIP, límite de archivos, rutas peligrosas («zip slip»),
    ZIP cifrado y relaciones de compresión anómalas («bomba ZIP»).
  * Nada de lo que trae el archivo se ejecuta ni se usa como instrucción.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import io
import json
import re
import zipfile
from decimal import Decimal, InvalidOperation
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import unquote

from defusedxml import ElementTree as DET
from defusedxml.common import DefusedXmlException

from .normalizacion import (FacturaCanonica, Impuesto, Linea, Parte, solo_alnum, solo_digitos,
                            validar_id_fiscal)

MAX_XML_BYTES = 5 * 1024 * 1024
MAX_ZIP_BYTES = 25 * 1024 * 1024
MAX_ZIP_ARCHIVOS = 20
MAX_ZIP_DESCOMPRIMIDO = 60 * 1024 * 1024
MAX_RATIO_COMPRESION = 200
CENTAVO = Decimal("0.01")

NS = {
    "cfdi": "http://www.sat.gob.mx/cfd/4",
    "cfdi33": "http://www.sat.gob.mx/cfd/3",
    "tfd": "http://www.sat.gob.mx/TimbreFiscalDigital",
    "inv": "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
    "cn": "urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2",
    "dn": "urn:oasis:names:specification:ubl:schema:xsd:DebitNote-2",
    "ad": "urn:oasis:names:specification:ubl:schema:xsd:AttachedDocument-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
}
TIPOS_RAIZ = {
    f"{{{NS['cfdi']}}}Comprobante": "cfdi40",
    f"{{{NS['cfdi33']}}}Comprobante": "cfdi33",
    f"{{{NS['inv']}}}Invoice": "ubl_factura",
    f"{{{NS['cn']}}}CreditNote": "ubl_nota_credito",
    f"{{{NS['dn']}}}DebitNote": "ubl_nota_debito",
    f"{{{NS['ad']}}}AttachedDocument": "dian_contenedor",
}


class DocumentoRechazado(ValueError):
    """El archivo no se procesa: es inseguro, está mal formado o no es una factura reconocida."""


def _v(campo: str, valido: bool | None, detalle: str) -> dict[str, Any]:
    return {"campo": campo, "valido": valido, "detalle": detalle}


def _txt(el: Any, ruta: str) -> str | None:
    if el is None:
        return None
    x = el.find(ruta, NS)
    return x.text.strip() if x is not None and x.text and x.text.strip() else None


def _dec(s: Any) -> Decimal | None:
    if s is None:
        return None
    try:
        return Decimal(str(s).strip())
    except InvalidOperation:
        return None


def _num(d: Decimal | None) -> str:
    return "—" if d is None else f"{d:,.2f}".replace(",", "§").replace(".", ",").replace("§", ".")


# ---------------------------------------------------------------------------
# XML seguro
# ---------------------------------------------------------------------------
def parsear_xml(datos: bytes):
    if len(datos) > MAX_XML_BYTES:
        raise DocumentoRechazado(f"El XML pesa {len(datos) // 1024} KB; el máximo permitido es {MAX_XML_BYTES // 1048576} MB.")
    try:
        return DET.fromstring(datos, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except DefusedXmlException as e:
        raise DocumentoRechazado("El XML trae una declaración DTD o entidades (patrón de ataque XXE o «billion laughs»). "
                                 "Kauta no lo abre: se descarta sin ejecutar nada.") from e
    except DET.ParseError as e:
        raise DocumentoRechazado(f"El XML está mal formado ({e}).") from e


def tipo_xml(raiz) -> str | None:
    return TIPOS_RAIZ.get(raiz.tag)


# ---------------------------------------------------------------------------
# México · CFDI 4.0
# ---------------------------------------------------------------------------
TIPO_CFDI = {"I": "factura", "E": "nota_credito", "P": "recibo_pago", "T": "otro", "N": "otro"}
IMPUESTO_SAT = {"001": "ISR", "002": "IVA", "003": "IEPS"}
PAIS_ISO3 = {"COL": "CO", "USA": "US", "MEX": "MX", "ARG": "AR", "BRA": "BR", "CHL": "CL", "PER": "PE",
             "ESP": "ES", "CAN": "CA", "GBR": "GB", "DEU": "DE"}


def url_verificacion_sat(uuid: str, rfc_emisor: str, rfc_receptor: str, total: Any, sello: str) -> str:
    """Enlace que lleva el QR de todo CFDI para verificarlo en el portal del SAT."""
    tt = f"{Decimal(str(total)):.2f}"
    return (f"https://verificacfdi.facturaelectronica.sat.gob.mx/default.aspx?id={uuid}&re={rfc_emisor}"
            f"&rr={rfc_receptor}&tt={tt}&fe={sello[-8:]}")


def leer_cfdi(raiz) -> tuple[FacturaCanonica, list[dict[str, Any]]]:
    a = raiz.attrib
    em, rc = raiz.find("cfdi:Emisor", NS), raiz.find("cfdi:Receptor", NS)
    if em is None or rc is None:
        raise DocumentoRechazado("El CFDI no trae Emisor o Receptor.")
    tfd = raiz.find("cfdi:Complemento/tfd:TimbreFiscalDigital", NS)
    rfc_em = (em.get("Rfc") or "").upper()
    v_em = validar_id_fiscal(f"RFC {rfc_em}", "MX")
    rfc_rc = (rc.get("Rfc") or "").upper()
    extranjero = rfc_rc == "XEXX010101000"
    id_rc = rc.get("NumRegIdTrib") if extranjero and rc.get("NumRegIdTrib") else rfc_rc
    serie, folio = a.get("Serie"), a.get("Folio")

    lineas = [Linea(descripcion=c.get("Descripcion") or "", cantidad=_dec(c.get("Cantidad")) or Decimal(1),
                    unidad=c.get("Unidad") or c.get("ClaveUnidad"), precio_unitario=_dec(c.get("ValorUnitario")),
                    total=_dec(c.get("Importe")), codigo=c.get("NoIdentificacion"))
              for c in raiz.findall("cfdi:Conceptos/cfdi:Concepto", NS)]
    impuestos: list[Impuesto] = []
    glob = raiz.find("cfdi:Impuestos", NS)
    if glob is not None:
        for t in glob.findall("cfdi:Traslados/cfdi:Traslado", NS):
            tasa = _dec(t.get("TasaOCuota"))
            impuestos.append(Impuesto(tipo=IMPUESTO_SAT.get(t.get("Impuesto"), t.get("Impuesto") or "?"),
                                      tasa=(tasa * 100).normalize() if tasa is not None else None,
                                      base=_dec(t.get("Base")), monto=_dec(t.get("Importe")) or Decimal(0)))
        for r in glob.findall("cfdi:Retenciones/cfdi:Retencion", NS):
            impuestos.append(Impuesto(tipo=IMPUESTO_SAT.get(r.get("Impuesto"), r.get("Impuesto") or "?") + "_RET", tasa=None,
                                      base=None, monto=_dec(r.get("Importe")) or Decimal(0), retencion=True))
    subtotal, total = _dec(a.get("SubTotal")), _dec(a.get("Total"))
    descuento = _dec(a.get("Descuento")) or Decimal(0)
    uuid = tfd.get("UUID").upper() if tfd is not None and tfd.get("UUID") else None

    f = FacturaCanonica(
        tipo=TIPO_CFDI.get(a.get("TipoDeComprobante") or "", "otro"),
        numero=f"{serie}-{folio}" if serie and folio else (folio or serie),
        fecha_emision=(a.get("Fecha") or "")[:10] or None, moneda=(a.get("Moneda") or "").upper() or None,
        emisor=Parte(nombre=em.get("Nombre"), id_fiscal=f"RFC {rfc_em}", tipo_id="RFC", id_valido=v_em.valido, pais="MX"),
        receptor=Parte(nombre=rc.get("Nombre"), id_fiscal=id_rc, tipo_id="NumRegIdTrib" if extranjero else "RFC",
                       pais=PAIS_ISO3.get(rc.get("ResidenciaFiscal") or "", None if extranjero else "MX")),
        lineas=lineas, impuestos=impuestos, subtotal=subtotal, total=total, total_a_pagar=total,
        tasa_cambio=_dec(a.get("TipoCambio")), metodo_pago=a.get("MetodoPago"),
        id_fiscal_unico=uuid, tipo_id_unico="UUID" if uuid else None, metodo_lectura="xml_fiscal")
    rel = raiz.find("cfdi:CfdiRelacionados/cfdi:CfdiRelacionado", NS)
    if rel is not None:
        f.documento_relacionado = rel.get("UUID")
    # El CFDI no tiene un campo de vencimiento: si las condiciones de pago traen la fecha límite (dd/mm/aaaa), se toma
    limite = re.search(r"(\d{2})/(\d{2})/(\d{4})", a.get("CondicionesDePago") or "")
    if limite:
        f.fecha_vencimiento = f"{limite.group(3)}-{limite.group(2)}-{limite.group(1)}"

    val = [_v("id_fiscal", v_em.valido, f"RFC del emisor {rfc_em}: {v_em.detalle}")]
    if uuid:
        val.append(_v("timbre_fiscal", True, f"CFDI timbrado el {(tfd.get('FechaTimbrado') or '')[:10]} · folio fiscal (UUID) {uuid}."))
    else:
        val.append(_v("timbre_fiscal", False, "El CFDI no trae Timbre Fiscal Digital (UUID): no es un comprobante válido ante el SAT."))
    if subtotal is not None and total is not None:
        tras = sum((i.monto for i in impuestos if not i.retencion), Decimal(0))
        ret = sum((i.monto for i in impuestos if i.retencion), Decimal(0))
        calc = subtotal - descuento + tras - ret
        ok = abs(calc - total) <= CENTAVO
        val.append(_v("totales", ok, f"Subtotal {_num(subtotal)} − descuento {_num(descuento)} + impuestos trasladados {_num(tras)} − "
                                     f"retenidos {_num(ret)} = {_num(calc)}" + ("; cuadra con el total." if ok else
                                                                                 f", pero el total dice {_num(total)}: no cuadra.")))
    if a.get("MetodoPago") == "PPD":
        val.append(_v("metodo_pago", None, "Pago en parcialidades o diferido (PPD): al pagar, el proveedor debe emitir el "
                                           "complemento de pago (REP) dentro del plazo del SAT."))
    if uuid and a.get("Sello"):
        f.alertas.append("verificar_en_sat")
        val.append(_v("verificacion_sat", None, "Consulta pública del SAT (requiere conexión): "
                      + url_verificacion_sat(uuid, rfc_em, rfc_rc, total or 0, a.get("Sello") or "")))
    f.confianza = {k: 1.0 for k in ("beneficiario", "id_fiscal", "numero_factura", "moneda", "monto", "fecha_vencimiento")}
    return f, val


# ---------------------------------------------------------------------------
# Colombia · DIAN UBL 2.1 y AttachedDocument
# ---------------------------------------------------------------------------
TRIBUTO_DIAN = {"01": "IVA", "02": "IC", "03": "ICA", "04": "INC", "05": "ReteIVA", "06": "ReteRenta", "07": "ReteICA",
                "ZZ": "No aplica"}
TIPO_DOC_DIAN = {"11": "RC", "12": "TI", "13": "CC", "21": "TE", "22": "CE", "31": "NIT", "41": "Pasaporte",
                 "42": "Documento extranjero", "47": "PEP", "48": "PPT", "50": "NIT de otro país", "91": "NUIP"}
TIPO_FACTURA_DIAN = {"01": "Factura electrónica de venta", "02": "Factura de exportación",
                     "03": "Factura por contingencia del facturador", "04": "Factura por contingencia DIAN"}


def calcular_cufe(numero: str, fecha: str, hora: str, subtotal: Any, iva: Any, inc: Any, ica: Any, total: Any,
                  nit_emisor: str, id_adquiriente: str, clave_tecnica: str, ambiente: str = "1") -> str:
    """CUFE = SHA-384 de la concatenación definida por la DIAN (Anexo técnico 1.9). Lo calcula el EMISOR:
    el comprador no conoce la clave técnica, así que la verifica consultando a la DIAN."""
    d = lambda x: f"{Decimal(str(x)):.2f}"
    cadena = (f"{numero}{fecha}{hora}{d(subtotal)}01{d(iva)}04{d(inc)}03{d(ica)}{d(total)}"
              f"{solo_digitos(nit_emisor)}{solo_digitos(id_adquiriente)}{clave_tecnica}{ambiente}")
    return hashlib.sha384(cadena.encode("utf-8")).hexdigest()


def _parte_ubl(party) -> Parte:
    if party is None:
        return Parte()
    nombre = (_txt(party, "cac:PartyTaxScheme/cbc:RegistrationName") or _txt(party, "cac:PartyLegalEntity/cbc:RegistrationName")
              or _txt(party, "cac:PartyName/cbc:Name"))
    cid = party.find("cac:PartyTaxScheme/cbc:CompanyID", NS)
    if cid is None:
        cid = party.find("cac:PartyLegalEntity/cbc:CompanyID", NS)
    numero = (cid.text or "").strip() if cid is not None else ""
    tipo = TIPO_DOC_DIAN.get(cid.get("schemeName") or "") if cid is not None else None
    dv = cid.get("schemeID") if cid is not None else None
    if tipo == "NIT" and dv not in (None, ""):
        idf = f"NIT {numero}-{dv}"
    elif tipo == "CC":
        idf = f"C.C. {numero}"
    else:
        idf = numero or None
    pais = (_txt(party, "cac:PartyTaxScheme/cac:RegistrationAddress/cac:Country/cbc:IdentificationCode")
            or _txt(party, "cac:PhysicalLocation/cac:Address/cac:Country/cbc:IdentificationCode"))
    return Parte(nombre=nombre, id_fiscal=idf, tipo_id=tipo, pais=pais, correo=_txt(party, "cac:Contact/cbc:ElectronicMail"))


def leer_ubl_dian(raiz, tipo_raiz: str) -> tuple[FacturaCanonica, list[dict[str, Any]]]:
    tipo = {"ubl_factura": "factura", "ubl_nota_credito": "nota_credito", "ubl_nota_debito": "nota_debito"}[tipo_raiz]
    em = _parte_ubl(raiz.find("cac:AccountingSupplierParty/cac:Party", NS))
    rc = _parte_ubl(raiz.find("cac:AccountingCustomerParty/cac:Party", NS))
    v_em = validar_id_fiscal(em.id_fiscal, "CO") if em.id_fiscal else None
    em.id_valido = v_em.valido if v_em else None
    if not em.pais:
        em.pais = "CO"
    uuid_el = raiz.find("cbc:UUID", NS)
    cufe = uuid_el.text.strip().lower() if uuid_el is not None and uuid_el.text else None
    esquema = (uuid_el.get("schemeName") if uuid_el is not None else None) or "CUFE-SHA384"
    tot = raiz.find("cac:LegalMonetaryTotal", NS)
    if tot is None:
        tot = raiz.find("cac:RequestedMonetaryTotal", NS)
    linea_tag, cant_tag = {"factura": ("cac:InvoiceLine", "cbc:InvoicedQuantity"),
                           "nota_credito": ("cac:CreditNoteLine", "cbc:CreditedQuantity"),
                           "nota_debito": ("cac:DebitNoteLine", "cbc:DebitedQuantity")}[tipo]
    lineas = []
    for ln in raiz.findall(linea_tag, NS):
        cant = ln.find(cant_tag, NS)
        lineas.append(Linea(descripcion=_txt(ln, "cac:Item/cbc:Description") or "",
                            cantidad=_dec(cant.text if cant is not None else None) or Decimal(1),
                            unidad=cant.get("unitCode") if cant is not None else None,
                            precio_unitario=_dec(_txt(ln, "cac:Price/cbc:PriceAmount")), total=_dec(_txt(ln, "cbc:LineExtensionAmount"))))
    impuestos: list[Impuesto] = []
    for grupo, es_ret in (("cac:TaxTotal", False), ("cac:WithholdingTaxTotal", True)):
        for tt in raiz.findall(grupo, NS):
            for st in tt.findall("cac:TaxSubtotal", NS):
                cod = _txt(st, "cac:TaxCategory/cac:TaxScheme/cbc:ID") or "?"
                impuestos.append(Impuesto(tipo=TRIBUTO_DIAN.get(cod, cod), tasa=_dec(_txt(st, "cac:TaxCategory/cbc:Percent")),
                                          base=_dec(_txt(st, "cbc:TaxableAmount")), monto=_dec(_txt(st, "cbc:TaxAmount")) or Decimal(0),
                                          retencion=es_ret))
    subtotal = _dec(_txt(tot, "cbc:LineExtensionAmount"))
    con_imp = _dec(_txt(tot, "cbc:TaxInclusiveAmount"))
    total = _dec(_txt(tot, "cbc:PayableAmount"))
    ambiente = _txt(raiz, "cbc:ProfileExecutionID")
    cuenta = _txt(raiz, "cac:PaymentMeans/cac:PayeeFinancialAccount/cbc:ID")

    f = FacturaCanonica(
        tipo=tipo, numero=_txt(raiz, "cbc:ID"), fecha_emision=_txt(raiz, "cbc:IssueDate"),
        fecha_vencimiento=_txt(raiz, "cbc:DueDate") or _txt(raiz, "cac:PaymentMeans/cbc:PaymentDueDate"),
        moneda=(_txt(raiz, "cbc:DocumentCurrencyCode") or "").upper() or None, emisor=em, receptor=rc,
        lineas=lineas, impuestos=impuestos, subtotal=subtotal, total=total, total_a_pagar=total,
        tasa_cambio=_dec(_txt(raiz, "cac:PaymentExchangeRate/cbc:CalculationRate")),
        metodo_pago={"1": "contado", "2": "crédito"}.get(_txt(raiz, "cac:PaymentMeans/cbc:ID") or "", None),
        cuenta_destino=solo_digitos(cuenta)[-4:] or None if cuenta else None,
        id_fiscal_unico=cufe, tipo_id_unico=esquema.split("-")[0] if cufe else None,
        documento_relacionado=_txt(raiz, "cac:BillingReference/cac:InvoiceDocumentReference/cbc:ID"),
        orden_compra=_txt(raiz, "cac:OrderReference/cbc:ID"), metodo_lectura="xml_fiscal")
    f.confianza = {k: 1.0 for k in ("beneficiario", "id_fiscal", "numero_factura", "moneda", "monto", "fecha_vencimiento")}

    val: list[dict[str, Any]] = []
    if v_em:
        val.append(_v("id_fiscal", v_em.valido, f"{v_em.tipo} del emisor: {v_em.detalle}"))
    if cufe and re.fullmatch(r"[0-9a-f]{96}", cufe):
        val.append(_v("cufe", True, f"{esquema.split('-')[0]} con formato SHA-384 válido (96 caracteres)."))
    else:
        val.append(_v("cufe", False, "La factura no trae un CUFE válido: sin él no es una factura electrónica ante la DIAN."))
    if ambiente == "2":
        val.append(_v("ambiente", False, "Emitida en el ambiente de PRUEBAS (habilitación) de la DIAN: no tiene validez fiscal."))
    elif ambiente == "1":
        val.append(_v("ambiente", True, "Emitida en el ambiente de producción de la DIAN."))
    if subtotal is not None and total is not None:
        imp = sum((i.monto for i in impuestos if not i.retencion), Decimal(0))
        ajustes = (- (_dec(_txt(tot, "cbc:AllowanceTotalAmount")) or 0) + (_dec(_txt(tot, "cbc:ChargeTotalAmount")) or 0)
                   - (_dec(_txt(tot, "cbc:PrepaidAmount")) or 0) + (_dec(_txt(tot, "cbc:PayableRoundingAmount")) or 0))
        calc = (con_imp if con_imp is not None else subtotal + imp) + ajustes
        ok = abs(calc - total) <= CENTAVO * max(1, len(lineas)) and (con_imp is None or abs(subtotal + imp - con_imp) <= CENTAVO * max(1, len(lineas)))
        val.append(_v("totales", ok, f"Base {_num(subtotal)} + impuestos {_num(imp)} {'+ ajustes ' + _num(ajustes) + ' ' if ajustes else ''}"
                                     f"= {_num(calc)}" + ("; cuadra con el total a pagar." if ok else f", pero el total a pagar dice {_num(total)}: no cuadra.")))
    rets = [i for i in impuestos if i.retencion]
    if rets:
        val.append(_v("retenciones", None, "Retenciones informadas: " + ", ".join(f"{i.tipo} {_num(i.monto)}" for i in rets)
                      + ". Las practica el pagador si es agente de retención en Colombia."))
    return f, val


def leer_contenedor_dian(raiz) -> tuple[FacturaCanonica, list[dict[str, Any]]]:
    desc = raiz.find("cac:Attachment/cac:ExternalReference/cbc:Description", NS)
    if desc is None or not (desc.text or "").strip():
        raise DocumentoRechazado("El AttachedDocument no trae la factura embebida.")
    interno = parsear_xml(desc.text.strip().encode("utf-8"))
    t = tipo_xml(interno)
    if t not in ("ubl_factura", "ubl_nota_credito", "ubl_nota_debito"):
        raise DocumentoRechazado("El contenedor DIAN no trae una factura o nota UBL.")
    f, val = leer_ubl_dian(interno, t)
    ref = raiz.find("cac:ParentDocumentLineReference/cac:DocumentReference", NS)
    cufe_cont = (_txt(ref, "cbc:UUID") or "").lower() or None
    codigo = _txt(ref, "cac:ResultOfVerification/cbc:ValidationResultCode")
    fecha_val = _txt(ref, "cac:ResultOfVerification/cbc:ValidationDate")
    padre = _txt(raiz, "cbc:ParentDocumentID")
    if cufe_cont and f.id_fiscal_unico:
        ok = cufe_cont == f.id_fiscal_unico
        val.append(_v("cufe_contenedor", ok, "El CUFE del contenedor coincide con el de la factura." if ok else
                      "El CUFE del contenedor NO coincide con el de la factura embebida: posible documento alterado."))
    if padre and f.numero and padre != f.numero:
        val.append(_v("numero_contenedor", False, f"El contenedor dice factura {padre}, pero la embebida es {f.numero}."))
    if codigo == "02":
        val.append(_v("validacion_dian", True, f"La DIAN validó la factura (código 02) el {fecha_val or 's. f.'}."))
    elif codigo:
        val.append(_v("validacion_dian", False, f"La DIAN no validó la factura (código {codigo})."))
    else:
        val.append(_v("validacion_dian", None, "El contenedor no trae el resultado de validación de la DIAN."))
    return f, val


# ---------------------------------------------------------------------------
# Entrada única para XML
# ---------------------------------------------------------------------------
def leer_xml_fiscal(datos: bytes) -> tuple[FacturaCanonica, list[dict[str, Any]], str]:
    """Lee un XML fiscal y devuelve (factura canónica, validaciones, tipo). Lanza DocumentoRechazado."""
    raiz = parsear_xml(datos)
    t = tipo_xml(raiz)
    if t == "cfdi40":
        f, v = leer_cfdi(raiz)
    elif t in ("ubl_factura", "ubl_nota_credito", "ubl_nota_debito"):
        f, v = leer_ubl_dian(raiz, t)
    elif t == "dian_contenedor":
        f, v = leer_contenedor_dian(raiz)
    elif t == "cfdi33":
        raise DocumentoRechazado("CFDI 3.3: el SAT ya no lo acepta para facturas nuevas desde 2023. Pida la versión 4.0.")
    else:
        raise DocumentoRechazado(f"XML no reconocido como factura electrónica (raíz {raiz.tag[:80]}).")
    f.validaciones = v
    return f, v, t


# ---------------------------------------------------------------------------
# ZIP seguro
# ---------------------------------------------------------------------------
def abrir_zip(datos: bytes) -> list[tuple[str, bytes]]:
    if len(datos) > MAX_ZIP_BYTES:
        raise DocumentoRechazado(f"El ZIP supera {MAX_ZIP_BYTES // 1048576} MB.")
    try:
        z = zipfile.ZipFile(io.BytesIO(datos))
    except zipfile.BadZipFile as e:
        raise DocumentoRechazado("El ZIP está dañado o no es un ZIP.") from e
    salida, total = [], 0
    with z:
        infos = [i for i in z.infolist() if not i.is_dir()]
        if len(infos) > MAX_ZIP_ARCHIVOS:
            raise DocumentoRechazado(f"El ZIP trae {len(infos)} archivos; el máximo es {MAX_ZIP_ARCHIVOS}.")
        for i in infos:
            nombre = i.filename.replace("\\", "/")
            partes = PurePosixPath(nombre).parts
            if nombre.startswith("/") or ".." in partes or re.match(r"^[A-Za-z]:", nombre):
                raise DocumentoRechazado(f"Ruta peligrosa dentro del ZIP ({i.filename}): patrón «zip slip». No se abre.")
            if i.flag_bits & 0x1:
                raise DocumentoRechazado("El ZIP está protegido con contraseña; no se puede revisar su contenido.")
            total += i.file_size
            if total > MAX_ZIP_DESCOMPRIMIDO:
                raise DocumentoRechazado("El contenido descomprimido supera el límite: posible «bomba ZIP».")
            if i.compress_size and i.file_size / i.compress_size > MAX_RATIO_COMPRESION:
                raise DocumentoRechazado("Relación de compresión anómala: posible «bomba ZIP».")
            try:
                with z.open(i) as fh:
                    contenido = fh.read(i.file_size + 1)
            except (zipfile.BadZipFile, RuntimeError) as e:
                raise DocumentoRechazado(f"No se pudo leer {i.filename} dentro del ZIP (archivo dañado).") from e
            if len(contenido) != i.file_size:
                raise DocumentoRechazado("El tamaño declarado en el ZIP no coincide con el real.")
            salida.append((partes[-1], contenido))
    return salida


# ---------------------------------------------------------------------------
# Identificadores fiscales en texto, enlaces y QR (PDF e imagen)
# ---------------------------------------------------------------------------
TIPO_CMP_ARCA = {1: "Factura A", 2: "Nota de débito A", 3: "Nota de crédito A", 6: "Factura B", 7: "Nota de débito B",
                 8: "Nota de crédito B", 11: "Factura C", 12: "Nota de débito C", 13: "Nota de crédito C", 19: "Factura E",
                 20: "Nota de débito E", 21: "Nota de crédito E", 51: "Factura M", 201: "Factura de crédito electrónica MiPyME A"}
MONEDA_ARCA = {"PES": "ARS", "DOL": "USD", "060": "EUR", "012": "BRL"}
RE_UUID = r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}"


def _param(url: str, clave: str) -> str | None:
    m = re.search(rf"[?&]{clave}=([^&#\s]+)", url)
    return unquote(m.group(1)) if m else None  # unquote (no unquote_plus): el «+» del Base64 se conserva


def leer_qr_arca(url: str) -> dict[str, Any] | None:
    if not re.search(r"(afip|arca)\.gob\.ar/fe/qr", url or ""):
        return None
    p = _param(url, "p")
    if not p:
        return None
    try:
        p = p.strip() + "=" * (-len(p.strip()) % 4)
        crudo = base64.urlsafe_b64decode(p) if ("-" in p or "_" in p) else base64.b64decode(p, validate=False)
        datos = json.loads(crudo.decode("utf-8"))
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None
    return datos if isinstance(datos, dict) and "cuit" in datos else None


def qr_arca(datos: dict[str, Any]) -> str:
    """Arma el enlace del QR de ARCA a partir de sus datos (lo usa el generador del set de prueba)."""
    j = json.dumps(datos, separators=(",", ":"), ensure_ascii=True).encode()
    return "https://www.afip.gob.ar/fe/qr/?p=" + base64.b64encode(j).decode()


def identificadores_fiscales(texto: str, uris: list[str] | tuple = (), qrs: list[str] | tuple = ()) -> dict[str, Any]:
    fuentes = "\n".join([texto or "", *uris, *qrs])
    res: dict[str, Any] = {}
    m = re.search(r"documentkey=([0-9a-fA-F]{96})", fuentes) or re.search(r"CU[FD]E\s*[:#]?\s*((?:[0-9a-fA-F]\s*){96})", fuentes)
    if m:
        res["cufe"] = re.sub(r"\s", "", m.group(1)).lower()
    m = re.search(r"https?://verificacfdi\.facturaelectronica\.sat\.gob\.mx/\S+", fuentes)
    if m:
        url = m.group(0)
        res["sat"] = {"uuid": (_param(url, "id") or "").upper(), "re": _param(url, "re"), "rr": _param(url, "rr"),
                      "tt": _dec(_param(url, "tt"))}
    else:
        m = re.search(rf"(?:Folio fiscal|UUID)[^0-9A-Fa-f]{{0,24}}({RE_UUID})", fuentes, flags=re.I)
        if m:
            res["uuid"] = m.group(1).upper()
    m = re.search(r"https?://(?:www\.)?(?:afip|arca)\.gob\.ar/fe/qr/?\?\S+", fuentes)
    if m:
        q = leer_qr_arca(m.group(0))
        if q:
            res["arca"] = q
    m = re.search(r"\bCAE\b[^0-9]{0,12}(\d{14})", fuentes)
    if m:
        res["cae"] = m.group(1)
    return res


def contrastar(ext: dict[str, Any], ids: dict[str, Any]) -> tuple[str | None, str | None, list[dict[str, Any]]]:
    """Compara lo que leyó la IA con los datos fiscales del QR/enlace. Devuelve (id único, tipo, validaciones)."""
    val: list[dict[str, Any]] = []
    uid = tipo = None
    monto = _dec(ext.get("monto"))
    idf = solo_alnum(re.sub(r"^\s*(NIT|RFC|CUIT|EIN|C\.?C\.?)\s*", "", ((ext.get("beneficiario") or {}).get("id_fiscal") or ""), flags=re.I))
    if "cufe" in ids:
        uid, tipo = ids["cufe"], "CUFE"
        val.append(_v("cufe", True, "CUFE leído del documento: identifica la factura ante la DIAN y evita pagarla dos veces."))
    sat = ids.get("sat")
    if sat and sat.get("uuid"):
        uid, tipo = sat["uuid"], "UUID"
        if sat.get("tt") is not None and monto is not None:
            ok = abs(sat["tt"] - monto) <= CENTAVO
            val.append(_v("qr_total", ok, f"El QR del SAT indica total {_num(sat['tt'])} y la lectura {_num(monto)}"
                                          + ("; coinciden." if ok else ": no coinciden, posible documento alterado.")))
        if sat.get("re") and idf:
            ok = solo_alnum(sat["re"]) == idf
            val.append(_v("qr_emisor", ok, "El RFC del QR coincide con el del emisor." if ok else
                          f"El QR del SAT es del RFC {sat['re']}, no del emisor leído: posible documento alterado."))
    elif "uuid" in ids:
        uid, tipo = ids["uuid"], "UUID"
    arca = ids.get("arca")
    if arca:
        try:
            uid = f"{int(arca['cuit'])}-{int(arca.get('tipoCmp', 0)):03d}-{int(arca.get('ptoVta', 0)):05d}-{int(arca.get('nroCmp', 0)):08d}"
            tipo = "ARCA"
        except (TypeError, ValueError):
            pass
        imp = _dec(arca.get("importe"))
        if imp is not None and monto is not None:
            ok = abs(imp - monto) <= CENTAVO
            val.append(_v("qr_total", ok, f"El QR de ARCA indica importe {_num(imp)} y la lectura {_num(monto)}"
                                          + ("; coinciden." if ok else ": no coinciden, posible documento alterado.")))
        mon = MONEDA_ARCA.get(str(arca.get("moneda")), str(arca.get("moneda")))
        if ext.get("moneda") and mon and mon != ext.get("moneda"):
            val.append(_v("qr_moneda", False, f"El QR de ARCA dice moneda {mon}; la lectura dice {ext.get('moneda')}."))
        if idf and str(arca.get("cuit")):
            ok = solo_digitos(str(arca["cuit"])) == solo_digitos(idf)
            val.append(_v("qr_emisor", ok, f"{TIPO_CMP_ARCA.get(int(arca.get('tipoCmp', 0)), 'Comprobante')} autorizado con CAE "
                                           f"{arca.get('codAut')}; el CUIT del QR coincide con el emisor." if ok else
                          "El CUIT del QR de ARCA no coincide con el emisor leído: posible documento alterado."))
    return uid, tipo, val


# ---------------------------------------------------------------------------
# PDF: enlaces (anotaciones) y QR en imágenes (opcional, si hay OpenCV)
# ---------------------------------------------------------------------------
def uris_pdf(datos: bytes) -> list[str]:
    try:
        from pypdf import PdfReader
        lector = PdfReader(io.BytesIO(datos))
        salida = []
        for p in lector.pages[:5]:
            for a in (p.get("/Annots") or []):
                obj = a.get_object()
                accion = obj.get("/A")
                if accion is not None:
                    uri = accion.get_object().get("/URI")
                    if uri:
                        salida.append(str(uri))
        return salida
    except Exception:
        return []


def qr_en_imagen(datos: bytes) -> list[str]:
    try:
        import cv2
        import numpy as np
    except Exception:
        return []
    try:
        img = cv2.imdecode(np.frombuffer(datos, np.uint8), cv2.IMREAD_GRAYSCALE)
        if img is None:
            return []
        det = cv2.QRCodeDetector()
        ok, textos, _, _ = det.detectAndDecodeMulti(img)
        return [t for t in (textos or []) if t] if ok else []
    except Exception:
        return []


def qr_en_pdf(datos: bytes, dpi: int = 200) -> list[str]:
    try:
        import pypdfium2 as pdfium
        doc = pdfium.PdfDocument(datos)
        img = doc[0].render(scale=dpi / 72).to_pil().convert("L")
        doc.close()
        buf = io.BytesIO()
        img.save(buf, "PNG")
        return qr_en_imagen(buf.getvalue())
    except Exception:
        return []
