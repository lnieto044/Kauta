"""
Avisos por correo a quien revisa las facturas: «le llega la factura al correo».

  * Cuando llega una factura (carga o buzón), Finanzas recibe el aviso con lo que decidió Kauta y el documento
    original adjunto. Si Kauta pregunta y el monto supera el umbral, el aviso va al CEO, que es quien aprueba.
  * Cuando una factura queda aprobada, Finanzas recibe «lista para pagar».
  * Cuando se paga, quienes la aprobaron reciben el resultado: exitoso, en proceso, fallido o negado.
Nunca se avisa a quien cargó la factura (ya la vio) ni a quien hizo el paso. La carga inicial de la demo no avisa.
"""
from __future__ import annotations

import mimetypes
import os
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from kauta.motor import fmt_dinero

from ..modelos import Factura, Pago, Usuario
from ..seguridad.permisos import tiene
from . import agente, correo, pagos

ACTIVOS = os.environ.get("KAUTA_AVISOS", "1") != "0"
MAX_ADJUNTO = 8 * 1024 * 1024
CANAL = {"pdf": "PDF", "imagen": "foto o imagen", "correo": "correo", "chat": "chat de WhatsApp", "xml": "XML fiscal"}
Mensaje = tuple[str, str, str, list]


def _personas(bd: Session, permiso: str, excluir: set[str]) -> list[Usuario]:
    return [u for u in bd.execute(select(Usuario).where(Usuario.activo.is_(True))).scalars()
            if tiene(u.rol, permiso) and u.rol != "admin" and u.correo.lower() not in excluir]


def _adjunto(bd: Session, f: Factura) -> list:
    datos = agente.leer_archivo(bd, f.ruta_archivo)
    if datos is None or len(datos) > MAX_ADJUNTO:
        return []
    return [(f.archivo, datos, mimetypes.guess_type(f.archivo)[0] or "application/octet-stream")]


def _monto(f: Factura) -> str:
    texto = fmt_dinero(f.monto, f.moneda) if f.monto is not None else "monto sin leer"
    return texto + (f" (≈ {fmt_dinero(f.monto_usd)})" if f.moneda and f.moneda != "USD" and f.monto_usd is not None else "")


def factura_recibida(bd: Session, f: Factura, umbral: Decimal, quien_cargo: str) -> list[Mensaje]:
    """El aviso de una factura nueva, con el documento adjunto, a quien la revisa."""
    if not ACTIVOS:
        return []
    alto = f.estado == "pendiente" and Decimal(f.monto_usd or 0) > umbral
    if f.estado == "pendiente":
        personas = _personas(bd, "facturas.firma_alta" if alto else "facturas.aprobar", {quien_cargo.lower()})
        asunto = f"Kauta te pregunta · {f.id} · {f.beneficiario_nombre} · {_monto(f)}"
        accion = ("Supera el umbral de aprobación: la aprueba el CEO y después Finanzas la paga." if alto else
                  "Respóndale a Kauta y apruébela o recházela con su token.")
    else:
        personas = _personas(bd, "pagos.ejecutar", {quien_cargo.lower()})
        asunto = {"pagada": f"Kauta pagó {f.id}", "frenada": f"Kauta frenó {f.id}"}.get(f.estado, f"Factura {f.id}") + \
            f" · {f.beneficiario_nombre} · {_monto(f)}"
        accion = {"pagada": "No tiene que hacer nada: cumplió las 13 reglas y Kauta la pagó sola.",
                  "frenada": "Rompe una regla dura: no se paga, ni con aprobación."}.get(f.estado, "")
    texto = (f"Llegó una factura por {CANAL.get(f.canal, f.canal)}.\n\n"
             f"Factura: {f.id} · {f.numero or 'sin número'}\nProveedor: {f.beneficiario_nombre}\nMonto: {_monto(f)}\n"
             f"Vence: {f.fecha_vencimiento or 'sin fecha'}\nLectura: {f.modelo}\n\nDecisión de Kauta: {f.motivo}\n\n{accion}\n\n"
             f"Ábrala en Kauta: {correo.enlace('facturas/' + f.id)}\nAdjunto: el documento tal como llegó.")
    adj = _adjunto(bd, f)
    return [(u.correo, asunto, f"Hola, {u.nombre}:\n\n{texto}", adj) for u in personas]


def factura_aprobada(bd: Session, f: Factura, aprobo: Usuario) -> list[Mensaje]:
    if not ACTIVOS:
        return []
    texto = (f"{aprobo.nombre} aprobó la factura {f.id} de {f.beneficiario_nombre} por {_monto(f)}.\n"
             f"Queda lista para pagar: páguela con su token en {correo.enlace('pagos')}\n"
             "(con la ventana de PayPal o con el pago directo).")
    return [(u.correo, f"Lista para pagar · {f.id} · {f.beneficiario_nombre} · {_monto(f)}", f"Hola, {u.nombre}:\n\n{texto}", [])
            for u in _personas(bd, "pagos.ejecutar", {aprobo.correo.lower()})]


def pago_resuelto(bd: Session, p: Pago, f: Factura, pago_por: Usuario) -> list[Mensaje]:
    if not ACTIVOS:
        return []
    resultado = {"exitoso": "exitoso", "en_proceso": "en proceso", "fallido": "fallido", "negado": "negado"}.get(
        pagos.RESULTADOS.get(p.estado, p.estado), p.estado)
    aprobaron = {a.usuario_id for a in f.aprobaciones if a.accion == "aprobar"}
    personas = [u for u in bd.execute(select(Usuario).where(Usuario.id.in_(aprobaron))).scalars() if u.id != pago_por.id]
    texto = (f"{pago_por.nombre} pagó la factura {f.id} de {f.beneficiario_nombre}: pago {resultado} ({p.id}, {pagos.RIELES[p.riel]['nombre']}).\n"
             + (f"Motivo: {p.motivo_devolucion}\n" if p.motivo_devolucion else "")
             + f"Detalle: {correo.enlace('facturas/' + f.id)}")
    return [(u.correo, f"Pago {resultado} · {f.id} · {f.beneficiario_nombre}", f"Hola, {u.nombre}:\n\n{texto}", []) for u in personas]
