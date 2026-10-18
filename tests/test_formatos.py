"""Pruebas de normalización, validadores y lectores de XML fiscal (sin IA)."""
import io
import random
import sys
import zipfile
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from kauta import lectores_xml as LX  # noqa: E402
from kauta import normalizacion as N  # noqa: E402
from kauta.agente import Agente, cargar_json  # noqa: E402
from kauta.extractor import ExtractorReferencia, leer_documento  # noqa: E402

SORP = RAIZ / "data" / "sorpresa"


# ------------------------------------------------------------ validadores
@pytest.mark.parametrize("valor,esperado", [
    ("NIT 901.482.317-5", True), ("900.618.442-0", True), ("900.618.442-7", False),
    ("CUIT 30-71634528-5", True), ("30-71634528-7", False),
    ("RFC TMA190312KJ4", True), ("OELJ880412AB5", True), ("OELJ880412AB3", False), ("XEXX010101000", True),
    ("TMA190312XK4", False),  # homoclave imposible: el SAT nunca emite una que empiece por X
    ("CUIT 20-12345678-6", True), ("CUIT 50-12345678-2", True), ("CUIT 40-12345678-7", False),
])
def test_identificaciones(valor, esperado):
    pais = "CO" if "NIT" in valor or valor.startswith("90") else "AR" if "CUIT" in valor or valor.startswith("30") else "MX"
    assert N.validar_id_fiscal(valor, pais).valido is esperado


def test_cnpj_alfanumerico_2026():
    assert N.validar_cnpj("12.ABC.345/01DE-35").valido is True
    assert N.validar_cnpj("12.ABC.345/01DE-36").valido is False


def test_validadores_bancarios():
    assert N.validar_iban("DE89 3704 0044 0532 0130 00").valido is True
    assert N.validar_iban("DE89 3704 0044 0532 0130 01").valido is False
    assert N.validar_bic("BCONCOBB").valido is True
    assert N.validar_iban("DE89 3704 0044 0532 0130 0").valido is False      # largo del país equivocado
    assert N.validar_iban("ES91 2100 0418 4502 0005 1332").valido is True
    assert N.validar_iban("ES56 2100 0418 4402 0005 1332").valido is False   # módulo 97 bien, CCC mal
    assert N.validar_iban("US12 3456 7890 1234 5678").valido is False         # EE. UU. no usa IBAN
    k = "".join(random.Random(3).choice("0123456789") for _ in range(17))
    suma = sum((int(d) * p) % 10 for d, p in zip(k, (3, 7, 1) * 6))
    assert N.validar_clabe(k + str((10 - suma % 10) % 10)).valido is True


@pytest.mark.parametrize("texto,pais,esperado", [
    ("2.400,00", None, "2400.00"), ("1,800.00", None, "1800.00"), ("$7.680.000", None, "7680000"),
    ("2.400", "CO", "2400"), ("18,4", None, "18.4"),
])
def test_montos(texto, pais, esperado):
    assert str(N.normalizar_monto(texto, pais)) == esperado


def test_fechas_por_pais():
    assert N.normalizar_fecha("10/01/2026", "US") == "2026-10-01"
    assert N.normalizar_fecha("10/01/2026", "CO") == "2026-01-10"
    assert N.normalizar_fecha("1 de octubre de 2026") == "2026-10-01"


def test_monedas():
    assert N.normalizar_moneda("DOL") == "USD"          # código de ARCA
    assert N.normalizar_moneda("PESOS M/CTE", "CO") == "COP"
    assert N.normalizar_moneda("$", "MX") == "MXN"
    assert N.normalizar_moneda("pesos") is None         # ambiguo sin país: no se adivina


# ------------------------------------------------------------ XML fiscal
def test_cfdi_lectura_exacta():
    f, val, tipo = LX.leer_xml_fiscal((SORP / "S01_traducciones-maya_TM-455.xml").read_bytes())
    assert tipo == "cfdi40" and f.numero == "TM-455" and str(f.total) == "27600.00" and f.moneda == "MXN"
    assert f.id_fiscal_unico and all(v["valido"] is not False for v in val)


def test_contenedor_dian_desde_zip():
    archivos = LX.abrir_zip((SORP / "S02_pixel-andino_PA-2026-10.zip").read_bytes())
    xml = next(c for n, c in archivos if n.endswith(".xml"))
    f, val, tipo = LX.leer_xml_fiscal(xml)
    assert tipo == "dian_contenedor" and f.emisor.id_fiscal == "NIT 901482317-5" and f.cuenta_destino == "4821"
    assert {v["campo"]: v["valido"] for v in val}["cufe_contenedor"] is True


def test_xxe_se_rechaza():
    with pytest.raises(LX.DocumentoRechazado):
        LX.parsear_xml((SORP / "S03_proveedor-desconocido_FX-001.xml").read_bytes())


def test_zip_slip_y_bomba():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("../../fuera.xml", "<a/>")
    with pytest.raises(LX.DocumentoRechazado):
        LX.abrir_zip(buf.getvalue())
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("bomba.xml", b"0" * 30_000_000)
    with pytest.raises(LX.DocumentoRechazado):
        LX.abrir_zip(buf.getvalue())


def test_totales_que_no_cuadran():
    xml = (SORP / "S01_traducciones-maya_TM-455.xml").read_text(encoding="utf-8").replace(' Total="27600.00"', ' Total="29600.00"')
    _, val, _ = LX.leer_xml_fiscal(xml.encode())
    assert {v["campo"]: v["valido"] for v in val}["totales"] is False


def test_qr_arca():
    url = LX.qr_arca({"ver": 1, "cuit": 30716345285, "ptoVta": 3, "tipoCmp": 19, "nroCmp": 77, "importe": 3200, "moneda": "DOL"})
    q = LX.leer_qr_arca(url)
    assert q["nroCmp"] == 77 and q["moneda"] == "DOL"


# ------------------------------------------------------------ de punta a punta
def _agente():
    return Agente(cargar_json("reglas.json"), cargar_json("beneficiarios.json"), ExtractorReferencia())


def test_xml_solo_se_paga_y_despues_del_pdf_es_duplicado():
    ag = _agente()
    s01 = (SORP / "S01_traducciones-maya_TM-455.xml")
    assert ag.procesar(s01.name, s01.read_bytes())["decision"].decision == "pagar"
    ag = _agente()
    f04 = RAIZ / "data" / "facturas" / "F04_traducciones-maya_TM-455.pdf"
    ag.procesar(f04.name, f04.read_bytes())
    d = ag.procesar(s01.name, s01.read_bytes())["decision"]
    assert d.decision == "frenar" and "(R03)" in d.motivo and "identificador fiscal" in d.motivo


def test_archivo_malicioso_escala_por_r01():
    ag = _agente()
    s03 = SORP / "S03_proveedor-desconocido_FX-001.xml"
    d = ag.procesar(s03.name, s03.read_bytes())["decision"]
    assert d.decision == "escalar" and d.motivo.startswith("Escalada · Datos ilegibles") and "R13" in d.motivo


def test_identificadores_desde_pdf():
    doc = leer_documento("F10.pdf", (RAIZ / "data" / "facturas" / "F10_datos-del-sur_E-0003-00000077.pdf").read_bytes())
    ids = LX.identificadores_fiscales(doc["texto"], doc["uris"], doc["qrs"])
    assert ids["arca"]["codAut"] == 76412345678901 and ids["cae"] == "76412345678901"


def test_nota_credito_nunca_se_paga():
    ag = _agente()
    s04 = SORP / "S04_traducciones-maya_NC-12.xml"
    d = ag.procesar(s04.name, s04.read_bytes())["decision"]
    assert d.decision == "frenar" and d.motivo.startswith("Frenada · Documento que no es un cobro (R01)")
    assert [r.efecto for r in d.reglas if r.id == "R01"] == ["frenar"]
    # un recibo de pago (CFDI tipo P) tampoco se paga; una nota débito o un tipo raro se le preguntan a una persona
    from kauta.motor import evaluar
    s01 = SORP / "S01_traducciones-maya_TM-455.xml"
    ext = _agente().procesar(s01.name, s01.read_bytes())["extraccion"]
    for tipo, esperado in (("recibo_pago", "frenar"), ("otro", "frenar"), ("nota_debito", "escalar"), ("raro", "escalar"),
                           ("factura", "pagar")):
        r = evaluar({"factura_id": "T1", "extraccion": {**ext, "tipo_documento": tipo}, "hashes": []}, ag.reglas,
                    ag.beneficiarios, [])
        assert r.decision == esperado, (tipo, r.motivo)


def test_ia_normaliza_el_tipo_de_documento():
    from kauta.extractor import normalizar
    assert normalizar({"tipo_documento": "Credit Note"})["tipo_documento"] == "nota_credito"
    assert normalizar({"tipo_documento": "invoice"})["tipo_documento"] == "factura"
    assert normalizar({})["tipo_documento"] == "factura"
    assert normalizar({"tipo_documento": "lo que sea"})["tipo_documento"] == "desconocido"
