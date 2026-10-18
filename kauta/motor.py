"""
Kauta · Motor de reglas determinista.

Principio de diseño: LA IA LEE, EL CÓDIGO DECIDE.
Este módulo no usa ningún modelo de IA. Recibe una factura ya extraída, las reglas de la
empresa, la lista de beneficiarios y el historial del periodo, y devuelve una decisión:

    pagar    -> cumple TODAS las reglas
    frenar   -> incumple una regla dura (no se paga; hay que corregir algo)
    escalar  -> incumple una regla blanda (una persona debe aprobar o rechazar)

Reglas de seguridad del motor:
  1. Lista blanca: solo se paga si TODAS las reglas se cumplen.
  2. Cualquier dato faltante, dudoso o error inesperado lleva a escalar, nunca a pagar.
  3. "Frenar" domina sobre "escalar", y "escalar" domina sobre "pagar".
  4. Es una función pura: misma entrada -> misma salida. Por eso se puede auditar y probar.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field, asdict
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Any

# ---------------------------------------------------------------------------
# Catálogo de reglas
# ---------------------------------------------------------------------------
CATALOGO: dict[str, dict[str, str]] = {
    "R01": {"nombre": "Datos legibles, completos y válidos", "falla": "Datos ilegibles, incompletos o inválidos", "efecto": "escalar"},
    "R02": {"nombre": "Moneda permitida", "falla": "Moneda no permitida", "efecto": "escalar"},
    "R03": {"nombre": "Factura no duplicada", "falla": "Factura duplicada", "efecto": "frenar"},
    "R04": {"nombre": "Un solo cobro por periodo (contrato fijo)", "falla": "Segundo cobro en el periodo", "efecto": "frenar"},
    "R05": {"nombre": "Beneficiario no bloqueado", "falla": "Beneficiario bloqueado", "efecto": "frenar"},
    "R06": {"nombre": "Beneficiario en la lista permitida", "falla": "Beneficiario no registrado", "efecto": "escalar"},
    "R07": {"nombre": "Cuenta de pago igual a la registrada", "falla": "Cuenta de pago distinta", "efecto": "escalar"},
    "R08": {"nombre": "Monto cuadra con lo acordado", "falla": "No cuadra con lo acordado", "efecto": "escalar"},
    "R09": {"nombre": "Dentro del límite máximo por pago", "falla": "Supera el máximo por pago", "efecto": "frenar"},
    "R10": {"nombre": "Dentro del umbral de aprobación humana", "falla": "Supera el umbral de aprobación", "efecto": "escalar"},
    "R11": {"nombre": "Dentro del límite por beneficiario en el periodo", "falla": "Supera el límite del beneficiario", "efecto": "escalar"},
    "R12": {"nombre": "Saldo suficiente en el periodo", "falla": "Saldo insuficiente", "efecto": "frenar"},
    "R13": {"nombre": "Sin instrucciones sospechosas en el documento", "falla": "Instrucción sospechosa en el documento", "efecto": "escalar"},
}
# Orden en que se elige el motivo principal que se muestra a la persona
PRIORIDAD_FRENAR = ["R05", "R03", "R04", "R09", "R12"]
PRIORIDAD_ESCALAR = ["R06", "R13", "R07", "R01", "R08", "R10", "R11", "R02"]
REGLAS_DURAS = [r for r, v in CATALOGO.items() if v["efecto"] == "frenar"]
CAMPOS_CRITICOS = ["beneficiario", "numero_factura", "moneda", "monto"]
ESTADOS_ACTIVOS = ("pagada", "aprobada", "pendiente")  # cuentan para "un solo cobro por periodo"
COMPROMETIDOS = ("pagada", "aprobada")  # dinero ya comprometido: pagado o aprobado a la espera del pago
# Documentos que no piden un pago: nunca se pagan, ni con aprobación (R01 se vuelve regla dura)
NO_ES_COBRO = {
    "nota_credito": "una nota crédito: reduce o anula lo que se le debe al proveedor; se aplica a su factura, no se paga",
    "recibo_pago": "un recibo o complemento de pago: confirma un pago ya hecho, no pide uno nuevo",
    "otro": "un comprobante que no es un cobro (cotización, proforma, traslado, nómina o estado de cuenta)",
    "por_cobrar": "una factura de venta que emitió la propia empresa a un cliente: es una cuenta por cobrar, no un pago",
}
# Documentos que pueden ser un cobro, pero que una persona debe confirmar
REVISAR_TIPO = {
    "nota_debito": "una nota débito: aumenta lo que se debe por otra factura; una persona debe confirmarla contra esa factura",
    "documento_soporte": "un documento soporte, que en Colombia emite el comprador y no el proveedor; una persona debe revisarlo",
    "desconocido": "un documento de tipo no reconocido; una persona debe confirmar que es un cobro",
}
CENT = Decimal("0.01")


@dataclass
class ResultadoRegla:
    id: str
    nombre: str
    efecto: str          # "frenar" | "escalar"
    estado: str          # "cumple" | "falla" | "no_aplica"
    detalle: str


@dataclass
class Decision:
    factura_id: str
    decision: str        # "pagar" | "frenar" | "escalar"
    motivo: str
    reglas: list[ResultadoRegla] = field(default_factory=list)
    beneficiario_id: str | None = None
    beneficiario_nombre: str | None = None
    monto: float | None = None
    moneda: str | None = None
    monto_usd: float | None = None
    periodo: str | None = None
    saldo_antes_usd: float | None = None
    version_reglas: int | None = None

    def fallas(self, efecto: str | None = None) -> list[ResultadoRegla]:
        return [r for r in self.reglas if r.estado == "falla" and (efecto is None or r.efecto == efecto)]

    def a_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def fmt_dinero(valor: Decimal | float | None, moneda: str = "USD") -> str:
    """1234.5 -> 'USD 1.234,50' (formato colombiano). COP sin decimales."""
    if valor is None:
        return "—"
    v = Decimal(str(valor))
    dec = 0 if moneda == "COP" else 2
    s = f"{v:,.{dec}f}".replace(",", "§").replace(".", ",").replace("§", ".")
    return f"{moneda} {s}"


def fmt_pct(v: Decimal) -> str:
    s = f"{v:+.1f}".replace(".", ",")
    return f"{s} %"


def normalizar_id(s: str | None) -> str:
    if not s:
        return ""
    s = s.upper()
    s = re.sub(r"\b(NIT|C\.?\s?C\.?|RFC|CUIT|EIN|CC)\b", "", s)
    return re.sub(r"[^A-Z0-9]", "", s)


def normalizar_texto(s: str | None) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", s)


def a_decimal(v: Any) -> Decimal | None:
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError):
        return None


def monto_en_usd(monto: Decimal | None, moneda: str | None, reglas: dict) -> Decimal | None:
    if monto is None or not moneda:
        return None
    tasa = reglas.get("tasas_cambio", {}).get(moneda)
    if tasa in (None, 0):
        return None
    return (monto / Decimal(str(tasa))).quantize(CENT, ROUND_HALF_UP)


def buscar_beneficiario(ext: dict, beneficiarios: list[dict]) -> tuple[dict | None, str]:
    """Identifica al beneficiario por identificación fiscal; si no hay, por nombre exacto."""
    b = ext.get("beneficiario") or {}
    idf = normalizar_id(b.get("id_fiscal"))
    if idf:
        for x in beneficiarios:
            if normalizar_id(x.get("id_fiscal")) == idf:
                return x, "identificación fiscal"
    nom = normalizar_texto(b.get("nombre"))
    if nom:
        for x in beneficiarios:
            if normalizar_texto(x.get("nombre")) == nom:
                if idf:  # mismo nombre pero otra identificación: no se confía
                    return None, "nombre coincide pero la identificación fiscal no"
                return x, "nombre"
    return None, "sin coincidencia"


def presupuesto_de(reglas: dict, periodo: str | None) -> Decimal:
    """El presupuesto del periodo: el general, salvo que las reglas fijen uno propio para ese mes."""
    propio = (reglas.get("presupuestos_periodo") or {}).get(periodo or "")
    return Decimal(str(propio if propio is not None else reglas["presupuesto_periodo_usd"]))


def periodo_de(ext: dict, reglas: dict) -> str:
    f = ext.get("fecha_emision")
    if isinstance(f, str) and re.match(r"^\d{4}-\d{2}", f):
        return f[:7]
    return reglas.get("periodo_actual", "")


def clave_beneficiario(ben: dict | None, ext: dict) -> str:
    if ben:
        return ben["id"]
    b = ext.get("beneficiario") or {}
    return "?" + (normalizar_id(b.get("id_fiscal")) or normalizar_texto(b.get("nombre")))


# ---------------------------------------------------------------------------
# Evaluación
# ---------------------------------------------------------------------------
def evaluar(factura: dict, reglas: dict, beneficiarios: list[dict], historial: list[dict]) -> Decision:
    """
    factura: {"factura_id", "extraccion": {...}, "hashes": [...]}
    historial: registros previos del agente, cada uno con
        {"factura_id","beneficiario_clave","numero_factura","periodo","estado","monto_usd","hashes"}
    """
    try:
        return _evaluar(factura, reglas, beneficiarios, historial)
    except Exception as e:  # Regla 2: ante un error inesperado se escala, nunca se paga
        return Decision(
            factura_id=factura.get("factura_id", "?"), decision="escalar",
            motivo=f"Escalada: error inesperado al evaluar ({type(e).__name__}). Una persona debe revisarla.",
            reglas=[], version_reglas=reglas.get("version"))


def _evaluar(factura: dict, reglas: dict, beneficiarios: list[dict], historial: list[dict]) -> Decision:
    fid = factura["factura_id"]
    ext = factura.get("extraccion") or {}
    hashes = set(factura.get("hashes") or [])
    conf = ext.get("confianza") or {}
    minimo = float(reglas["confianza_minima"])
    b_ext = ext.get("beneficiario") or {}
    nombre_ext = b_ext.get("nombre") or "beneficiario sin nombre"
    moneda = (ext.get("moneda") or "").upper() or None
    monto = a_decimal(ext.get("monto"))
    monto_usd = monto_en_usd(monto, moneda, reglas)
    periodo = periodo_de(ext, reglas)
    numero = (ext.get("numero_factura") or "").strip()
    ben, via = buscar_beneficiario(ext, beneficiarios)
    clave = clave_beneficiario(ben, ext)
    otros = [h for h in historial if h.get("factura_id") != fid]

    pagado_periodo = sum((Decimal(str(h["monto_usd"])) for h in otros
                          if h.get("estado") in COMPROMETIDOS and h.get("periodo") == periodo and h.get("monto_usd") is not None),
                         Decimal("0"))
    presupuesto = presupuesto_de(reglas, periodo)
    saldo = presupuesto - pagado_periodo

    res: list[ResultadoRegla] = []

    def add(rid: str, estado: str, detalle: str) -> None:
        res.append(ResultadoRegla(rid, CATALOGO[rid]["nombre"], CATALOGO[rid]["efecto"], estado, detalle))

    # R01 · Datos legibles, completos y válidos (y que el documento sea un cobro)
    tipo_doc = str(ext.get("tipo_documento") or "factura").lower()
    if tipo_doc not in NO_ES_COBRO and tipo_doc not in REVISAR_TIPO and tipo_doc not in ("factura", "cuenta_cobro"):
        tipo_doc = "desconocido"
    faltan = []
    if not b_ext.get("nombre"):
        faltan.append("beneficiario")
    if not numero:
        faltan.append("número de factura")
    if not moneda:
        faltan.append("moneda")
    if monto is None:
        faltan.append("monto")
    dudosos = [c for c in CAMPOS_CRITICOS if float(conf.get(c, 0) or 0) < minimo]
    validaciones = ext.get("validaciones") or []
    invalidas = [v for v in validaciones if v.get("valido") is False]
    superadas = [v for v in validaciones if v.get("valido") is True]
    min_txt = f"{minimo:.2f}".replace(".", ",")
    if tipo_doc in NO_ES_COBRO:
        res.append(ResultadoRegla("R01", CATALOGO["R01"]["nombre"], "frenar", "falla",
                                  f"El documento es {NO_ES_COBRO[tipo_doc]}. Kauta no lo paga, ni siquiera con aprobación."))
    elif invalidas:
        detalle = " ".join(v["detalle"].rstrip(".") + "." for v in invalidas)
        if any(v.get("campo") == "seguridad" for v in invalidas):
            add("R01", "falla", f"{detalle} Pida al proveedor el documento original por otro canal.")
        else:
            add("R01", "falla", f"No supera la validación: {detalle} Puede ser un error de lectura o un documento "
                                "alterado; una persona debe verificarlo.")
    elif faltan:
        add("R01", "falla", f"Faltan datos críticos: {', '.join(faltan)}. Una persona debe completarlos.")
    elif tipo_doc in REVISAR_TIPO:
        add("R01", "falla", f"El documento es {REVISAR_TIPO[tipo_doc]}.")
    elif dudosos:
        partes = ", ".join(f"{c.replace('_', ' ')} (confianza {float(conf.get(c, 0)):.2f})".replace(".", ",") for c in dudosos)
        add("R01", "falla", f"La lectura no es confiable en: {partes}; el mínimo es {min_txt}. "
                            "Una persona debe verificarla en el documento.")
    else:
        base = ("Datos tomados del XML fiscal, sin IA: son exactos." if ext.get("metodo_lectura") == "xml_fiscal"
                else f"Los campos críticos se leyeron con confianza de al menos {min_txt}.")
        extra = (f" Validaciones superadas ({len(superadas)}): " + "; ".join(v["campo"].replace("_", " ") for v in superadas) + "."
                 if superadas else "")
        add("R01", "cumple", base + extra)

    # R02 · Moneda permitida
    permitidas = reglas.get("monedas_permitidas", [])
    if not moneda:
        add("R02", "no_aplica", "No se identificó la moneda.")
    elif moneda not in permitidas or monto_usd is None and monto is not None:
        add("R02", "falla", f"La moneda {moneda} no está permitida o no tiene tasa de cambio (permitidas: {', '.join(permitidas)}).")
    else:
        add("R02", "cumple", f"{moneda} es una moneda permitida.")

    # R03 · Factura no duplicada: mismo identificador fiscal (CUFE, UUID, CAE), mismo documento o mismo número
    uid = (ext.get("id_fiscal_unico") or "").lower()
    dup, como = None, ""
    for h in otros:
        if uid and (h.get("id_fiscal_unico") or "").lower() == uid:
            dup, como = h, f"el mismo identificador fiscal ({ext.get('tipo_id_unico') or 'ID'} {uid[:12]}…)"
        elif hashes and hashes.intersection(set(h.get("hashes") or [])):
            dup, como = h, "el mismo documento (huella SHA-256 idéntica)"
        elif numero and h.get("beneficiario_clave") == clave and normalizar_id(h.get("numero_factura")) == normalizar_id(numero):
            dup, como = h, "el mismo número de factura del mismo beneficiario"
        if dup:
            break
    if dup:
        add("R03", "falla", f"La factura {numero or '(sin número)'} de {nombre_ext} ya está registrada como {dup['factura_id']} "
                            f"(estado: {dup['estado']}). Se detectó {como}; pagarla de nuevo sería un cobro duplicado.")
    else:
        add("R03", "cumple", f"No hay otra factura {numero} de este beneficiario, ni el mismo documento"
                             + (" ni el mismo identificador fiscal" if uid else "") + " en el historial.")

    # R04 · Un solo cobro por periodo en contratos fijos mensuales
    contrato = (ben or {}).get("contrato") or {}
    if not ben:
        add("R04", "no_aplica", "Beneficiario no registrado: no hay contrato con qué comparar.")
    elif contrato.get("tipo") == "orden_compra":
        add("R04", "no_aplica", f"Compra con orden {contrato.get('referencia') or 'registrada'}: el monto se valida contra la orden (R08).")
    elif contrato.get("tipo") != "fijo_mensual":
        add("R04", "no_aplica", "Contrato por horas: admite varios cobros en el periodo.")
    else:
        previo = next((h for h in otros if h.get("beneficiario_clave") == clave and h.get("periodo") == periodo
                       and h.get("estado") in ESTADOS_ACTIVOS), None)
        if previo:
            add("R04", "falla", f"El contrato de {ben['nombre']} es fijo mensual y ya tiene un cobro en {periodo}: "
                                f"{previo['factura_id']} (factura {previo.get('numero_factura')}, {previo['estado']}).")
        else:
            add("R04", "cumple", f"Es el primer cobro de {ben['nombre']} en {periodo}.")

    # R05 · Beneficiario no bloqueado
    if ben and ben.get("estado") == "bloqueado":
        add("R05", "falla", f"{ben['nombre']} está bloqueado por la empresa. Motivo: {ben.get('motivo_bloqueo') or 'sin detalle'}")
    else:
        add("R05", "cumple", "El beneficiario no está en la lista de bloqueados.")

    # R06 · Beneficiario en la lista permitida
    if ben and ben.get("estado") == "activo":
        add("R06", "cumple", f"{ben['nombre']} ({ben['id']}) está en la lista permitida; identificado por {via}.")
    elif ben and ben.get("estado") == "bloqueado":
        add("R06", "no_aplica", "Beneficiario bloqueado (ver R05).")
    else:
        idf = b_ext.get("id_fiscal") or "sin identificación"
        nota = (" El nombre coincide con un beneficiario registrado, pero la identificación fiscal no."
                if via.startswith("nombre coincide") else "")
        add("R06", "falla", f"{nombre_ext} ({idf}) no está en la lista de beneficiarios permitidos.{nota} "
                            "Una persona debe validarlo antes del primer pago.")

    # R07 · Cuenta de pago igual a la registrada
    cuenta = re.sub(r"\D", "", str(ext.get("cuenta_destino") or ""))[-4:]
    if not ben or ben.get("estado") != "activo":
        add("R07", "no_aplica", "Sin beneficiario activo con qué comparar la cuenta.")
    elif not cuenta:
        add("R07", "cumple", f"La factura no pide otra cuenta: se paga solo a la registrada (…{ben.get('cuenta_registrada')}).")
    elif cuenta != str(ben.get("cuenta_registrada")):
        add("R07", "falla", f"La factura pide pagar a la cuenta terminada en {cuenta}, pero la registrada termina en "
                            f"{ben.get('cuenta_registrada')}. Un cambio de cuenta lo debe confirmar una persona.")
    else:
        add("R07", "cumple", f"La cuenta de destino (…{cuenta}) coincide con la registrada.")

    # R08 · Monto cuadra con lo acordado
    tol = Decimal(str(reglas["tolerancia_contrato_pct"]))
    if not ben or ben.get("estado") != "activo" or not contrato:
        add("R08", "no_aplica", "Sin contrato registrado con qué comparar.")
    elif monto is None or monto_usd is None:
        add("R08", "no_aplica", "Monto no disponible.")
    else:
        if contrato.get("tipo") == "fijo_mensual":
            acordado, mon_c = Decimal(str(contrato["monto"])), contrato["moneda"]
            base = "fijo mensual"
        elif contrato.get("tipo") == "orden_compra":
            acordado, mon_c = Decimal(str(contrato["monto"])), contrato["moneda"]
            base = f"orden de compra {contrato.get('referencia') or ''}".strip()
        else:
            horas = a_decimal(ext.get("horas"))
            if horas is None:
                acordado = None
            else:
                acordado, mon_c = horas * Decimal(str(contrato["tarifa_hora"])), contrato["moneda"]
                base = f"{fmt_num(horas)} h × {fmt_dinero(contrato['tarifa_hora'], mon_c)}"
        if acordado is None:
            add("R08", "falla", f"La factura no indica horas; no se puede verificar contra la tarifa de "
                                f"{fmt_dinero(contrato['tarifa_hora'], contrato['moneda'])} por hora.")
        else:
            acordado_usd = monto_en_usd(acordado, mon_c, reglas)
            dif = ((monto_usd - acordado_usd) / acordado_usd * 100) if acordado_usd else Decimal("100")
            texto = (f"{fmt_dinero(monto, moneda)} frente a {fmt_dinero(acordado, mon_c)} acordados ({base}); "
                     f"diferencia {fmt_pct(dif)}, tolerancia ±{fmt_num(tol, 0)} %.")
            add("R08", "cumple" if abs(dif) <= tol else "falla", texto)

    # R09 · Límite máximo por pago
    maximo = Decimal(str(reglas["limite_maximo_pago_usd"]))
    if monto_usd is None:
        add("R09", "no_aplica", "Monto no disponible.")
    elif monto_usd > maximo:
        add("R09", "falla", f"{fmt_dinero(monto_usd)} supera el límite máximo por pago ({fmt_dinero(maximo)}). "
                            "Ningún pago de este tamaño se aprueba en la plataforma.")
    else:
        add("R09", "cumple", f"{fmt_dinero(monto_usd)} está dentro del máximo por pago ({fmt_dinero(maximo)}).")

    # R10 · Umbral de aprobación humana
    umbral = Decimal(str(reglas["umbral_aprobacion_usd"]))
    if monto_usd is None:
        add("R10", "no_aplica", "Monto no disponible.")
    elif monto_usd > umbral:
        add("R10", "falla", f"{fmt_dinero(monto_usd)} supera el umbral de aprobación humana ({fmt_dinero(umbral)}).")
    else:
        add("R10", "cumple", f"{fmt_dinero(monto_usd)} no supera el umbral de aprobación ({fmt_dinero(umbral)}).")

    # R11 · Límite por beneficiario en el periodo
    lim_b = Decimal(str(reglas["limite_beneficiario_periodo_usd"]))
    if monto_usd is None or not ben:
        add("R11", "no_aplica", "Monto o beneficiario no disponible.")
    else:
        acumulado = sum((Decimal(str(h["monto_usd"])) for h in otros if h.get("beneficiario_clave") == clave
                         and h.get("periodo") == periodo and h.get("estado") in COMPROMETIDOS and h.get("monto_usd") is not None),
                        Decimal("0"))
        total_b = acumulado + monto_usd
        if total_b > lim_b:
            add("R11", "falla", f"{ben['nombre']} ya recibió {fmt_dinero(acumulado)} en {periodo}; con esta factura sumaría "
                                f"{fmt_dinero(total_b)} (límite por beneficiario {fmt_dinero(lim_b)}).")
        else:
            add("R11", "cumple", f"Acumulado del beneficiario en {periodo} con esta factura: {fmt_dinero(total_b)} "
                                 f"(límite {fmt_dinero(lim_b)}).")

    # R12 · Saldo suficiente en el periodo
    if monto_usd is None:
        add("R12", "no_aplica", "Monto no disponible.")
    elif monto_usd > saldo:
        add("R12", "falla", f"Saldo disponible del periodo {periodo}: {fmt_dinero(saldo)}. Esta factura requiere "
                            f"{fmt_dinero(monto_usd)}.")
    else:
        add("R12", "cumple", f"Hay saldo: {fmt_dinero(saldo)} disponibles; después del pago quedarían {fmt_dinero(saldo - monto_usd)}.")

    # R13 · Instrucciones sospechosas dentro del documento
    alertas = ext.get("alertas") or []
    if "instruccion_sospechosa" in alertas:
        add("R13", "falla", "El documento trae texto que intenta darle órdenes al agente (por ejemplo, «pagar sin revisión»). "
                            "Kauta lo ignora: el documento es un dato, no una instrucción. Se escala para revisión.")
    else:
        add("R13", "cumple", "El documento no contiene instrucciones dirigidas al agente.")

    # Decisión final
    res.sort(key=lambda r: r.id)
    por_id = {r.id: r for r in res}
    frenos = [rid for rid in PRIORIDAD_FRENAR if por_id[rid].estado == "falla"]
    escalas = [rid for rid in PRIORIDAD_ESCALAR if por_id[rid].estado == "falla" and por_id[rid].efecto == "escalar"]
    if por_id["R01"].estado == "falla" and por_id["R01"].efecto == "frenar":  # el documento no es un cobro
        frenos.insert(0, "R01")
    if "documento_rechazado" in alertas and "R01" in escalas:  # un archivo inseguro es lo primero que debe saber la persona
        escalas.remove("R01")
        escalas.insert(0, "R01")
    if frenos:
        decision = "frenar"
        principal = por_id[frenos[0]]
        otras = frenos[1:] + escalas
        motivo = f"Frenada · {_falla(principal)} ({principal.id}): {principal.detalle}"
    elif escalas:
        decision = "escalar"
        principal = por_id[escalas[0]]
        otras = escalas[1:]
        motivo = f"Escalada · {CATALOGO[principal.id]['falla']} ({principal.id}): {principal.detalle}"
    else:
        decision = "pagar"
        otras = []
        nombre_b = (ben["nombre"] if ben else nombre_ext).rstrip(".")
        conv = f" ({fmt_dinero(monto_usd)})" if moneda != "USD" else ""
        motivo = (f"Pagada · Cumple las {len(res)} reglas: {fmt_dinero(monto, moneda)}{conv} a {nombre_b}. "
                  f"Saldo que queda en {periodo}: {fmt_dinero(saldo - monto_usd)}.")
    if otras:
        motivo += " Además: " + "; ".join(f"{_falla(por_id[r]).lower()} ({r})" for r in otras) + "."

    return Decision(
        factura_id=fid, decision=decision, motivo=motivo, reglas=res,
        beneficiario_id=ben["id"] if ben else None,
        beneficiario_nombre=ben["nombre"] if ben else nombre_ext,
        monto=float(monto) if monto is not None else None, moneda=moneda,
        monto_usd=float(monto_usd) if monto_usd is not None else None,
        periodo=periodo, saldo_antes_usd=float(saldo), version_reglas=reglas.get("version"),
    )


def _falla(r: ResultadoRegla) -> str:
    if r.id == "R01" and r.efecto == "frenar":
        return "Documento que no es un cobro"
    return CATALOGO[r.id]["falla"]


def fmt_num(v: Decimal | float, dec: int = 1) -> str:
    d = Decimal(str(v))
    if d == d.to_integral():
        return f"{int(d)}"
    return f"{d:.{dec}f}".replace(".", ",")


def revisar_reglas_duras(factura: dict, reglas: dict, beneficiarios: list[dict], historial: list[dict]) -> Decision:
    """Se usa cuando una persona aprueba: solo bloquean las reglas duras (frenar)."""
    return evaluar(factura, reglas, beneficiarios, historial)
