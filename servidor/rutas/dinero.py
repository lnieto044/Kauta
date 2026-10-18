"""Wallet, pagos, rieles y comprobantes."""
from __future__ import annotations

import io
from decimal import Decimal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select

from kauta import motor
from kauta import rutas as rutas_reto

from ..config import CONFIG
from ..esquemas import AprobarRutaIn, CheckoutSimuladoIn, FondearIn, PagarIn, ReintentarIn
from ..db import obtener_bd
from ..modelos import Asiento, Factura, Pago, RutaAprobada
from ..seguridad import firma
from ..seguridad.limites import limitar
from ..seguridad.sesiones import Contexto, requiere
from ..servicios import BLOQUEO, agente, auditoria, autorizacion, avisos, conciliacion, correo, pagos, paypal, wallet
from ..servicios.agente import ErrorNegocio
from .. import vistas

r = APIRouter(prefix="/api", tags=["Dinero"])


@r.get("/wallet")
def ver_wallet(ctx: Contexto = Depends(requiere("ver"))):
    reglas = agente.reglas_vigentes(ctx.bd)
    res = wallet.resumen(ctx.bd)
    asientos = ctx.bd.execute(select(Asiento).order_by(Asiento.id.desc()).limit(40)).scalars().all()
    from ..servicios.simulador import disponible_periodo
    periodos = []
    for per in wallet.periodos_fondeados(ctx.bd):
        disp = float(disponible_periodo(ctx.bd, reglas, per))
        presupuesto = float(motor.presupuesto_de(reglas, per))
        periodos.append({"periodo": per, "presupuesto": presupuesto, "disponible": disp, "pagado": round(presupuesto - disp, 2)})
    res.update({
        "periodo": reglas["periodo_actual"], "presupuesto": reglas["presupuesto_periodo_usd"], "periodos": periodos,
        "libro": wallet.verificar_libro(ctx.bd),
        "asientos": [{"id": a.id, "fecha": vistas.iso(a.fecha), "tipo": a.tipo, "descripcion": a.descripcion,
                      "referencia": a.referencia,
                      "movimientos": [{"cuenta": m.cuenta, "debito": float(m.debito), "credito": float(m.credito)} for m in a.movimientos]}
                     for a in asientos],
    })
    return res


@r.post("/wallet/fondear")
def fondear(datos: FondearIn, ctx: Contexto = Depends(requiere("wallet.fondear"))):
    with BLOQUEO:
        reglas = agente.reglas_vigentes(ctx.bd)
        wallet.transferir(ctx.bd, "fondeo", f"Depósito simulado a la cuenta operativa por {ctx.actor}", "FONDEO",
                          reglas["periodo_actual"], "fondeo", "operativa", Decimal(str(datos.monto)))
        auditoria.registrar(ctx.bd, "wallet.fondeo", ctx.actor, "wallet", "operativa", f"Depósito simulado de USD {datos.monto:,.2f}.", {})
        ctx.bd.commit()
    return wallet.resumen(ctx.bd)


@r.get("/pagos")
def listar_pagos(ctx: Contexto = Depends(requiere("ver"))):
    return [pagos.a_dict(p) for p in ctx.bd.execute(select(Pago).order_by(Pago.creado_en.desc(), Pago.id.desc())).scalars()]


@r.get("/pagos/{pid}")
def ver_pago(pid: str, ctx: Contexto = Depends(requiere("ver"))):
    p = ctx.bd.get(Pago, pid)
    if not p:
        raise HTTPException(404, "Pago no encontrado.")
    return pagos.a_dict(p)


@r.post("/pagos/{pid}/reintentar")
def reintentar(pid: str, datos: ReintentarIn, ctx: Contexto = Depends(requiere("pagos.reintentar"))):
    with BLOQUEO:
        p = ctx.bd.get(Pago, pid)
        if not p or p.estado != "devuelto":
            raise HTTPException(409, "Solo se reintentan pagos devueltos.")
        f = ctx.bd.get(Factura, p.factura_id)
        from kauta import motor
        reglas = agente.reglas_vigentes(ctx.bd)
        d = motor.evaluar({"factura_id": f.id, "extraccion": f.extraccion, "hashes": f.hashes}, reglas,
                          agente.beneficiarios_motor(ctx.bd), agente.historial(ctx.bd, excluir=f.id))
        if d.fallas("frenar") or (d.decision != "pagar" and not any(a.accion == "aprobar" for a in f.aprobaciones)):
            raise HTTPException(409, "Antes de reintentar, Kauta volvió a evaluar la factura y ya no cumple: " + d.motivo)
        intento = len(ctx.bd.execute(select(Pago).where(Pago.factura_id == f.id)).scalars().all()) + 1
        try:
            nuevo = pagos.crear_y_ejecutar(ctx.bd, f, agente.reglas_vigentes(ctx.bd), ctx.actor, riel=datos.riel, intento=intento)
        except ValueError as e:
            raise HTTPException(409, str(e))
        if nuevo.estado != "devuelto":     # si el reintento también falla, la factura sigue devuelta
            f.estado = "pagada"
            f.motivo = f"Pagada en el intento {intento} por {nuevo.riel} tras la devolución de {pid}. " + f.motivo_inicial
        ctx.bd.commit()
    return pagos.a_dict(nuevo)


# ----------------------------------------------------------------- pagar facturas aprobadas
@r.post("/facturas/{fid}/pago/token")
def token_pago(fid: str, tareas: BackgroundTasks, ctx: Contexto = Depends(requiere("pagos.ejecutar"))):
    """Envía al correo de quien paga el token que autoriza ESTE pago: monto, riel y destino."""
    limitar(f"token-pago:{ctx.usuario.id}", 6, 600)
    try:
        t, mensaje = autorizacion.emitir_pago(ctx.bd, fid, ctx.usuario)
    except ErrorNegocio as e:
        raise HTTPException(409, str(e)) from None
    tareas.add_task(correo.enviar, *mensaje)
    return {"ok": True, "destino": autorizacion.enmascarar(ctx.usuario.correo), "minutos": autorizacion.MINUTOS,
            "vence_en": vistas.iso(t.expira_en), "autoriza": t.resumen, "entrega": correo.entrega(ctx.usuario.correo),
            "totp": ctx.usuario.mfa_activo, "codigo_demo": getattr(t, "codigo_demo", None)}


@r.post("/facturas/{fid}/pagar")
def pagar(fid: str, datos: PagarIn, tareas: BackgroundTasks, ctx: Contexto = Depends(requiere("pagos.ejecutar"))):
    """Paga una factura aprobada. Responde siempre con el resultado: exitoso, en proceso, fallido o negado."""
    limitar(f"pagar:{ctx.usuario.id}", 20, 600)
    try:
        autorizacion.verificar_pago(ctx.bd, fid, ctx.usuario, datos.token)
        p, mensaje, enlace = agente.pagar(ctx.bd, fid, ctx.usuario, datos.metodo, CONFIG.origen)
    except ErrorNegocio as e:
        raise HTTPException(409, str(e)) from None
    except autorizacion.ErrorToken as e:
        raise HTTPException(403, str(e)) from None
    if not enlace:                         # el resultado ya se conoce: avisa a quien aprobó
        for m in avisos.pago_resuelto(ctx.bd, p, ctx.bd.get(Factura, fid), ctx.usuario):
            tareas.add_task(correo.enviar, *m)
    return {"resultado": pagos.RESULTADOS.get(p.estado, p.estado), "mensaje": mensaje, "pago": pagos.a_dict(p),
            "aprobar_en_paypal": enlace}


# --------------------------------------------- vuelta desde la ventana de PayPal (Checkout)
# PayPal devuelve el navegador con ?token=<orden>. La cookie de sesión es SameSite=Strict y no viaja en esa redirección
# entre sitios: la orden, que nadie más conoce, es la prueba. Kauta cobra solo si la orden coincide con el pago en espera.
def _volver(request: Request, bd, pago: str, token: str, aprobado: bool):
    limitar(f"paypal-volver:{request.client.host if request.client else 'x'}", 30, 60)
    with BLOQUEO:
        p = bd.get(Pago, pago)
        if p and p.estado == "reservado":
            try:
                pagos.completar_checkout(bd, p, token, aprobado)
                bd.commit()
            except ValueError:
                bd.rollback()
    return RedirectResponse(f"/#/pagos/{pago}", status_code=303)


@r.get("/paypal/volver", include_in_schema=False)
def paypal_volver(request: Request, pago: str = "", token: str = "", bd=Depends(obtener_bd)):
    return _volver(request, bd, pago, token, True)


@r.get("/paypal/cancelar", include_in_schema=False)
def paypal_cancelar(request: Request, pago: str = "", token: str = "", bd=Depends(obtener_bd)):
    return _volver(request, bd, pago, token, False)


@r.post("/pagos/{pid}/checkout/simulado")
def checkout_simulado(pid: str, datos: CheckoutSimuladoIn, ctx: Contexto = Depends(requiere("pagos.ejecutar"))):
    """Sin credenciales de PayPal, la ventana de PayPal se simula en Kauta: aprobar o rechazar el pago en espera."""
    with BLOQUEO:
        p = ctx.bd.get(Pago, pid)
        if not p or p.datos_firmados.get("modo_paypal") != "simulado" or p.estado != "reservado":
            raise HTTPException(409, "Ese pago no está esperando una aprobación simulada.")
        p, mensaje = pagos.completar_checkout(ctx.bd, p, p.referencia, datos.aprobar)
        ctx.bd.commit()
    return {"resultado": pagos.RESULTADOS.get(p.estado, p.estado), "mensaje": mensaje, "pago": pagos.a_dict(p)}


@r.post("/pagos/{pid}/checkout/cancelar")
def checkout_cancelar(pid: str, ctx: Contexto = Depends(requiere("pagos.ejecutar"))):
    """Cancela un pago que quedó esperando en PayPal (por ejemplo, si se cerró la ventana): la reserva vuelve a la wallet."""
    with BLOQUEO:
        p = ctx.bd.get(Pago, pid)
        if not p or p.estado != "reservado" or p.datos_firmados.get("metodo") != "checkout":
            raise HTTPException(409, "Ese pago no está esperando en PayPal.")
        p, mensaje = pagos.completar_checkout(ctx.bd, p, p.referencia, False)
        ctx.bd.commit()
    return {"resultado": pagos.RESULTADOS.get(p.estado, p.estado), "mensaje": mensaje, "pago": pagos.a_dict(p)}


@r.get("/tablero/pagos")
def tablero_pagos(ctx: Contexto = Depends(requiere("ver"))):
    """Pagos de punta a punta: lo que está listo para pagar, lo que espera aprobación y el resultado de cada pago."""
    fs = {f.id: f for f in ctx.bd.execute(select(Factura)).scalars()}
    reglas = agente.reglas_vigentes(ctx.bd)
    umbral = float(reglas["umbral_aprobacion_usd"])
    usd = lambda f: float(f.monto_usd or 0)

    def fila(f: Factura) -> dict:
        d = vistas.factura_resumen(ctx.bd, f)
        d["aprobada_por"] = [a.usuario_nombre for a in f.aprobaciones if a.accion == "aprobar"]
        d["riel_nombre"] = pagos.RIELES[f.riel_pago or pagos.RIEL_PAGOS]["nombre"]
        d["aprueba"] = "CEO" if usd(f) > umbral else "Finanzas o CEO"
        return d

    lista_pagos = ctx.bd.execute(select(Pago).order_by(Pago.creado_en.desc())).scalars().all()
    salida_pagos = []
    for p in lista_pagos:
        d = pagos.a_dict(p)
        f = fs.get(p.factura_id)
        d["factura_numero"] = f.numero if f else None
        d["factura_estado"] = f.estado if f else None
        d["automatico"] = bool(f and not any(a.accion == "aprobar" for a in f.aprobaciones))
        salida_pagos.append(d)
    negadas = [f for f in fs.values() if f.estado in ("frenada", "rechazada")]

    def total(lista, campo="monto_usd"):
        return round(sum(float(x[campo] if isinstance(x, dict) else (x.monto_usd or 0)) for x in lista), 2)

    grupos = {k: [d for d in salida_pagos if d["resultado"] == k] for k in ("exitoso", "en_proceso", "fallido", "negado")}
    por_pagar = sorted((f for f in fs.values() if f.estado == "aprobada"), key=lambda f: f.fecha_vencimiento or "9999")
    esperan = [f for f in fs.values() if f.estado == "pendiente"]
    return {
        "umbral_usd": umbral,
        "paypal": {"modo": paypal.modo(), "receptor": paypal.receptor_enmascarado() if paypal.configurado() else None},
        "por_pagar": [fila(f) for f in por_pagar],
        "esperan_aprobacion": {"facturas": len(esperan), "usd": round(sum(usd(f) for f in esperan), 2),
                               "del_ceo": sum(1 for f in esperan if usd(f) > umbral)},
        "resumen": {
            "por_pagar": {"pagos": len(por_pagar), "usd": round(sum(usd(f) for f in por_pagar), 2)},
            **{k: {"pagos": len(v), "usd": total(v)} for k, v in grupos.items()},
            "facturas_negadas": {"facturas": len(negadas), "usd": round(sum(usd(f) for f in negadas), 2)},
        },
        "pagos": salida_pagos,
        "facturas_negadas": [{**vistas.factura_resumen(ctx.bd, f),
                              "negada_por": ("Kauta (reglas)" if f.estado == "frenada" else
                                             next((a.usuario_nombre for a in f.aprobaciones if a.accion == "rechazar"), "Una persona"))}
                             for f in sorted(negadas, key=lambda f: f.recibida_en, reverse=True)],
    }


@r.get("/rutas-pago")
def rutas_de_pago(ctx: Contexto = Depends(requiere("reportes.ver"))):
    """Ruta de menor costo por historia del reto (respetando la reserva de cada entidad) y el análisis del día a día."""
    datos = rutas_reto.resumen()
    for h in datos["historias"]:
        a = ctx.bd.execute(select(RutaAprobada).where(RutaAprobada.historia == h["historia"])
                           .order_by(RutaAprobada.id.desc())).scalars().first()
        vigente = a is not None and a.opciones == [o["opcion_id"] for o in h["kauta"]["opciones"]]
        h["aprobacion"] = ({"aprobada_por": a.aprobada_por, "comentario": a.comentario, "creada_en": vistas.iso(a.creada_en),
                            "huella": a.huella} if vigente else None)
    return datos


@r.post("/rutas-pago/{historia}/aprobar")
def aprobar_ruta(historia: str, datos: AprobarRutaIn, ctx: Contexto = Depends(requiere("rutas.aprobar"))):
    """El CEO aprueba la ruta propuesta: queda firmada (HMAC) sobre las alternativas exactas y en la auditoría."""
    if historia not in ("H1", "H2", "H3"):
        raise HTTPException(404, "Historia desconocida.")
    h = rutas_reto.optimizar_historia(historia)
    elegidas = [o["opcion_id"] for o in h["kauta"]["opciones"]]
    with BLOQUEO:
        huella = firma.huella({"historia": historia, "opciones": elegidas, "costo": h["kauta"]["costo_usd"]})
        a = RutaAprobada(historia=historia, opciones=elegidas, costo_usd=Decimal(str(h["kauta"]["costo_usd"])),
                         ahorro_usd=Decimal(str(h["ahorro_usd"])), huella=huella, aprobada_por=ctx.actor, comentario=datos.comentario)
        ctx.bd.add(a)
        auditoria.registrar(ctx.bd, "ruta.aprobada", ctx.actor, "ruta", historia,
                            f"Ruta {historia} aprobada: costo USD {h['kauta']['costo_usd']:,.2f}, ahorro USD {h['ahorro_usd']:,.2f}. "
                            f"«{datos.comentario[:160]}»", {"opciones": elegidas, "huella": huella,
                                                          "condiciones": h["kauta"]["condiciones"]})
        ctx.bd.commit()
    return {"ok": True, "huella": huella, "mensaje": f"Ruta {historia} aprobada. Finanzas puede ejecutarla cuando se cumplan sus condiciones."}


@r.get("/rieles")
def rieles(ctx: Contexto = Depends(requiere("ver"))):
    return pagos.rieles_publicos()


@r.get("/conciliacion")
def descargar_conciliacion(periodo: str | None = None, ctx: Contexto = Depends(requiere("reportes.ver"))):
    """CSV para Excel con cada factura del periodo: decisión, aprobaciones, pago, costos y motivo."""
    nombre, contenido = conciliacion.generar(ctx.bd, (periodo or "")[:7] or None)
    auditoria.registrar(ctx.bd, "conciliacion.descargada", ctx.actor, "periodo", nombre.removeprefix("kauta-conciliacion-").removesuffix(".csv"), f"Descargó {nombre}.", {})
    ctx.bd.commit()
    return Response(contenido, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{nombre}"'})


@r.get("/paypal/estado")
def estado_paypal(ctx: Contexto = Depends(requiere("ver"))):
    """Qué está configurado para pagar por el sandbox de PayPal (sin mostrar las credenciales)."""
    return paypal.estado()


@r.post("/paypal/probar")
def probar_paypal(ctx: Contexto = Depends(requiere("integraciones.probar"))):
    """Comprueba las credenciales del sandbox pidiendo un token; no crea pagos."""
    limitar(f"paypal-probar:{ctx.usuario.id}", 6, 60)
    try:
        ok, mensaje = paypal.probar()
    except paypal.ErrorPayPal as e:
        mensaje, ok = str(e), False
    auditoria.registrar(ctx.bd, "paypal.prueba", ctx.actor, "riel", "PAYPAL",
                        ("Prueba de conexión con el sandbox: correcta." if ok else f"Prueba de conexión con el sandbox: falló. {mensaje}"), {})
    ctx.bd.commit()
    return {"ok": ok, "mensaje": mensaje, "estado": paypal.estado()}


@r.post("/pagos/{pid}/paypal")
def consultar_paypal(pid: str, ctx: Contexto = Depends(requiere("pagos.reintentar"))):
    """Pregunta al sandbox de PayPal por un pago que quedó en proceso y lo liquida o lo devuelve."""
    limitar(f"paypal:{ctx.usuario.id}", 20, 60)
    with BLOQUEO:
        p = ctx.bd.get(Pago, pid)
        if not p:
            raise HTTPException(404, "Pago no encontrado.")
        try:
            p, mensaje = pagos.actualizar_paypal(ctx.bd, p, ctx.actor)
        except ValueError as e:
            raise HTTPException(409, str(e)) from None
        ctx.bd.commit()
    return {"mensaje": mensaje, "pago": pagos.a_dict(p)}


@r.get("/pagos/{pid}/comprobante")
def comprobante(pid: str, ctx: Contexto = Depends(requiere("ver"))):
    """Comprobante en PDF generado en el servidor (documento simulado, sin validez)."""
    p = ctx.bd.get(Pago, pid)
    if not p:
        raise HTTPException(404)
    from reportlab.lib.colors import HexColor
    from reportlab.lib.pagesizes import A5
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    W, H = A5
    c = canvas.Canvas(buf, pagesize=A5)
    c.setTitle(f"Comprobante {p.id}")
    c.setFillColor(HexColor("#0B1B3F"))
    c.rect(0, H - 70, W, 70, stroke=0, fill=1)
    c.setFillColor(HexColor("#FFFFFF"))
    c.setFont("Helvetica-Bold", 20)
    c.drawString(28, H - 44, "Kauta")
    c.setFont("Helvetica", 9)
    c.drawString(28, H - 60, "Comprobante de pago SIMULADO · Hackathon 30X · sin validez")
    filas = [("Pago", p.id), ("Estado", p.estado.upper()), ("Factura", p.factura_id), ("Beneficiario", p.beneficiario_nombre),
             ("Cuenta", (f"PayPal {p.datos_firmados.get('receptor_paypal')} · {p.datos_firmados.get('modo_paypal', 'simulado')}"
                         if p.riel == "PAYPAL" else f"···{p.cuenta_ultimos4} · titular confirmado: {p.titular_confirmado or '—'}")),
             ("Riel", pagos.RIELES.get(p.riel, {}).get("nombre", p.riel)), ("Referencia", p.referencia[:44]),
             ("Monto de la factura", f"{p.moneda_factura} {p.monto_factura:,.2f}"),
             ("Recibe el beneficiario", f"{p.moneda_destino} {p.monto_destino:,.2f}"),
             ("Tasa aplicada", f"{p.tasa_aplicada:,.4f} {p.moneda_destino}/USD" if p.moneda_destino != "USD" else "No aplica"),
             ("Costo base", f"USD {p.monto_usd:,.2f}"), ("Comisión del riel", f"USD {p.comision_usd:,.2f}"),
             ("Costo cambiario", f"USD {p.costo_fx_usd:,.2f}"),
             ("Costo total", f"USD {p.monto_usd + p.comision_usd + p.costo_fx_usd:,.2f}"),
             ("Firma de la orden", p.firma[:32]), ("Idempotencia", p.clave_idempotencia[:44]),
             ("Creado", p.creado_en.strftime("%Y-%m-%d %H:%M:%S UTC"))]
    y = H - 100
    for k, v in filas:
        c.setFillColor(HexColor("#5B6782"))
        c.setFont("Helvetica", 8.5)
        c.drawString(28, y, k)
        c.setFillColor(HexColor("#1A1F2B"))
        c.setFont("Helvetica-Bold", 8.5)
        c.drawString(150, y, str(v))
        y -= 17
    if p.motivo_devolucion:
        c.setFillColor(HexColor("#C2410C"))
        c.drawString(28, y - 6, f"Devuelto: {p.motivo_devolucion}"[:90])
    c.setFillColor(HexColor("#5B6782"))
    c.setFont("Helvetica", 7)
    c.drawString(28, 24, "Ningún dinero real se movió. Documento generado por el simulador de pagos de Kauta.")
    c.save()
    return Response(buf.getvalue(), media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="comprobante-{p.id}.pdf"'})
