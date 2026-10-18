"""
Carga inicial de la demo: empresa, usuarios por rol, proveedores con datos de pago ficticios
(validados con su dígito de control), reglas v1, wallet fondeada y, opcionalmente, 50 facturas: las 20 del set y 30
construidas con los ítems del dataset del reto (scripts/generar_reto.py).
TODOS LOS DATOS SON FICTICIOS.
"""
from __future__ import annotations

import json
import logging
import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import delete, insert, inspect, select
from sqlalchemy.orm import Session

from kauta import motor
from kauta.normalizacion import validar_aba, validar_clabe, validar_id_fiscal

from ..config import CONFIG, RAIZ
from ..db import Base, motor_bd
from ..modelos import (Aprobacion, Asiento, Beneficiario, CambioCuenta, ClaveIdempotencia, CuentaWallet, EventoAuditoria,
                       Factura, Meta, Movimiento, Organizacion, Pago, RutaAprobada, TokenFactura, Usuario, VersionReglas)
from ..seguridad.cifrado import cifrar
from ..seguridad.contrasenas import hashear, problemas_politica
from . import BLOQUEO, agente, auditoria, paypal, wallet

DATA = RAIZ / "data"
log = logging.getLogger("uvicorn.error")
CONTRASENA_DEMO = "Kauta-30X-demo-2026"
USUARIOS_DEMO = [
    ("carlos.rivera@brisamar.example", "Carlos Rivera", "CEO", "ceo"),
    ("mariana.torres@brisamar.example", "Mariana Torres", "Directora financiera", "finanzas"),
    ("andrea.gomez@brisamar.example", "Andrea Gómez", "Analista de cuentas por pagar", "finanzas"),
    ("tomas.herrera@brisamar.example", "Tomás Herrera", "Tesorería", "finanzas"),
    ("equipo@kauta.example", "Equipo Kauta", "Administración", "admin"),
    ("jurado@kauta.example", "Jurado Hackathon 30X", "Jurado (demo)", "admin"),
]
# Sube cuando cambia una tabla que ya existía (3: roles CEO, Finanzas y Administrador; 4: forma de pago por factura;
# 6: aprobar y pagar son pasos separados: factura «aprobada» y pago «negado»).
ESQUEMA = "6"
# riel, moneda en que recibe, banco (todo simulado)
BENEFICIARIOS_RETO = DATA / "reto" / "beneficiarios_reto.json"
BENEFICIARIOS_PRUEBAS = DATA / "pruebas" / "beneficiarios_pruebas.json"   # los del paquete facturas_de_prueba/
DOCS_RETO = DATA / "reto" / "documentos"

PAGO = {
    "B01": ("SWIFT", "USD", "Banco Cóndor (simulado) · SWIFT CNDRCOBB"),
    "B02": ("BREB", "COP", "Banco del Pacífico Sur (simulado) · llave Bre-B @carolinamendez"),
    "B03": ("ACH", "USD", "Lone Star Community Bank (simulado)"),
    "B04": ("SPEI", "MXN", "BancoMar (simulado)"),
    "B05": ("SWIFT", "USD", "Banco Austral (simulado) · SWIFT AUSTARBA"),
    "B06": ("SPEI", "MXN", "Banco Jade (simulado)"),
    "B07": ("WIRE", "USD", "Hudson Mutual Bank (simulado)"),
    "B08": ("BREB", "COP", "Banco Cóndor (simulado) · llave Bre-B @soportenexo"),
    "B09": ("SPEI", "MXN", "Banco Jade (simulado)"),
    "B10": ("BREB", "COP", "Banco del Pacífico Sur (simulado) · llave Bre-B @andresrojas"),
    "B11": ("SWIFT", "USD", "Banco Cóndor (simulado) · SWIFT CNDRCOBB"),
    "B12": ("ACH_CO", "COP", "Banco Cóndor (simulado) · cuenta de ahorros"),
    "B13": ("SWIFT", "USD", "Banco del Pacífico Sur (simulado) · SWIFT PSURCOBB"),
    "B14": ("ACH_CO", "COP", "Banco del Pacífico Sur (simulado) · cuenta corriente"),
    "X01": ("ACH", "USD", "Gulf Coast Bank (simulado)"),
}


def cuenta_ficticia(riel: str, ultimos4: str, rnd: random.Random) -> tuple[str, str]:
    """Número completo ficticio que termina en los 4 dígitos registrados y pasa su validación de formato."""
    d = lambda n: "".join(rnd.choice("0123456789") for _ in range(n))
    if riel in ("ACH", "WIRE"):
        base = "13" + d(6)  # el prefijo 13 no lo asigna la ABA: routing válido en formato y ficticio
        suma = sum(int(x) * p for x, p in zip(base, (3, 7, 1, 3, 7, 1, 3, 7)))
        routing = base + str((10 - suma % 10) % 10)
        assert validar_aba(routing).valido
        return f"ABA {routing} · cuenta {d(6)}{ultimos4}", "ABA con dígito de control válido"
    if riel == "SPEI":
        for _ in range(10000):  # 999 = banco inexistente; se busca la cuenta cuyo control deje la terminación registrada
            k = "999180" + d(8) + ultimos4[:3]
            suma = sum((int(x) * p) % 10 for x, p in zip(k, (3, 7, 1) * 6))
            if str((10 - suma % 10) % 10) == ultimos4[3]:
                assert validar_clabe(k + ultimos4[3]).valido
                return f"CLABE {k}{ultimos4[3]}", "CLABE de 18 dígitos con dígito de control válido"
    if riel == "BREB":
        return f"Cuenta de ahorros {d(6)}{ultimos4} (resuelta por la llave Bre-B)", "Llave Bre-B resuelta en el directorio"
    if riel == "SWIFT":
        return f"Cuenta {d(6)}{ultimos4}", "Código SWIFT/BIC con formato ISO 9362 válido"
    return f"Cuenta {d(7)}{ultimos4}", "Cuenta local"


def _usuarios(bd: Session) -> None:
    if bd.execute(select(Usuario)).first():
        return
    if not CONFIG.demo:
        return  # en producción los usuarios se crean con el proveedor de identidad, no con semillas
    h = hashear(CONTRASENA_DEMO)
    for correo, nombre, cargo, rol in USUARIOS_DEMO:
        if problemas_politica(CONTRASENA_DEMO, correo):
            raise RuntimeError(f"La contraseña de la demo no cumple la política: {problemas_politica(CONTRASENA_DEMO, correo)}")
        bd.add(Usuario(correo=correo, nombre=nombre, cargo=cargo, rol=rol, hash_contrasena=h))


def _invitacion_demo(bd: Session) -> None:
    """Una invitación pendiente de ejemplo, para que «Personas y roles» muestre el flujo completo."""
    from ..modelos import Invitacion
    from . import usuarios as serv_usuarios
    if not CONFIG.demo or bd.execute(select(Invitacion)).first():
        return
    bd.add(Invitacion(correo="daniel.osorio@brisamar.example", nombre="Daniel Osorio", cargo="Analista de pagos",
                      rol="finanzas", hash_codigo=hashear(serv_usuarios.generar_codigo()), prefijo="KAUD",
                      creada_por="Equipo Kauta (Administración)",
                      creada_en=datetime.now(timezone.utc), expira_en=datetime.now(timezone.utc) + timedelta(days=5)))


def _negocio(bd: Session, con_set: bool) -> None:
    empresa = json.loads((DATA / "empresa.json").read_text(encoding="utf-8"))
    if not bd.get(Organizacion, 1):
        bd.add(Organizacion(id=1, nombre=empresa["nombre"], id_fiscal=empresa["id_fiscal"], datos=empresa))
    rnd = random.Random(30)
    for b in json.loads((DATA / "beneficiarios.json").read_text(encoding="utf-8")):
        riel, moneda, banco = PAGO[b["id"]]
        cuenta, nota = cuenta_ficticia(riel, b["cuenta_registrada"], rnd)
        v = validar_id_fiscal(b["id_fiscal"], b["pais"])
        bd.add(Beneficiario(id=b["id"], nombre=b["nombre"], id_fiscal=b["id_fiscal"], tipo_id=v.tipo, id_valido=v.valido,
                            pais=b["pais"], tipo_persona=b["tipo_persona"], categoria=b["categoria"], estado=b["estado"],
                            motivo_bloqueo=b["motivo_bloqueo"], contrato=b["contrato"], contactos=b["contactos"], riel=riel,
                            moneda_recepcion=moneda, banco=f"{banco} · {nota}",
                            cuenta_cifrada=cifrar(cuenta, aad=f"cuenta:{b['id']}"), cuenta_ultimos4=b["cuenta_registrada"],
                            titular_registrado=b["nombre"], verificada_por="Alta inicial del proveedor (documentos y llamada)",
                            verificada_en=datetime(2026, 9, 1, 15, 0)))
    # Proveedores del dataset del reto: compran contra orden de compra y cobran por PayPal
    reto = json.loads(BENEFICIARIOS_RETO.read_text(encoding="utf-8")) if BENEFICIARIOS_RETO.exists() else []
    pruebas = json.loads(BENEFICIARIOS_PRUEBAS.read_text(encoding="utf-8")) if BENEFICIARIOS_PRUEBAS.exists() else []
    for b in reto + pruebas:
        v = validar_id_fiscal(b["id_fiscal"], b["pais"])
        bd.add(Beneficiario(id=b["id"], nombre=b["nombre"], id_fiscal=b["id_fiscal"], tipo_id=v.tipo, id_valido=v.valido,
                            pais=b["pais"], tipo_persona=b["tipo_persona"], categoria=b["categoria"], estado=b["estado"],
                            motivo_bloqueo=b["motivo_bloqueo"], contrato=b["contrato"], contactos=b["contactos"], riel="PAYPAL",
                            moneda_recepcion="USD", banco="PayPal · cuenta empresarial registrada en el alta",
                            cuenta_cifrada=cifrar(f"PayPal {b['id']}-{b['cuenta_registrada']}", aad=f"cuenta:{b['id']}"),
                            cuenta_ultimos4=b["cuenta_registrada"], titular_registrado=b["nombre"],
                            verificada_por=f"Alta con la orden de compra {b['contrato']['referencia']} (dataset del reto)",
                            verificada_en=datetime(2026, 9, 1, 15, 0)))
    reglas = json.loads((DATA / "reglas.json").read_text(encoding="utf-8"))
    bd.add(VersionReglas(version=1, parametros={k: v for k, v in reglas.items() if k != "version"},
                         creada_por="Mariana Torres (Finance Lead)", motivo="Política de pagos inicial de octubre de 2026"))
    wallet.crear_cuentas(bd)
    per = reglas["periodo_actual"]
    wallet.transferir(bd, "fondeo", "Depósito inicial simulado en la cuenta operativa", "FONDEO-0", per, "fondeo", "operativa", Decimal("120000"))
    wallet.transferir(bd, "fondeo", f"Fondeo de la sub-wallet de cuentas por pagar para {per}", f"FONDEO-{per}", per, "operativa", "cxp",
                      Decimal(str(reglas["presupuesto_periodo_usd"])))
    bd.flush()
    auditoria.registrar(bd, "demo.inicio", "Sistema", "organizacion", "1",
                        f"Demo iniciada: {empresa['nombre']}, reglas v1, sub-wallet fondeada con USD {reglas['presupuesto_periodo_usd']:,}.", {})
    bd.commit()
    if con_set:
        ref = json.loads((DATA / "referencia_extracciones.json").read_text(encoding="utf-8"))
        for p in sorted((DATA / "facturas").iterdir()):
            if p.is_file() and not p.name.startswith("."):
                with paypal.solo_simulado():          # la carga inicial no envía pagos reales al sandbox
                    f = agente.procesar_archivo(bd, p.name, p.read_bytes(), "set", "Agente Kauta", "buzon@brisamar.example")
                recibida = ref.get(p.name, {}).get("recibida")
                if recibida:  # hora de Bogotá (UTC-5) guardada en UTC
                    f.recibida_en = datetime.fromisoformat(recibida) + timedelta(hours=5)
        bd.commit()
        _facturas_reto(bd, reglas)
        _aprobadas_demo(bd)


def _aprobadas_demo(bd: Session) -> None:
    """El CEO ya aprobó dos facturas del reto que solo superaban el umbral: quedan listas para que Finanzas las pague."""
    ceo = bd.execute(select(Usuario).where(Usuario.correo == "carlos.rivera@brisamar.example")).scalar_one_or_none()
    if not ceo:
        return
    solo_umbral = [f for f in bd.execute(select(Factura).where(Factura.estado == "pendiente")).scalars()
                   if {r["id"] for r in f.reglas if r["estado"] == "falla"} == {"R10"}]
    aprobadas = 0
    for f in sorted(solo_umbral, key=lambda f: f.monto_usd or 0):
        try:                                   # solo las que caben en el presupuesto de su periodo (R12)
            agente.aprobar(bd, f.id, ceo, "Revisé la orden de compra y la recepción del pedido: el monto coincide. "
                           "Apruebo; Finanzas la paga.", None, con_mfa=True)
        except agente.ErrorNegocio:
            continue
        aprobadas += 1
        if aprobadas == 2:
            break


def _facturas_reto(bd: Session, reglas: dict) -> None:
    """Las 30 facturas construidas con los ítems del dataset del reto (scripts/generar_reto.py), por correo, chat, PDF,
    foto y XML. Se emitieron en septiembre: ese periodo tiene su propio presupuesto."""
    if not DOCS_RETO.exists():
        return
    ref = json.loads((DOCS_RETO / "referencia.json").read_text(encoding="utf-8"))
    periodos = sorted({v["fecha_emision"][:7] for v in ref.values() if v.get("fecha_emision")})
    for per in periodos:
        presupuesto = motor.presupuesto_de(reglas, per)
        if per not in wallet.periodos_fondeados(bd):
            wallet.transferir(bd, "fondeo", f"Fondeo de la sub-wallet de cuentas por pagar para {per} (facturas del dataset del reto)",
                              f"FONDEO-{per}", per, "operativa", "cxp", presupuesto)
            auditoria.registrar(bd, "wallet.fondeo_periodo", "Tesorería automática", "wallet", "cxp",
                                f"Se fondeó la sub-wallet para {per} con USD {presupuesto:,.0f}.", {})
    bd.commit()
    for p in sorted(DOCS_RETO.iterdir()):
        if p.is_file() and p.name in ref:
            with paypal.solo_simulado():
                f = agente.procesar_archivo(bd, p.name, p.read_bytes(), "reto", "Agente Kauta", "buzon@brisamar.example")
            f.recibida_en = datetime.fromisoformat(ref[p.name]["recibida"]) + timedelta(hours=5)
    bd.commit()


def _preparar_esquema() -> None:
    """
    Crea las tablas que falten y detecta una base de una versión anterior (por ejemplo, con los roles viejos).
    En demo esa base se vuelve a crear con los datos de ejemplo; en producción el servidor no arranca sin migrarla.
    """
    tablas = set(inspect(motor_bd).get_table_names())
    version = None
    if "kauta_meta" in tablas:
        with motor_bd.connect() as c:
            version = c.execute(select(Meta.valor).where(Meta.clave == "esquema")).scalar_one_or_none()
    if "usuarios" in tablas and version != ESQUEMA:
        if not CONFIG.demo:
            raise RuntimeError(f"La base de datos es de una versión anterior de Kauta (esquema {version or '1-2'}, "
                               f"se necesita {ESQUEMA}). Migre los roles a admin, ceo y finanzas antes de arrancar.")
        log.warning("La base de la demo es de una versión anterior (esquema %s): se vuelve a crear con los datos de ejemplo.",
                    version or "1-2")
        Base.metadata.drop_all(motor_bd)
    Base.metadata.create_all(motor_bd)
    with motor_bd.begin() as c:
        if c.execute(select(Meta.valor).where(Meta.clave == "esquema")).scalar_one_or_none() is None:
            c.execute(insert(Meta).values(clave="esquema", valor=ESQUEMA))


def iniciar(bd: Session, con_set: bool = True) -> None:
    _preparar_esquema()
    _usuarios(bd)
    _invitacion_demo(bd)
    bd.commit()
    if not bd.get(Organizacion, 1):
        _negocio(bd, con_set)


TABLAS_NEGOCIO = [ClaveIdempotencia, Movimiento, Asiento, Pago, Aprobacion, TokenFactura, CambioCuenta, Factura, Beneficiario,
                  RutaAprobada, VersionReglas, CuentaWallet, EventoAuditoria, Organizacion]


def restablecer(bd: Session, con_set: bool, actor: str) -> None:
    """Vuelve la demo al estado inicial. Conserva usuarios y sesiones."""
    with BLOQUEO:
        for t in TABLAS_NEGOCIO:
            bd.execute(delete(t))
        bd.commit()
        _negocio(bd, con_set)
        auditoria.registrar(bd, "demo.restablecida", actor, "organizacion", "1",
                            "La demo se restableció " + ("con las 50 facturas de ejemplo (20 del set y 30 del dataset del reto)." if con_set else "sin facturas."), {})
        bd.commit()
