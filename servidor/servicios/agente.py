"""
El agente Kauta en el servidor: extracción (IA solo si hace falta) + motor de reglas determinista +
pago por la wallet + registro de auditoría. Todo se guarda en la base de datos.

Ciclo de una factura:
  1. Se lee el documento (XML fiscal exacto, extracción verificada o IA) y se valida.
  2. El motor decide con las reglas vigentes: pagar, frenar o escalar.
  3. Si es «pagar», el pago sale solo por la wallet (con sus propios controles).
  4. Si es «escalar», Kauta pregunta a una persona; si supera el umbral, se necesitan DOS personas.
  5. Al aprobar, el motor vuelve a revisar las reglas duras: ninguna aprobación rompe saldo,
     duplicados, bloqueos ni el máximo por pago.
"""
from __future__ import annotations

import csv
import hashlib
import os
import re
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from kauta import motor
from kauta.extractor import ExtraccionNoDisponible, ExtractorReferencia

from ..config import CONFIG, RAIZ, VAR
from ..modelos import (Aprobacion, ArchivoGuardado, Beneficiario, CambioCuenta, Factura, Pago, Usuario, VersionReglas)
from ..seguridad import firma
from ..seguridad.cifrado import cifrar
from ..seguridad.permisos import tiene
from . import BLOQUEO, auditoria, pagos, wallet

ESTADO = {"pagar": "pagada", "frenar": "frenada", "escalar": "pendiente"}
ARCHIVOS = VAR / "archivos"


class ErrorNegocio(ValueError):
    """Error explicable para la persona (se devuelve como 409/422 con el mensaje)."""


# ---------------------------------------------------------------------------
# Extractor del servidor: XML y set de referencia sin IA; IA para documentos nuevos si hay clave
# ---------------------------------------------------------------------------
class ExtractorServidor:
    def __init__(self) -> None:
        self.ref = ExtractorReferencia()
        self.ia = None
        if os.environ.get("ANTHROPIC_API_KEY"):
            try:
                from kauta.extractor import ExtractorIA
                self.ia = ExtractorIA()
            except Exception:
                self.ia = None

    @property
    def modo(self) -> str:
        return f"IA activa ({self.ia.modelo})" if self.ia else "Sin IA: XML fiscal, texto del PDF, chat o correo, y OCR local"

    def extraer(self, nombre: str, datos: bytes) -> dict[str, Any]:
        try:
            return self.ref.extraer(nombre, datos)
        except ExtraccionNoDisponible:
            if self.ia:
                return self.ia.extraer(nombre, datos)
            raise ErrorNegocio("Kauta no pudo leer este documento sin IA: no trae XML fiscal, ni texto suficiente, ni una "
                               "imagen legible para el OCR (¿está instalado Tesseract?). Con ANTHROPIC_API_KEY lo leería la IA.")


EXTRACTOR = ExtractorServidor()


# ---------------------------------------------------------------------------
# Datos para el motor
# ---------------------------------------------------------------------------
def reglas_vigentes(bd: Session) -> dict[str, Any]:
    v = bd.execute(select(VersionReglas).order_by(VersionReglas.version.desc()).limit(1)).scalar_one()
    return {**v.parametros, "version": v.version}


def beneficiarios_motor(bd: Session) -> list[dict[str, Any]]:
    return [{"id": b.id, "nombre": b.nombre, "id_fiscal": b.id_fiscal, "pais": b.pais, "tipo_persona": b.tipo_persona,
             "categoria": b.categoria, "contrato": b.contrato, "cuenta_registrada": b.cuenta_ultimos4,
             "estado": b.estado, "motivo_bloqueo": b.motivo_bloqueo}
            for b in bd.execute(select(Beneficiario).order_by(Beneficiario.id)).scalars()]


def historial(bd: Session, excluir: str | None = None) -> list[dict[str, Any]]:
    return [{"factura_id": f.id, "beneficiario_clave": f.beneficiario_clave, "numero_factura": f.numero,
             "periodo": f.periodo, "estado": f.estado, "monto_usd": float(f.monto_usd) if f.monto_usd is not None else None,
             "hashes": f.hashes, "id_fiscal_unico": f.id_fiscal_unico}
            for f in bd.execute(select(Factura).order_by(Factura.recibida_en, Factura.id)).scalars() if f.id != excluir]


def periodos_abiertos(reglas: dict[str, Any]) -> list[str]:
    """Periodo actual y el siguiente: los únicos que la tesorería automática fondea."""
    a, m = (int(x) for x in reglas["periodo_actual"].split("-"))
    return [reglas["periodo_actual"], f"{a + (m // 12)}-{m % 12 + 1:02d}"]


def nuevo_id(bd: Session, nombre: str, origen: str) -> str:
    pref = Path(nombre).name.split("_")[0]
    if re.fullmatch(r"[FSP]\d{2}", pref) and not bd.get(Factura, pref):     # P01…P50: el paquete facturas_de_prueba/
        return pref
    base = "SIM" if origen == "simulador" else "N"
    n = 1
    while bd.get(Factura, f"{base}{n:03d}"):
        n += 1
    return f"{base}{n:03d}"


def _dec(v: Any) -> Decimal | None:
    return Decimal(str(v)).quantize(Decimal("0.01")) if v is not None else None


def guardar_archivo(nombre: str, datos: bytes, bd: Session | None = None) -> str:
    """Los archivos se guardan con nombre aleatorio derivado de su huella, fuera de la carpeta web.
    Con varias instancias (PostgreSQL) se guarda además una copia en la base, para que cualquiera lo pueda leer."""
    ARCHIVOS.mkdir(parents=True, exist_ok=True)
    ext = re.sub(r"[^a-z0-9.]", "", Path(nombre).suffix.lower())[:6] or ".bin"
    ruta = ARCHIVOS / (hashlib.sha256(datos).hexdigest() + ext)
    if not ruta.exists():
        ruta.write_bytes(datos)
    if bd is not None and CONFIG.varias_instancias and bd.get(ArchivoGuardado, ruta.name) is None:
        bd.add(ArchivoGuardado(nombre=ruta.name, datos=datos))
    return str(ruta)


def leer_archivo(bd: Session, ruta: str | None) -> bytes | None:
    """El documento tal como llegó: del disco o, si esta instancia no lo tiene, de la copia en la base."""
    if not ruta:
        return None
    p = Path(ruta)
    if p.exists():
        return p.read_bytes()
    if CONFIG.varias_instancias and (a := bd.get(ArchivoGuardado, p.name)) is not None:
        ARCHIVOS.mkdir(parents=True, exist_ok=True)
        (ARCHIVOS / p.name).write_bytes(a.datos)
        return a.datos
    return None


# ---------------------------------------------------------------------------
# Procesar una factura
# ---------------------------------------------------------------------------
def procesar_archivo(bd: Session, nombre: str, datos: bytes, origen: str, actor: str, cargada_por: str,
                     forzar_pago: str | None = None) -> Factura:
    r = EXTRACTOR.extraer(nombre, datos)
    return registrar(bd, nombre, r, origen, actor, cargada_por, ruta=guardar_archivo(nombre, datos, bd), forzar_pago=forzar_pago)


def registrar(bd: Session, nombre: str, r: dict[str, Any], origen: str, actor: str, cargada_por: str,
              ruta: str | None = None, forzar_pago: str | None = None, factura_id: str | None = None,
              riel: str | None = None) -> Factura:
    with BLOQUEO:
        fid = factura_id or nuevo_id(bd, nombre, origen)
        reglas = reglas_vigentes(bd)
        bens = beneficiarios_motor(bd)
        ext = r["extraccion"]
        ben, _ = motor.buscar_beneficiario(ext, bens)
        periodo = motor.periodo_de(ext, reglas)
        if wallet.asegurar_fondeo(bd, periodo, motor.presupuesto_de(reglas, periodo), periodos_abiertos(reglas)):
            auditoria.registrar(bd, "wallet.fondeo_periodo", "Tesorería automática", "wallet", "cxp",
                                f"Se fondeó la sub-wallet para {periodo} con USD {motor.presupuesto_de(reglas, periodo):,.0f}.", {})
        t0 = datetime.now(timezone.utc)
        d = motor.evaluar({"factura_id": fid, "extraccion": ext, "hashes": r["hashes"]}, reglas, bens, historial(bd))
        ms = round((datetime.now(timezone.utc) - t0).total_seconds() * 1000, 1)
        requeridas = 0 if d.decision != "escalar" else 1     # una aprobación; el pago es un paso aparte
        lista = [asdict(x) for x in d.reglas]
        f = Factura(id=fid, archivo=nombre, canal=r["canal"], origen=origen, ruta_archivo=ruta,
                    hash_documento=r["hashes"][0], hashes=r["hashes"], cargada_por=cargada_por, extraccion=ext,
                    texto=(r.get("texto") or "")[:20000], metodo_lectura=ext.get("metodo_lectura") or "ia",
                    modelo=r.get("modelo") or "", beneficiario_id=d.beneficiario_id,
                    beneficiario_nombre=d.beneficiario_nombre or "Sin nombre", beneficiario_clave=motor.clave_beneficiario(ben, ext),
                    numero=ext.get("numero_factura"), id_fiscal_unico=ext.get("id_fiscal_unico"), monto=_dec(d.monto),
                    moneda=d.moneda, monto_usd=_dec(d.monto_usd), periodo=d.periodo or reglas["periodo_actual"],
                    fecha_vencimiento=ext.get("fecha_vencimiento"), decision=d.decision, decision_inicial=d.decision,
                    estado=ESTADO[d.decision], motivo=d.motivo, motivo_inicial=d.motivo, reglas=lista, reglas_iniciales=lista,
                    version_reglas=d.version_reglas or reglas["version"], aprobaciones_requeridas=requeridas, riel_pago=riel)
        bd.add(f)
        bd.flush()
        auditoria.registrar(bd, "factura.decision", actor, "factura", fid, d.motivo[:400],
                            {"decision": d.decision, "monto_usd": d.monto_usd, "beneficiario": f.beneficiario_nombre,
                             "metodo_lectura": f.metodo_lectura, "modelo": f.modelo, "hash_documento": f.hash_documento,
                             "version_reglas": f.version_reglas, "duracion_ms": ms,
                             "reglas": {x["id"]: x["estado"] for x in lista}})
        if d.decision == "pagar":
            _pagar_o_escalar(bd, f, reglas, actor, forzar_pago, riel)
        r07 = next((x for x in lista if x["id"] == "R07" and x["estado"] == "falla"), None)
        if r07 and f.beneficiario_id and (ext.get("cuenta_destino") or ""):
            _solicitar_cambio_cuenta(bd, f, ext["cuenta_destino"])
        bd.commit()
        return f


def _pagar_o_escalar(bd: Session, f: Factura, reglas: dict[str, Any], actor: str, forzar: str | None,
                     riel: str | None = None) -> Pago | None:
    """El motor dijo «pagar»; los controles del pago aún pueden detenerlo (defensa en profundidad)."""
    try:
        with bd.begin_nested():
            return pagos.crear_y_ejecutar(bd, f, reglas, actor, forzar=forzar, riel=riel)
    except ValueError as e:
        f.decision, f.estado = "escalar", "pendiente"
        if f.aprobaciones_requeridas == 0:
            f.decision_inicial = "escalar"
            f.aprobaciones_requeridas = 1
        f.motivo = f"Escalada · Control del pago: {e} El motor aprobó, pero el pago no sale hasta que una persona lo revise."
        if f.motivo_inicial.startswith("Pagada"):
            f.motivo_inicial = f.motivo
        auditoria.registrar(bd, "pago.bloqueado", "Agente Kauta", "factura", f.id, str(e)[:300], {})
        return None


def _solicitar_cambio_cuenta(bd: Session, f: Factura, ultimos4: str) -> None:
    pendiente = bd.execute(select(CambioCuenta).where(CambioCuenta.beneficiario_id == f.beneficiario_id,
                                                      CambioCuenta.estado == "pendiente")).scalar_one_or_none()
    if pendiente:
        return
    banco = "Banca Aurora (simulado)"
    m = re.search(r"(Banca|Banco)\s+[A-ZÁÉÍÓÚa-záéíóúñ ]+\(simulado\)", f.texto or "")
    if m:
        banco = m.group(0)
    c = CambioCuenta(beneficiario_id=f.beneficiario_id, factura_id=f.id, banco_nuevo=banco,
                     cuenta_nueva_cifrada=cifrar("0" * 8 + ultimos4[-4:], aad=f"cambio:{f.beneficiario_id}"),
                     ultimos4_nuevos=ultimos4[-4:], origen=f"Factura {f.id} ({f.canal})",
                     solicitada_por="Agente Kauta (detectado en la factura)")
    bd.add(c)
    bd.flush()
    auditoria.registrar(bd, "cuenta.cambio_solicitado", "Agente Kauta", "beneficiario", f.beneficiario_id,
                        f"La factura {f.id} pide pagar a ···{ultimos4[-4:]}; queda pendiente de verificación independiente.",
                        {"factura": f.id, "solicitud": c.id})


# ---------------------------------------------------------------------------
# Decisiones humanas
# ---------------------------------------------------------------------------
def cargada_por_mi(f: Factura, correo: str) -> bool:
    """La factura la cargó esta persona (también cuando entró como caso de prueba: «caso de prueba:correo»)."""
    return (f.cargada_por or "").rsplit(":", 1)[-1].strip().lower() == correo.lower()


def revisar_aprobacion(bd: Session, fid: str, u: Usuario, correcciones: dict[str, Any] | None):
    """
    Todo lo que se verifica antes de aceptar una aprobación (también antes de emitir su token): estado,
    segregación de funciones, quién aprueba según el monto y reglas duras con los datos corregidos.
    Devuelve (factura, extracción, decisión del motor, correcciones, aprobaciones previas, reglas).
    """
    with BLOQUEO:
        f = bd.get(Factura, fid)
        if not f:
            raise ErrorNegocio("La factura no existe.")
        if f.estado != "pendiente":
            raise ErrorNegocio(f"Solo se aprueban facturas pendientes (estado actual: {f.estado}).")
        if cargada_por_mi(f, u.correo):
            raise ErrorNegocio("Segregación de funciones: quien cargó la factura no puede aprobarla.")
        previas = [a for a in f.aprobaciones if a.accion == "aprobar"]
        if any(a.usuario_id == u.id for a in previas):
            raise ErrorNegocio("Usted ya aprobó esta factura.")
        reglas = reglas_vigentes(bd)
        bens = beneficiarios_motor(bd)
        ext = dict(f.extraccion)
        corr = {k: v for k, v in (correcciones or {}).items() if v not in (None, "")}
        if corr:
            ext["confianza"] = dict(ext.get("confianza") or {})
            for k, v in corr.items():
                if k in ("monto", "horas"):
                    v = float(v)
                ext[k] = v
                ext["confianza"][k] = 1.0
            ext["validaciones"] = [v for v in ext.get("validaciones") or [] if v.get("campo") != "qr_total"]
        d = motor.evaluar({"factura_id": fid, "extraccion": ext, "hashes": f.hashes}, reglas, bens, historial(bd, excluir=fid))
        duras = d.fallas("frenar")
        if duras:
            auditoria.registrar(bd, "aprobacion.bloqueada", f"{u.nombre} ({u.cargo})", "factura", fid,
                                f"Intento de aprobación bloqueado por regla dura {duras[0].id}: {duras[0].detalle}"[:400],
                                {"reglas": [r.id for r in duras]})
            bd.commit()
            raise ErrorNegocio(f"La aprobación no procede por una regla dura ({duras[0].id}): {duras[0].detalle}")
        umbral = Decimal(str(reglas["umbral_aprobacion_usd"]))
        if Decimal(str(d.monto_usd or 0)) > umbral and not tiene(u.rol, "facturas.firma_alta"):
            raise ErrorNegocio(f"Esta factura supera el umbral de {motor.fmt_dinero(umbral)}: la aprueba el CEO. "
                               "Cuando el CEO la apruebe, Finanzas la paga desde Pagos.")
        return f, ext, d, corr, previas, reglas


def aprobar(bd: Session, fid: str, u: Usuario, comentario: str, correcciones: dict[str, Any] | None,
            con_mfa: bool) -> dict[str, Any]:
    with BLOQUEO:
        if not (comentario or "").strip():
            raise ErrorNegocio("Escriba por qué aprueba: toda decisión humana debe quedar explicada.")
        f, ext, d, corr, previas, reglas = revisar_aprobacion(bd, fid, u, correcciones)
        if corr:
            f.extraccion = ext
            f.monto, f.moneda, f.monto_usd = _dec(d.monto), d.moneda, _dec(d.monto_usd)
        nivel = len(previas) + 1
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        ben = bd.get(Beneficiario, f.beneficiario_id) if f.beneficiario_id else None
        datos = pagos.datos_aprobacion(f, ben.id if ben else None, ben.cuenta_ultimos4 if ben else "", u.id, nivel, "aprobar", ts)
        revisadas = [r["id"] for r in f.reglas if r["estado"] == "falla" and r["efecto"] == "escalar"]
        a = Aprobacion(factura_id=fid, usuario_id=u.id, usuario_nombre=u.nombre, nivel=nivel, accion="aprobar",
                       comentario=comentario.strip()[:1000], correcciones=corr, reglas_revisadas=revisadas,
                       datos_firmados=datos, firma=firma.firmar(datos), con_mfa=con_mfa)
        bd.add(a)
        bd.flush()
        auditoria.registrar(bd, "aprobacion", f"{u.nombre} ({u.cargo})", "factura", fid,
                            f"Aprobación {nivel} de {f.aprobaciones_requeridas} · «{comentario.strip()[:160]}»",
                            {"firma": a.firma[:16], "con_mfa": con_mfa, "correcciones": corr, "reglas_revisadas": revisadas})
        if nivel < f.aprobaciones_requeridas:
            bd.commit()
            return {"ok": True, "completa": False, "mensaje": f"Aprobación {nivel} de {f.aprobaciones_requeridas} registrada. "
                    "El monto supera el umbral: falta la aprobación de otra persona (doble control)."}
        quienes = " y ".join(x.usuario_nombre for x in [*previas, a])
        f.decision, f.estado, f.reglas = "pagar", "aprobada", [asdict(x) for x in d.reglas]
        partes = [f"Aprobada por {quienes}, que revisó: "
                  + "; ".join(f"{motor.CATALOGO[r]['falla'].lower()} ({r})" for r in revisadas) + "."]
        if corr:
            partes.append("Datos corregidos: " + ", ".join(f"{k} = {v}" for k, v in corr.items()) + ".")
        partes.append(f"Comentario: «{comentario.strip()[:200]}».")
        partes.append("Lista para pagar: Finanzas la paga desde Pagos con su token, y Kauta vuelve a verificar las reglas "
                      "duras (saldo, duplicados, bloqueos y máximo por pago) en ese momento.")
        if any(r == "R07" for r in revisadas) and ben:
            partes.append(f"Se pagará a la cuenta registrada (···{ben.cuenta_ultimos4}); un cambio de cuenta solo se aplica con verificación independiente.")
        f.motivo = " ".join(partes)
        auditoria.registrar(bd, "factura.aprobada", f"{u.nombre} ({u.cargo})", "factura", fid,
                            f"{fid} aprobada por {quienes}: lista para pagar.", {"monto_usd": str(f.monto_usd)})
        bd.commit()
        return {"ok": True, "completa": True, "estado": "aprobada", "mensaje": f.motivo, "pago": None}


def rechazar(bd: Session, fid: str, u: Usuario, comentario: str) -> dict[str, Any]:
    with BLOQUEO:
        f = bd.get(Factura, fid)
        if not f or f.estado != "pendiente":
            raise ErrorNegocio("Solo se rechazan facturas pendientes.")
        if not (comentario or "").strip():
            raise ErrorNegocio("Escriba el motivo del rechazo.")
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        datos = pagos.datos_aprobacion(f, f.beneficiario_id, "", u.id, 0, "rechazar", ts)
        bd.add(Aprobacion(factura_id=fid, usuario_id=u.id, usuario_nombre=u.nombre, nivel=0, accion="rechazar",
                          comentario=comentario.strip()[:1000], datos_firmados=datos, firma=firma.firmar(datos)))
        f.estado = "rechazada"
        f.motivo = f"Rechazada por {u.nombre}. Comentario: «{comentario.strip()[:200]}»."
        auditoria.registrar(bd, "rechazo", f"{u.nombre} ({u.cargo})", "factura", fid, f.motivo, {})
        bd.commit()
        return {"ok": True, "mensaje": f.motivo}


# ---------------------------------------------------------------------------
# Pagar una factura aprobada: un paso aparte, con su propio token
# ---------------------------------------------------------------------------
NO_SE_PAGA = {
    "pendiente": "Esta factura aún no está aprobada: primero la aprueba Finanzas (o el CEO si supera el umbral) en Kauta pregunta.",
    "pagada": "Esta factura ya está pagada.",
    "devuelta": "El pago anterior de esta factura falló y el dinero volvió a la wallet: use «Reintentar» en Pagos.",
    "frenada": "Kauta frenó esta factura por una regla: no se paga.",
    "rechazada": "Esta factura fue rechazada por una persona: no se paga.",
}
RESULTADO = {
    "liquidado": "Pago exitoso: el dinero llegó al beneficiario.",
    "enviado": "Pago en proceso: PayPal lo recibió y lo está procesando. Use «Consultar en PayPal» en unos segundos.",
    "devuelto": "Pago fallido: el riel no lo completó y el dinero volvió a la wallet. Puede reintentarlo.",
}


def revisar_pago(bd: Session, fid: str, u: Usuario) -> tuple[Factura, Beneficiario]:
    """Lo que se verifica antes de enviar el token de pago y otra vez al pagar."""
    f = bd.get(Factura, fid)
    if not f:
        raise ErrorNegocio("La factura no existe.")
    if not tiene(u.rol, "pagos.ejecutar"):
        raise ErrorNegocio("Su rol no paga facturas: las paga Finanzas cuando ya están aprobadas.")
    if f.estado != "aprobada":
        raise ErrorNegocio(NO_SE_PAGA.get(f.estado, f"No se puede pagar una factura en estado {f.estado}."))
    ben = bd.get(Beneficiario, f.beneficiario_id) if f.beneficiario_id else None
    if not ben:
        raise ErrorNegocio("La factura no tiene un beneficiario registrado: no se puede pagar.")
    return f, ben


def pagar(bd: Session, fid: str, u: Usuario, metodo: str = "directo", origen: str = "") -> tuple[Pago, str, str | None]:
    """
    Finanzas paga una factura aprobada. Antes de mover un dólar, Kauta vuelve a evaluar las 13 reglas con los datos de
    hoy (otra factura pudo gastar el presupuesto o el proveedor pudo quedar bloqueado). Devuelve el pago y su resultado:
    exitoso, en proceso, fallido (el riel lo devolvió) o negado (Kauta no movió el dinero).
    Con metodo="ventana" (PayPal Checkout) el pago queda esperando: devuelve el enlace de la ventana de PayPal, donde
    quien paga lo aprueba o lo rechaza; al volver, Kauta cobra la orden (pagos.completar_checkout).
    """
    with BLOQUEO:
        f, ben = revisar_pago(bd, fid, u)
        actor = f"{u.nombre} ({u.cargo})"
        reglas = reglas_vigentes(bd)
        d = motor.evaluar({"factura_id": f.id, "extraccion": f.extraccion, "hashes": f.hashes}, reglas,
                          beneficiarios_motor(bd), historial(bd, excluir=f.id))
        intento = len(bd.execute(select(Pago).where(Pago.factura_id == f.id)).scalars().all()) + 1
        duras = d.fallas("frenar")
        if duras:
            r = duras[0]
            p = pagos.registrar_negado(bd, f, ben, reglas, actor, f"Regla {r.id} · {r.detalle}", intento)
            f.decision, f.estado, f.reglas = "frenar", "frenada", [asdict(x) for x in d.reglas]
            f.motivo = (f"Frenada al pagar · {motor.CATALOGO[r.id]['falla']} ({r.id}): {r.detalle} Estaba aprobada, pero "
                        "Kauta volvió a revisar las reglas antes de mover el dinero y esta ya no se cumple.")
            bd.commit()
            return p, f"Pago negado por la regla {r.id}: {r.detalle}", None
        ventana = metodo == "ventana" and (f.riel_pago or pagos.RIEL_PAGOS) == "PAYPAL"
        enlace = None
        try:
            with bd.begin_nested():
                if ventana:
                    p, enlace = pagos.iniciar_checkout(bd, f, reglas, actor, intento, origen)
                else:
                    p = pagos.crear_y_ejecutar(bd, f, reglas, actor, riel=f.riel_pago, intento=intento)
        except ValueError as e:
            p = pagos.registrar_negado(bd, f, ben, reglas, actor, str(e), intento)
            bd.commit()
            return p, f"Pago negado: {e} La factura sigue aprobada y se puede pagar cuando se resuelva.", None
        if ventana:
            bd.commit()
            if not enlace:
                return p, f"Pago fallido: {p.motivo_devolucion} La factura sigue lista para pagar.", None
            return p, "Abra PayPal para aprobar o rechazar el pago: al volver, Kauta lo cobra y le muestra el resultado.", enlace
        if p.estado != "devuelto":
            aprobacion = re.sub(r"\s*Lista para pagar:.*?en ese momento\.", "", f.motivo or "")
            f.estado, f.reglas = "pagada", [asdict(x) for x in d.reglas]
            f.motivo = (f"Pagada por {u.nombre} con token · {p.id} por {pagos.RIELES[p.riel]['nombre']}. {aprobacion} "
                        "Al pagar, Kauta volvió a verificar las reglas duras y se cumplen.")
        bd.commit()
        return p, RESULTADO.get(p.estado, p.estado), None


def reevaluar(bd: Session, actor: str, beneficiario_id: str | None = None) -> list[str]:
    """Con reglas o datos nuevos, vuelve a evaluar en orden las frenadas y pendientes (las pagadas no se tocan)."""
    cambiadas = []
    with BLOQUEO:
        reglas = reglas_vigentes(bd)
        bens = beneficiarios_motor(bd)
        consulta = select(Factura).where(Factura.estado.in_(("frenada", "pendiente")))
        if beneficiario_id:
            consulta = consulta.where(Factura.beneficiario_id == beneficiario_id)
        for f in bd.execute(consulta.order_by(Factura.recibida_en, Factura.id)).scalars().all():
            antes = f.estado
            d = motor.evaluar({"factura_id": f.id, "extraccion": f.extraccion, "hashes": f.hashes}, reglas, bens,
                              historial(bd, excluir=f.id))
            nuevo = ESTADO[d.decision]
            f.reglas, f.version_reglas, f.decision, f.motivo = [asdict(x) for x in d.reglas], reglas["version"], d.decision, d.motivo
            f.aprobaciones_requeridas = 0 if d.decision != "escalar" else 1
            f.estado = nuevo
            bd.flush()
            if nuevo != antes:
                if nuevo == "pagada":
                    _pagar_o_escalar(bd, f, reglas, actor, None, f.riel_pago)
                cambiadas.append(f.id)
                auditoria.registrar(bd, "reevaluacion", actor, "factura", f.id,
                                    f"Con las reglas v{reglas['version']}: {antes} → {f.estado}. {f.motivo[:200]}", {})
        bd.commit()
    return cambiadas


# ---------------------------------------------------------------------------
# Métricas para el jurado
# ---------------------------------------------------------------------------
def esperado_set() -> dict[str, dict[str, str]]:
    ruta = RAIZ / "data" / "esperado.csv"
    return {r["factura_id"]: r for r in csv.DictReader(open(ruta, encoding="utf-8"))} if ruta.exists() else {}


def regla_principal(motivo: str) -> str:
    m = re.search(r"\((R\d{2})\)", motivo or "")
    return m.group(1) if m and not motivo.startswith("Pagada") else "—"


def metricas(bd: Session) -> dict[str, Any]:
    fs = bd.execute(select(Factura)).scalars().all()
    tot = len(fs)
    cuenta = lambda e: sum(1 for f in fs if f.estado == e)
    autonomas = sum(1 for f in fs if f.decision_inicial in ("pagar", "frenar"))
    indebidos = 0
    for f in fs:
        if f.estado != "pagada":
            continue
        aprobadas = [a for a in f.aprobaciones if a.accion == "aprobar"]
        fallas = [r for r in f.reglas if r["estado"] == "falla"]
        if not aprobadas and fallas:
            indebidos += 1
        if aprobadas and any(r["efecto"] == "frenar" for r in fallas):
            indebidos += 1
        if aprobadas and len(aprobadas) < f.aprobaciones_requeridas:
            indebidos += 1
    esperado = esperado_set()
    del_set = [f for f in fs if f.id in esperado]
    aciertos = sum(1 for f in del_set if f.decision_inicial == esperado[f.id]["decision_esperada"]
                   and regla_principal(f.motivo_inicial) == esperado[f.id]["regla_principal"])
    protegido = sum((float(f.monto_usd or 0) for f in fs if f.estado in ("frenada", "rechazada")), 0.0)
    autonomas_set = sum(1 for f in del_set if f.decision_inicial in ("pagar", "frenar"))
    trampas = [f for f in del_set if esperado[f.id]["tipo_caso"] == "trampa"]
    return {
        "total": tot, "pagadas": cuenta("pagada"), "frenadas": cuenta("frenada"), "pendientes": cuenta("pendiente"),
        "aprobadas": cuenta("aprobada"),
        "rechazadas": cuenta("rechazada"), "devueltas": cuenta("devuelta"),
        "autonomia_pct": round(100 * autonomas / tot, 1) if tot else 0.0,
        "pagos_fuera_de_reglas": indebidos,
        "explicadas_pct": round(100 * sum(1 for f in fs if f.motivo and f.reglas) / tot, 1) if tot else 0.0,
        "set_aciertos": aciertos, "set_total": len(del_set),
        "autonomia_set_pct": round(100 * autonomas_set / len(del_set), 1) if del_set else 0.0,
        "trampas_detenidas": sum(1 for f in trampas if f.decision_inicial != "pagar"), "trampas_total": len(trampas),
        "dinero_protegido_usd": round(protegido, 2),
        "lectura_xml": sum(1 for f in fs if f.metodo_lectura == "xml_fiscal"),
    }
