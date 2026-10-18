"""
Simulador de pagos: rieles, cambio de moneda, comisiones, confirmación de titular y liquidación.

Ningún pago sale de verdad: todo ocurre en el libro mayor de la wallet con referencias simuladas.
Aun así, cada pago pasa por los mismos controles que tendría en producción:

  1. Re-verificación de las firmas de TODAS las aprobaciones humanas (si el monto, la cuenta o el
     documento cambiaron después de aprobar, el pago se bloquea).
  2. Confirmación de titular (CoP): el nombre que devuelve el directorio de la cuenta debe ser el
     del beneficiario registrado.
  3. Doble verificación de saldo: la regla R12 del motor y el saldo real de la sub-wallet.
  4. Idempotencia: una clave única por pago; reintentar nunca paga dos veces.
  5. La base de datos impide dos pagos vivos para la misma factura (índice único parcial).
"""
from __future__ import annotations

import random
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from kauta.motor import fmt_dinero
from kauta.normalizacion import clave_nombre

from ..modelos import Aprobacion, Beneficiario, Factura, Pago, ahora
from ..seguridad import firma
from ..seguridad.cifrado import descifrar
from . import auditoria, paypal, wallet

CENT = Decimal("0.01")

RIELES: dict[str, dict[str, Any]] = {
    "ACH": {"nombre": "ACH", "region": "Estados Unidos", "moneda": "USD", "comision": "0.50", "spread": "0",
            "liquidacion": "Mismo día (same-day ACH) o día hábil siguiente", "segundos": 6,
            "disponibilidad": "Días hábiles, por ventanas de corte", "referencia": "Número de rastreo (trace number)",
            "requisitos": "Routing ABA de 9 dígitos con dígito de control y número de cuenta",
            "devolucion": "ACH R03: no existe la cuenta o no se pudo ubicar"},
    "WIRE": {"nombre": "Wire doméstico (Fedwire)", "region": "Estados Unidos", "moneda": "USD", "comision": "15.00",
             "spread": "0", "liquidacion": "Minutos, en horario de Fedwire", "segundos": 4, "disponibilidad": "Días hábiles",
             "referencia": "IMAD", "requisitos": "Routing ABA y número de cuenta",
             "devolucion": "Wire devuelto por el banco receptor: cuenta cerrada"},
    "SWIFT": {"nombre": "Transferencia internacional SWIFT", "region": "Internacional", "moneda": "USD", "comision": "25.00",
              "spread": "0", "liquidacion": "1 a 2 días hábiles (seguimiento SWIFT gpi)", "segundos": 8,
              "disponibilidad": "Días hábiles", "referencia": "UETR (identificador único de extremo a extremo)",
              "requisitos": "Código SWIFT/BIC del banco y cuenta del beneficiario",
              "devolucion": "MT103 rechazado por el banco intermediario: datos del beneficiario incompletos"},
    "SPEI": {"nombre": "SPEI", "region": "México", "moneda": "MXN", "comision": "0.30", "spread": "0.004",
             "liquidacion": "Segundos, 24/7", "segundos": 3, "disponibilidad": "24/7", "referencia": "Clave de rastreo",
             "requisitos": "CLABE de 18 dígitos con dígito de control",
             "devolucion": "SPEI devuelto: la CLABE no pertenece al titular"},
    "BREB": {"nombre": "Bre-B", "region": "Colombia", "moneda": "COP", "comision": "0.00", "spread": "0.005",
             "liquidacion": "Segundos, 24/7", "segundos": 3, "disponibilidad": "24/7",
             "referencia": "Identificador de extremo a extremo", "requisitos": "Llave Bre-B (celular, documento, correo o alfanumérica)",
             "devolucion": "Bre-B rechazado: la llave no existe en el directorio"},
    "ACH_CO": {"nombre": "Transferencia ACH Colombia", "region": "Colombia", "moneda": "COP", "comision": "0.40",
               "spread": "0.005", "liquidacion": "Mismo día, por ciclos de compensación", "segundos": 5,
               "disponibilidad": "Días hábiles", "referencia": "Número de transacción",
               "requisitos": "Banco, tipo y número de cuenta", "devolucion": "ACH Colombia: cuenta inactiva"},
    "PIX": {"nombre": "Pix", "region": "Brasil", "moneda": "BRL", "comision": "0.00", "spread": "0.005",
            "liquidacion": "Segundos, 24/7", "segundos": 3, "disponibilidad": "24/7", "referencia": "EndToEndId",
            "requisitos": "Chave Pix (CPF/CNPJ, correo, teléfono o aleatoria)", "devolucion": "Pix devuelto (MED)"},
    "USDC": {"nombre": "Stablecoin USDC (alternativa)", "region": "Global", "moneda": "USD", "comision": "0.05",
             "spread": "0", "liquidacion": "Minutos, 24/7", "segundos": 4, "disponibilidad": "24/7",
             "referencia": "Hash de la transacción", "requisitos": "Dirección de billetera verificada del beneficiario",
             "devolucion": "Transacción revertida: dirección no verificada"},
    "PAYPAL": {"nombre": "PayPal (pruebas)", "region": "Global · sandbox", "moneda": "USD", "comision": "20.00", "comision_pct": "0.02",
               "spread": "0", "liquidacion": "Segundos a minutos (PayPal Payouts)", "segundos": 4, "disponibilidad": "24/7",
               "referencia": "Lote de PayPal (payout_batch_id)",
               "requisitos": "Correo de una cuenta PayPal; en pruebas, la cuenta personal del sandbox",
               "devolucion": "PayPal devolvió el pago: la cuenta receptora no pudo recibirlo"},
}
MONEDA_FIJA = {"PAYPAL": "USD"}   # PayPal paga en dólares, sin importar la moneda en que recibe el proveedor por banco
RIEL_PAGOS = "PAYPAL"             # las facturas se pagan por PayPal; los demás rieles quedan para reintentos y pruebas


def _referencia(riel: str, rnd: random.Random) -> str:
    hoy = datetime.now(timezone.utc).strftime("%Y%m%d")
    al = lambda n, abc="ABCDEFGHJKLMNPQRSTUVWXYZ23456789": "".join(rnd.choice(abc) for _ in range(n))
    if riel == "ACH":
        return "13" + "".join(rnd.choice("0123456789") for _ in range(13))
    if riel == "WIRE":
        return f"{hoy}KAUT{al(4)}{rnd.randint(0, 999999):06d}"
    if riel == "SWIFT":
        return str(uuid.UUID(int=rnd.getrandbits(128), version=4))
    if riel == "SPEI":
        return f"KAUTA{hoy}{al(8)}"
    if riel == "BREB":
        return f"E{hoy}KAUTA{al(19)}"
    if riel == "PIX":
        return f"E99999999{datetime.now(timezone.utc).strftime('%Y%m%d%H%M')}{al(11)}"
    if riel == "USDC":
        return "0x" + "".join(rnd.choice("0123456789abcdef") for _ in range(64))
    if riel == "PAYPAL":
        return "SIM" + al(14)
    return f"CO{hoy}{rnd.randint(0, 99999999):08d}"


def cotizar(bd_reglas: dict[str, Any], factura: Factura, ben: Beneficiario, riel: str) -> dict[str, Any]:
    """Calcula lo que recibe el beneficiario y lo que cuesta, en USD, enviarlo por el riel."""
    info = RIELES[riel]
    tasas = {k: Decimal(str(v)) for k, v in bd_reglas.get("tasas_cambio", {}).items() if not k.startswith("_")}
    monto_usd = Decimal(factura.monto_usd)
    destino = MONEDA_FIJA.get(riel, ben.moneda_recepcion)
    ref = tasas.get(destino, Decimal("1"))
    spread = Decimal(info["spread"]) if destino != "USD" else Decimal("0")
    if factura.moneda == destino:
        monto_destino = Decimal(factura.monto)
    else:
        monto_destino = (monto_usd * ref).quantize(CENT, ROUND_HALF_UP)
    aplicada = (ref * (1 - spread)).quantize(Decimal("0.000001"))
    costo_real = (monto_destino / aplicada).quantize(CENT, ROUND_HALF_UP) if destino != "USD" else monto_usd
    comision = Decimal(info["comision"])
    if "comision_pct" in info:      # porcentaje con tope (estimación: el sandbox de PayPal no cobra)
        comision = min(monto_usd * Decimal(info["comision_pct"]), comision).quantize(CENT, ROUND_HALF_UP)
    return {"monto_destino": monto_destino, "moneda_destino": destino, "tasa_referencia": ref, "tasa_aplicada": aplicada,
            "costo_fx_usd": max(Decimal("0"), costo_real - monto_usd).quantize(CENT), "comision_usd": comision}


def confirmar_titular(ben: Beneficiario) -> tuple[bool, str]:
    """Confirmación de titular (Confirmation of Payee): el directorio devuelve el nombre de la cuenta."""
    ok = clave_nombre(ben.titular_registrado) == clave_nombre(ben.nombre)
    return ok, ben.titular_registrado


def datos_aprobacion(f: Factura, ben_id: str | None, cuenta4: str, usuario_id: int, nivel: int, accion: str,
                     ts: str) -> dict[str, Any]:
    return {"factura_id": f.id, "beneficiario_id": ben_id, "monto": str(f.monto), "moneda": f.moneda,
            "monto_usd": str(f.monto_usd), "cuenta_ultimos4": cuenta4, "hash_documento": f.hash_documento,
            "version_reglas": f.version_reglas, "riel_pago": f.riel_pago or "", "usuario_id": usuario_id, "nivel": nivel,
            "accion": accion, "ts": ts}


def verificar_aprobaciones(bd: Session, f: Factura, ben: Beneficiario) -> list[str]:
    """Recalcula cada firma con los datos ACTUALES de la factura. Devuelve los problemas encontrados."""
    problemas = []
    for a in bd.execute(select(Aprobacion).where(Aprobacion.factura_id == f.id, Aprobacion.accion == "aprobar")).scalars():
        actual = datos_aprobacion(f, ben.id, ben.cuenta_ultimos4, a.usuario_id, a.nivel, "aprobar", a.datos_firmados.get("ts"))
        if not firma.verificar(actual, a.firma):
            problemas.append(f"La aprobación de {a.usuario_nombre} ya no coincide con los datos actuales "
                             "(monto, cuenta o documento cambiaron después de aprobar).")
    return problemas


def rieles_publicos() -> list[dict[str, Any]]:
    """Los rieles para la pantalla; PayPal dice si envía al sandbox de verdad o si está simulado."""
    salida = []
    for codigo, info in RIELES.items():
        d = {"codigo": codigo, **info}
        if codigo == "PAYPAL":
            d |= {"modo": paypal.modo(), "receptor": paypal.receptor_enmascarado() if paypal.configurado() else None}
        salida.append(d)
    return salida


def nuevo_id(bd: Session) -> str:
    n = bd.execute(select(func.count()).select_from(Pago)).scalar_one() + 1
    return f"PAG-{n:06d}"


def crear_y_ejecutar(bd: Session, f: Factura, reglas: dict[str, Any], actor: str, forzar: str | None = None,
                     riel: str | None = None, intento: int = 1) -> Pago:
    ben = bd.get(Beneficiario, f.beneficiario_id) if f.beneficiario_id else None
    if not ben or ben.estado != "activo":
        raise ValueError("Solo se paga a beneficiarios registrados y activos.")
    problemas = verificar_aprobaciones(bd, f, ben)
    if problemas:
        raise ValueError(problemas[0])
    riel = riel or RIEL_PAGOS
    if riel not in RIELES:
        raise ValueError(f"Riel desconocido: {riel}.")
    cop_ok, titular = confirmar_titular(ben)
    if not cop_ok:
        raise ValueError(f"Confirmación de titular fallida: la cuenta está a nombre de «{titular}», no de «{ben.nombre}».")
    disponible = wallet.saldo(bd, "cxp")
    monto_usd = Decimal(f.monto_usd).quantize(CENT)
    if monto_usd > disponible:
        raise ValueError(f"La sub-wallet de cuentas por pagar tiene {fmt_dinero(disponible)}; el pago requiere {fmt_dinero(monto_usd)}.")
    clave = f"pago:{f.id}:{f.hash_documento[:16]}:{intento}"
    existente = bd.execute(select(Pago).where(Pago.clave_idempotencia == clave)).scalar_one_or_none()
    if existente:
        return existente  # idempotencia: el mismo intento nunca crea un segundo pago

    c = cotizar(reglas, f, ben, riel)
    destino = c["moneda_destino"]
    rnd = random.Random(secrets.randbits(64))
    pid = nuevo_id(bd)
    referencia = _referencia(riel, rnd)
    cuenta_completa = descifrar(ben.cuenta_cifrada, aad=f"cuenta:{ben.id}")
    es_paypal = riel == "PAYPAL"
    paypal_real = es_paypal and paypal.envio_real() and forzar is None
    instruccion = {"pago": pid, "factura": f.id, "beneficiario": ben.id, "riel": riel, "monto_usd": str(monto_usd),
                   "moneda_destino": destino, "monto_destino": str(c["monto_destino"]),
                   "cuenta_ultimos4": ben.cuenta_ultimos4, "hash_cuenta": firma.huella({"c": cuenta_completa}),
                   "clave_idempotencia": clave}
    if es_paypal:
        instruccion |= {"receptor_paypal": paypal.receptor_enmascarado() if paypal_real else "(simulada)",
                        "modo_paypal": "sandbox" if paypal_real else "simulado"}
    t0 = ahora()
    info = RIELES[riel]
    seg = info["segundos"]
    pasos = [
        {"paso": "creado", "titulo": "Orden de pago creada y firmada", "detalle": f"Firma HMAC {firma.huella(instruccion)} · clave de idempotencia {clave}", "t": 0},
        {"paso": "verificado", "titulo": "Controles previos superados", "detalle": f"Titular confirmado: {titular} · saldo suficiente · firmas de aprobación válidas", "t": 0.4},
        {"paso": "reservado", "titulo": "Fondos reservados en la wallet", "detalle": f"{fmt_dinero(monto_usd)} pasan de la sub-wallet de pagos a reservas", "t": 0.8},
    ]
    p = Pago(id=pid, factura_id=f.id, beneficiario_id=ben.id, beneficiario_nombre=ben.nombre, riel=riel,
             monto_factura=Decimal(f.monto), moneda_factura=f.moneda, monto_usd=monto_usd, moneda_destino=destino,
             monto_destino=c["monto_destino"], tasa_referencia=c["tasa_referencia"], tasa_aplicada=c["tasa_aplicada"],
             comision_usd=c["comision_usd"], costo_fx_usd=c["costo_fx_usd"], cuenta_ultimos4=ben.cuenta_ultimos4,
             titular_confirmado=titular, referencia=referencia, estado="enviado", clave_idempotencia=clave,
             datos_firmados=instruccion, firma=firma.firmar(instruccion), creado_en=t0)
    bd.add(p)
    bd.flush()
    per = f.periodo
    wallet.transferir(bd, "reserva", f"Reserva para {pid} · {f.id} · {ben.nombre}", pid, per, "cxp", "reservas", monto_usd)
    wallet.transferir(bd, "envio", f"Envío por {info['nombre']} · {pid}", pid, per, "reservas", "transito", monto_usd)

    envio = {"paso": "enviado", "titulo": f"Enviado por {info['nombre']}", "detalle": f"{info['referencia']}: {referencia}", "t": 1.4}
    fallo, resultado = None, None
    if paypal_real:
        # El envío real al sandbox: si PayPal no lo acepta, el dinero nunca salió y vuelve a la sub-wallet
        try:
            env = paypal.enviar(f"kauta-{pid}-{secrets.token_hex(6)}", pid, c["monto_destino"], destino,
                                nota=f"Pago de la factura {f.id} ({f.numero or 'sin número'}) de {ben.nombre}",
                                asunto="Brisamar Labs le envió un pago de prueba")
        except paypal.ErrorPayPal as e:
            fallo = str(e)
            envio |= {"titulo": "PayPal no aceptó el envío", "detalle": fallo}
        else:
            p.referencia = referencia = env["lote"]
            envio["detalle"] = f"Lote de PayPal {env['lote']} · sandbox, a la cuenta de pruebas {instruccion['receptor_paypal']}"
            resultado = paypal.esperar_resultado(env["lote"])
    elif es_paypal:
        envio["detalle"] += " · simulado: configure el sandbox de PayPal para enviarlo de verdad"
    pasos.append(envio)
    if not fallo:  # la comisión y el cambio solo se pagan si el dinero salió
        if c["comision_usd"] > 0:
            wallet.transferir(bd, "comision", f"Comisión {info['nombre']} · {pid}", pid, per, "operativa", "comisiones", c["comision_usd"])
        if c["costo_fx_usd"] > 0:
            wallet.transferir(bd, "fx", f"Costo cambiario USD→{destino} · {pid}", pid, per, "operativa", "costos_fx", c["costo_fx_usd"])
    else:
        p.comision_usd = p.costo_fx_usd = Decimal("0")

    if forzar == "devuelto" or fallo or (resultado and resultado["estado"] in paypal.DEVUELTO):
        if fallo:
            motivo = f"PayPal no aceptó el envío: {fallo}"
        elif resultado:
            motivo = f"PayPal devolvió el pago ({resultado['estado']})" + (f": {resultado['error']}" if resultado.get("error") else "")
        else:
            motivo = info["devolucion"]
        _devolver(bd, p, f, motivo, pasos, 1.4 + seg, "Riel de pagos (simulado)" if not paypal_real else "PayPal (sandbox)")
    elif resultado and resultado["estado"] not in paypal.LIQUIDADO:
        pasos.append({"paso": "en_proceso", "titulo": "PayPal está procesando el pago",
                      "detalle": f"Estado en PayPal: {resultado['estado']}. Use «Consultar en PayPal» para actualizarlo.", "t": 1.4 + seg})
    else:
        _liquidar(bd, p, ben, pasos, 1.4 + seg, resultado)
    p.linea_tiempo = pasos
    auditoria.registrar(bd, "pago.creado", actor, "pago", pid,
                        f"{pid}: {fmt_dinero(monto_usd)} a {ben.nombre} por {info['nombre']} ({p.estado})",
                        {"factura": f.id, "riel": riel, "referencia": referencia, "firma": p.firma[:16],
                         "comision_usd": str(p.comision_usd), "costo_fx_usd": str(p.costo_fx_usd),
                         **({"paypal": instruccion["modo_paypal"]} if es_paypal else {})})
    return p


def registrar_negado(bd: Session, f: Factura, ben: Beneficiario, reglas: dict[str, Any], actor: str, motivo: str,
                     intento: int) -> Pago:
    """Un intento de pago que Kauta negó antes de mover dinero: queda en el historial de pagos, sin asientos en el libro."""
    riel = f.riel_pago or RIEL_PAGOS
    c = cotizar(reglas, f, ben, riel)
    pid = nuevo_id(bd)
    monto_usd = Decimal(f.monto_usd).quantize(CENT)
    instruccion = {"pago": pid, "factura": f.id, "beneficiario": ben.id, "riel": riel, "monto_usd": str(monto_usd),
                   "resultado": "negado", "motivo": motivo[:300]}
    pasos = [
        {"paso": "creado", "titulo": "Pago solicitado con token", "detalle": f"{actor} pidió pagar {fmt_dinero(monto_usd)} por {RIELES[riel]['nombre']}", "t": 0},
        {"paso": "negado", "titulo": "Negado: Kauta no movió el dinero", "detalle": motivo, "t": 0.4},
    ]
    p = Pago(id=pid, factura_id=f.id, beneficiario_id=ben.id, beneficiario_nombre=ben.nombre, riel=riel,
             monto_factura=Decimal(f.monto), moneda_factura=f.moneda, monto_usd=monto_usd, moneda_destino=c["moneda_destino"],
             monto_destino=c["monto_destino"], tasa_referencia=c["tasa_referencia"], tasa_aplicada=c["tasa_aplicada"],
             comision_usd=Decimal("0"), costo_fx_usd=Decimal("0"), cuenta_ultimos4=ben.cuenta_ultimos4,
             titular_confirmado=None, referencia="—", estado="negado",
             clave_idempotencia=f"negado:{f.id}:{intento}:{secrets.token_hex(4)}", datos_firmados=instruccion,
             firma=firma.firmar(instruccion), linea_tiempo=pasos, motivo_devolucion=motivo, creado_en=ahora())
    bd.add(p)
    bd.flush()
    auditoria.registrar(bd, "pago.negado", actor, "pago", pid, f"{pid} negado antes de mover dinero: {motivo}"[:400],
                        {"factura": f.id, "monto_usd": str(monto_usd)})
    return p


RESULTADOS = {"liquidado": "exitoso", "enviado": "en_proceso", "reservado": "en_proceso", "devuelto": "fallido", "negado": "negado"}


# ---------------------------------------------------------------------------
# Pago con la ventana de PayPal (Checkout): quien paga lo aprueba o lo rechaza en PayPal
# ---------------------------------------------------------------------------
def iniciar_checkout(bd: Session, f: Factura, reglas: dict[str, Any], actor: str, intento: int,
                     origen: str) -> tuple[Pago, str | None]:
    """
    Reserva el dinero en la wallet y crea la orden en PayPal. Devuelve el pago (en espera) y el enlace de la ventana de
    PayPal. Nada sale de la wallet hasta que PayPal confirma la aprobación y Kauta cobra la orden.
    """
    ben = bd.get(Beneficiario, f.beneficiario_id) if f.beneficiario_id else None
    if not ben or ben.estado != "activo":
        raise ValueError("Solo se paga a beneficiarios registrados y activos.")
    problemas = verificar_aprobaciones(bd, f, ben)
    if problemas:
        raise ValueError(problemas[0])
    cop_ok, titular = confirmar_titular(ben)
    if not cop_ok:
        raise ValueError(f"Confirmación de titular fallida: la cuenta está a nombre de «{titular}», no de «{ben.nombre}».")
    monto_usd = Decimal(f.monto_usd).quantize(CENT)
    disponible = wallet.saldo(bd, "cxp")
    if monto_usd > disponible:
        raise ValueError(f"La sub-wallet de cuentas por pagar tiene {fmt_dinero(disponible)}; el pago requiere {fmt_dinero(monto_usd)}.")
    c = cotizar(reglas, f, ben, "PAYPAL")
    real = paypal.configurado()
    pid = nuevo_id(bd)
    clave = f"checkout:{f.id}:{f.hash_documento[:16]}:{intento}"
    instruccion = {"pago": pid, "factura": f.id, "beneficiario": ben.id, "riel": "PAYPAL", "monto_usd": str(monto_usd),
                   "moneda_destino": c["moneda_destino"], "monto_destino": str(c["monto_destino"]), "metodo": "checkout",
                   "receptor_paypal": "la cuenta Business del sandbox" if real else "(simulada)",
                   "modo_paypal": "sandbox" if real else "simulado", "clave_idempotencia": clave}
    pasos = [
        {"paso": "creado", "titulo": "Orden de pago creada y firmada", "detalle": f"Firma HMAC {firma.huella(instruccion)} · {actor}", "t": 0},
        {"paso": "verificado", "titulo": "Controles previos superados", "detalle": f"Titular confirmado: {titular} · saldo suficiente · aprobación válida", "t": 0.4},
        {"paso": "reservado", "titulo": "Fondos reservados en la wallet", "detalle": f"{fmt_dinero(monto_usd)} apartados mientras usted aprueba en PayPal", "t": 0.8},
    ]
    p = Pago(id=pid, factura_id=f.id, beneficiario_id=ben.id, beneficiario_nombre=ben.nombre, riel="PAYPAL",
             monto_factura=Decimal(f.monto), moneda_factura=f.moneda, monto_usd=monto_usd, moneda_destino=c["moneda_destino"],
             monto_destino=c["monto_destino"], tasa_referencia=c["tasa_referencia"], tasa_aplicada=c["tasa_aplicada"],
             comision_usd=Decimal("0"), costo_fx_usd=Decimal("0"),   # en Checkout la comisión la paga quien cobra
             cuenta_ultimos4=ben.cuenta_ultimos4, titular_confirmado=titular, referencia="(creando orden)", estado="reservado",
             clave_idempotencia=clave, datos_firmados=instruccion, firma=firma.firmar(instruccion), creado_en=ahora())
    bd.add(p)
    bd.flush()
    wallet.transferir(bd, "reserva", f"Reserva para {pid} · {f.id} · {ben.nombre} (esperando PayPal)", pid, f.periodo,
                      "cxp", "reservas", monto_usd)
    enlace = None
    if real:
        try:
            o = paypal.crear_orden(pid, c["monto_destino"], c["moneda_destino"], f"Factura {f.id} {f.numero or ''} · {ben.nombre}",
                                   f"{origen}/api/paypal/volver?pago={pid}", f"{origen}/api/paypal/cancelar?pago={pid}")
        except paypal.ErrorPayPal as e:
            _liberar(bd, p, f, f"PayPal no abrió el pago: {e}", pasos, 1.4, "devuelto")
            p.linea_tiempo = pasos
            return p, None
        p.referencia, enlace = o["orden"], o["aprobar"]
    else:
        p.referencia, enlace = f"SIMORD{secrets.token_hex(5).upper()}", f"/#/pagos/paypal-simulado/{pid}"
    pasos.append({"paso": "en_proceso", "titulo": "Esperando su aprobación en PayPal", "enlace": enlace,
                  "detalle": f"Orden {p.referencia}: Kauta abrió PayPal para que usted apruebe o rechace el pago.", "t": 1.4})
    p.linea_tiempo = pasos
    auditoria.registrar(bd, "pago.checkout_iniciado", actor, "pago", pid,
                        f"{pid}: {fmt_dinero(monto_usd)} a {ben.nombre}; orden {p.referencia} esperando aprobación en PayPal.",
                        {"factura": f.id, "orden": p.referencia, "modo": instruccion["modo_paypal"]})
    return p, enlace


def _liberar(bd: Session, p: Pago, f: Factura, motivo: str, pasos: list[dict[str, Any]], t: float, estado: str) -> None:
    """La reserva vuelve a la sub-wallet: el dinero nunca salió. La factura sigue aprobada y se puede pagar otra vez."""
    wallet.transferir(bd, "liberacion", f"Liberación de {p.id}: {motivo}"[:300], p.id, f.periodo, "reservas", "cxp", p.monto_usd)
    p.estado, p.motivo_devolucion = estado, motivo
    pasos.append({"paso": "negado" if estado == "negado" else "devuelto",
                  "titulo": "Rechazado en PayPal: no se movió dinero" if estado == "negado" else "PayPal no completó el pago",
                  "detalle": motivo + " · la reserva volvió a la sub-wallet", "t": t})
    auditoria.registrar(bd, f"pago.{estado}", "PayPal (sandbox)" if p.datos_firmados.get("modo_paypal") == "sandbox" else "PayPal (simulado)",
                        "pago", p.id, f"{p.id}: {motivo}"[:400], {"factura": f.id})


def completar_checkout(bd: Session, p: Pago, orden: str, aprobado: bool) -> tuple[Pago, str]:
    """PayPal devolvió a la persona: si aprobó, Kauta cobra la orden; si canceló, libera la reserva (pago negado)."""
    if p.datos_firmados.get("metodo") != "checkout" or p.referencia != orden:
        raise ValueError("La orden no corresponde a este pago.")
    if p.estado != "reservado":
        raise ValueError("Este pago ya se resolvió.")
    f = bd.get(Factura, p.factura_id)
    ben = bd.get(Beneficiario, p.beneficiario_id)
    pasos = [x for x in (p.linea_tiempo or []) if x["paso"] != "en_proceso"]
    real = p.datos_firmados.get("modo_paypal") == "sandbox"
    if not aprobado:
        _liberar(bd, p, f, "Quien paga rechazó el pago en la ventana de PayPal", pasos, 2.0, "negado")
        p.linea_tiempo = pasos
        return p, "Pago negado: se rechazó en PayPal y no se movió dinero. La factura sigue lista para pagar."
    try:
        r = paypal.capturar_orden(orden) if real else {"estado": "COMPLETED", "captura": f"SIMCAP{secrets.token_hex(5).upper()}",
                                                       "pagador": "cuenta de pruebas (simulada)"}
    except paypal.ErrorPayPal as e:
        _liberar(bd, p, f, f"PayPal no cobró la orden: {e}", pasos, 2.0, "devuelto")
        p.linea_tiempo = pasos
        return p, f"Pago fallido: {e} El dinero volvió a la wallet; la factura sigue lista para pagar."
    if r["estado"] in paypal.ORDEN_RECHAZADA:
        _liberar(bd, p, f, f"PayPal rechazó el cobro ({r['estado']})", pasos, 2.0, "devuelto")
        p.linea_tiempo = pasos
        return p, f"Pago fallido: PayPal rechazó el cobro ({r['estado']}). El dinero volvió a la wallet."
    wallet.transferir(bd, "envio", f"Cobro por PayPal Checkout · {p.id}", p.id, f.periodo, "reservas", "transito", p.monto_usd)
    pasos.append({"paso": "enviado", "titulo": "Aprobado en PayPal", "t": 2.0,
                  "detalle": f"Orden {orden} aprobada por {r.get('pagador') or 'quien paga'} · cobro {r.get('captura') or '—'}"})
    if r["estado"] in paypal.ORDEN_LIQUIDADA:
        _liquidar(bd, p, ben, pasos, 2.6, {"transaccion": r.get("captura")})
        mensaje = f"Pago exitoso: PayPal confirmó el cobro {r.get('captura')}."
    else:
        p.estado = "enviado"
        pasos.append({"paso": "en_proceso", "titulo": "PayPal está procesando el cobro",
                      "detalle": f"Estado en PayPal: {r['estado']}. Use «Consultar en PayPal» para actualizarlo.", "t": 2.6})
        mensaje = f"Pago en proceso: PayPal dejó el cobro en {r['estado']}."
    f.estado = "pagada"
    aprobacion = re.sub(r"\s*Lista para pagar:.*?en ese momento\.", "", f.motivo or "")
    f.motivo = f"Pagada con la ventana de PayPal · {p.id} (orden {orden}). {aprobacion}"
    p.linea_tiempo = pasos
    auditoria.registrar(bd, "pago.checkout_aprobado", "PayPal (sandbox)" if real else "PayPal (simulado)", "pago", p.id,
                        f"{p.id}: orden {orden} aprobada; cobro {r.get('captura')} ({r['estado']}).", {"factura": f.id})
    return p, mensaje


def _liquidar(bd: Session, p: Pago, ben: Beneficiario, pasos: list[dict[str, Any]], t: float,
              resultado: dict[str, Any] | None = None) -> None:
    info = RIELES[p.riel]
    wallet.transferir(bd, "liquidacion", f"Liquidación {p.id} · {ben.nombre}", p.id, _periodo(bd, p), "transito", "proveedores", p.monto_usd)
    # con PayPal real, la hora en que PayPal confirmó; en los rieles simulados, la del tiempo típico del riel
    p.estado, p.liquidado_en = "liquidado", ahora() if resultado else p.creado_en + timedelta(seconds=info["segundos"])
    if p.riel == "PAYPAL":
        donde = f"en la cuenta PayPal de pruebas {p.datos_firmados.get('receptor_paypal')}"
        if resultado and resultado.get("transaccion"):
            donde += f" · transacción {resultado['transaccion']}"
    else:
        donde = f"en la cuenta ···{ben.cuenta_ultimos4}"
    plazo = "PayPal confirmó el cobro al aprobarlo" if p.datos_firmados.get("metodo") == "checkout" else info["liquidacion"]
    pasos.append({"paso": "liquidado", "titulo": "Liquidado: el beneficiario recibió el dinero",
                  "detalle": f"{fmt_dinero(p.monto_destino, p.moneda_destino)} {donde} · {plazo}", "t": t})


def _devolver(bd: Session, p: Pago, f: Factura, motivo: str, pasos: list[dict[str, Any]], t: float, actor: str) -> None:
    wallet.transferir(bd, "devolucion", f"Devolución de {p.id}: {motivo}"[:300], p.id, f.periodo, "transito", "cxp", p.monto_usd)
    p.estado, p.motivo_devolucion = "devuelto", motivo
    f.estado = "devuelta"
    f.motivo = (f"Devuelta por el riel · {motivo}. Los {fmt_dinero(p.monto_usd)} volvieron a la sub-wallet; "
                "la factura queda para revisión de tesorería (los datos de pago deben verificarse).")
    pasos.append({"paso": "devuelto", "titulo": "Devuelto: el dinero volvió a la wallet", "detalle": motivo + " · fondos reintegrados", "t": t})
    auditoria.registrar(bd, "pago.devuelto", actor, "pago", p.id, f"{p.id} devuelto: {motivo}"[:400],
                        {"factura": f.id, "monto_usd": str(p.monto_usd)})


def _periodo(bd: Session, p: Pago) -> str:
    f = bd.get(Factura, p.factura_id)
    return f.periodo if f else ahora().strftime("%Y-%m")


def _actualizar_checkout(bd: Session, p: Pago, actor: str) -> tuple[Pago, str]:
    """Un pago con la ventana de PayPal que quedó esperando: se pregunta a PayPal por la orden."""
    if p.datos_firmados.get("modo_paypal") != "sandbox" or not paypal.configurado():
        raise ValueError("Este pago no se hizo en el sandbox de PayPal.")
    try:
        r = paypal.consultar_orden(p.referencia)
    except paypal.ErrorPayPal as e:
        raise ValueError(str(e)) from None
    if p.estado == "reservado":
        if r["estado"] == "APPROVED":
            return completar_checkout(bd, p, p.referencia, aprobado=True)
        if r["estado"] in paypal.ORDEN_RECHAZADA:
            return completar_checkout(bd, p, p.referencia, aprobado=False)
        return p, f"PayPal sigue esperando su aprobación ({r['estado']}): abra la ventana de PayPal para aprobar o rechazar."
    if r["estado"] in paypal.ORDEN_LIQUIDADA:
        pasos = [x for x in (p.linea_tiempo or []) if x["paso"] != "en_proceso"]
        _liquidar(bd, p, bd.get(Beneficiario, p.beneficiario_id), pasos, (pasos[-1]["t"] if pasos else 2) + 1, {"transaccion": None})
        p.linea_tiempo = pasos
        return p, f"PayPal confirmó el cobro del pago {p.id}: exitoso."
    return p, f"PayPal sigue procesando el cobro ({r['estado']})."


def actualizar_paypal(bd: Session, p: Pago, actor: str) -> tuple[Pago, str]:
    """Consulta en el sandbox un pago por PayPal que quedó en proceso y lo liquida o lo devuelve."""
    if p.riel == "PAYPAL" and p.datos_firmados.get("metodo") == "checkout" and p.estado in ("reservado", "enviado"):
        return _actualizar_checkout(bd, p, actor)
    if p.riel != "PAYPAL" or p.estado != "enviado":
        raise ValueError("Solo se consultan pagos por PayPal que siguen en proceso.")
    if p.datos_firmados.get("modo_paypal") != "sandbox" or not paypal.configurado():
        raise ValueError("Este pago no se envió al sandbox de PayPal o el servidor ya no tiene sus credenciales.")
    try:
        r = paypal.consultar(p.referencia)
    except paypal.ErrorPayPal as e:
        raise ValueError(str(e)) from None
    pasos = list(p.linea_tiempo or [])
    t = (pasos[-1]["t"] if pasos else 0) + 1
    pasos = [x for x in pasos if x["paso"] != "en_proceso"]
    f = bd.get(Factura, p.factura_id)
    if r["estado"] in paypal.LIQUIDADO:
        _liquidar(bd, p, bd.get(Beneficiario, p.beneficiario_id), pasos, t, r)
        mensaje = f"PayPal confirmó el pago {p.id}: liquidado."
    elif r["estado"] in paypal.DEVUELTO:
        _devolver(bd, p, f, f"PayPal devolvió el pago ({r['estado']})" + (f": {r['error']}" if r.get("error") else ""), pasos, t,
                  "PayPal (sandbox)")
        mensaje = f"PayPal devolvió el pago {p.id}; el dinero volvió a la sub-wallet."
    else:
        pasos.append({"paso": "en_proceso", "titulo": "PayPal está procesando el pago",
                      "detalle": f"Estado en PayPal: {r['estado']}. Vuelva a consultar en unos segundos.", "t": t})
        mensaje = f"PayPal sigue procesando el pago ({r['estado']})."
    p.linea_tiempo = pasos
    auditoria.registrar(bd, "pago.paypal_consultado", actor, "pago", p.id, f"{p.id}: estado en PayPal {r['estado']}.",
                        {"lote": p.referencia, "estado": r["estado"]})
    return p, mensaje


def a_dict(p: Pago) -> dict[str, Any]:
    info = RIELES.get(p.riel, {})
    return {"id": p.id, "factura_id": p.factura_id, "beneficiario_id": p.beneficiario_id, "beneficiario": p.beneficiario_nombre,
            "riel": p.riel, "riel_nombre": info.get("nombre", p.riel), "liquidacion": info.get("liquidacion"),
            "monto_factura": float(p.monto_factura), "moneda_factura": p.moneda_factura, "monto_usd": float(p.monto_usd),
            "moneda_destino": p.moneda_destino, "monto_destino": float(p.monto_destino),
            "tasa_referencia": float(p.tasa_referencia), "tasa_aplicada": float(p.tasa_aplicada),
            "comision_usd": float(p.comision_usd), "costo_fx_usd": float(p.costo_fx_usd),
            "costo_total_usd": float(p.monto_usd + p.comision_usd + p.costo_fx_usd),
            "cuenta": (f"PayPal {p.datos_firmados.get('receptor_paypal')}" if p.riel == "PAYPAL" else f"···{p.cuenta_ultimos4}"),
            "titular": p.titular_confirmado, "referencia": p.referencia,
            "paypal": ({"modo": p.datos_firmados.get("modo_paypal", "simulado"),
                        "metodo": p.datos_firmados.get("metodo", "directo"),
                        "enlace": next((x.get("enlace") for x in (p.linea_tiempo or []) if x.get("enlace")), None)
                        if p.estado == "reservado" else None,
                        "consultable": p.estado in ("enviado", "reservado") and p.datos_firmados.get("modo_paypal") == "sandbox"}
                       if p.riel == "PAYPAL" else None),
            "estado": p.estado, "resultado": RESULTADOS.get(p.estado, p.estado), "firma": p.firma[:16],
            "clave_idempotencia": p.clave_idempotencia,
            "linea_tiempo": p.linea_tiempo, "motivo_devolucion": p.motivo_devolucion,
            "creado_en": p.creado_en.isoformat() + "Z", "liquidado_en": p.liquidado_en.isoformat() + "Z" if p.liquidado_en else None}
