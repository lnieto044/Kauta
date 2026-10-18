"""Facturas, aprobaciones (Kauta pregunta), proveedores, cambios de cuenta y reglas."""
from __future__ import annotations

import io
import re
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select

from ..config import CONFIG, RAIZ, VAR
from ..esquemas import AprobarIn, RechazarIn, ReglasIn, TokenFacturaIn, VerificarCambioIn
from ..modelos import Beneficiario, CambioCuenta, Factura, VersionReglas, ahora
from ..seguridad.cifrado import cifrar, descifrar
from ..seguridad.limites import limitar
from ..seguridad.sesiones import Contexto, requiere
from ..servicios import BLOQUEO, agente, auditoria, autorizacion, avisos, correo, wallet
from ..servicios.agente import ErrorNegocio
from .. import vistas

r = APIRouter(prefix="/api", tags=["Negocio"])
FIRMAS = {b"%PDF-": ".pdf", b"\x89PNG": ".png", b"\xff\xd8\xff": ".jpg", b"PK\x03\x04": ".zip"}
PERMITIDAS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".eml", ".txt", ".xml"}   # el ZIP ya no es un canal de carga


def _tipo_real(nombre: str, datos: bytes) -> str:
    """Valida por contenido (bytes mágicos), no solo por la extensión que dice el archivo."""
    ext = Path(nombre).suffix.lower()
    if ext not in PERMITIDAS:
        raise HTTPException(415, f"Tipo de archivo no permitido ({ext or 'sin extensión'}).")
    for firma, e in FIRMAS.items():
        if datos.startswith(firma):
            if e != ext and not (e == ".jpg" and ext == ".jpeg"):
                raise HTTPException(415, f"El contenido es {e} pero el nombre dice {ext}: archivo sospechoso.")
            return e
    if ext == ".webp" and datos[:4] == b"RIFF" and datos[8:12] == b"WEBP":
        return ext
    if ext in (".eml", ".txt", ".xml"):
        try:
            datos[:65536].decode("utf-8")
        except UnicodeDecodeError:
            raise HTTPException(415, "El archivo de texto no es UTF-8 válido.")
        return ext
    raise HTTPException(415, "El contenido del archivo no coincide con su tipo.")


@r.get("/facturas")
def listar(estado: str | None = None, q: str | None = None, ctx: Contexto = Depends(requiere("ver"))):
    consulta = select(Factura).order_by(Factura.recibida_en.desc(), Factura.id.desc())
    if estado:
        consulta = consulta.where(Factura.estado == estado)
    filas = ctx.bd.execute(consulta).scalars().all()
    if q:
        t = q.lower()[:60]
        filas = [f for f in filas if t in f"{f.id} {f.beneficiario_nombre} {f.numero} {f.archivo}".lower()]
    return [vistas.factura_resumen(ctx.bd, f) for f in filas]


@r.get("/facturas/{fid}")
def detalle(fid: str, ctx: Contexto = Depends(requiere("ver"))):
    f = ctx.bd.get(Factura, fid)
    if not f:
        raise HTTPException(404, "Factura no encontrada.")
    return vistas.factura_detalle(ctx.bd, f)


@r.get("/facturas/{fid}/vista")
def vista(fid: str, ctx: Contexto = Depends(requiere("ver"))):
    """Vista previa como PNG re-codificado (nunca se entrega el archivo original al navegador)."""
    f = ctx.bd.get(Factura, fid)
    if not f:
        raise HTTPException(404)
    previa = RAIZ / "data" / "previews" / f"{f.id}.png"
    if f.origen == "set" and previa.exists():
        return FileResponse(previa, media_type="image/png", headers={"Content-Disposition": "inline"})
    cache = VAR / "vistas" / f"{f.hash_documento}.png"
    if not cache.exists() and f.ruta_archivo:
        cache.parent.mkdir(parents=True, exist_ok=True)
        datos = agente.leer_archivo(ctx.bd, f.ruta_archivo)
        if datos is None:
            raise HTTPException(404, "No hay vista previa para este documento.")
        try:
            from PIL import Image
            if datos.startswith(b"%PDF-"):
                import pypdfium2 as pdfium
                doc = pdfium.PdfDocument(datos)
                img = doc[0].render(scale=1.3).to_pil()
                doc.close()
            elif f.canal == "imagen":
                img = Image.open(io.BytesIO(datos))
                img.thumbnail((1400, 1400))
            elif f.canal == "correo":
                from kauta.extractor import leer_documento
                d = leer_documento(f.archivo, datos)
                if d["pdfs"]:
                    import pypdfium2 as pdfium
                    doc = pdfium.PdfDocument(d["pdfs"][0])
                    img = doc[0].render(scale=1.3).to_pil()
                    doc.close()
                elif d["imagenes"]:
                    img = Image.open(io.BytesIO(d["imagenes"][0][1]))
                else:
                    raise HTTPException(404)
            else:
                raise HTTPException(404)
            img.convert("RGB").save(cache, "PNG")  # re-codificar elimina metadatos y contenido incrustado
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(404, "No hay vista previa para este documento.")
    if not cache.exists():
        raise HTTPException(404)
    return FileResponse(cache, media_type="image/png", headers={"Content-Disposition": "inline"})


@r.post("/facturas/cargar")
async def cargar(tareas: BackgroundTasks, archivo: UploadFile = File(...), ctx: Contexto = Depends(requiere("facturas.cargar"))):
    limitar(f"carga:{ctx.usuario.id}", 30, 60)
    tope = CONFIG.max_archivo_mb * 1024 * 1024
    datos = await archivo.read(tope + 1)
    if len(datos) > tope:
        raise HTTPException(413, f"El archivo supera {CONFIG.max_archivo_mb} MB.")
    nombre = re.sub(r"[^\w.\-]", "_", Path(archivo.filename or "documento").name)[:100]
    _tipo_real(nombre, datos)
    try:
        f = agente.procesar_archivo(ctx.bd, nombre, datos, "carga", ctx.actor, ctx.usuario.correo)
    except ErrorNegocio as e:
        raise HTTPException(422, str(e))
    umbral = Decimal(str(agente.reglas_vigentes(ctx.bd)["umbral_aprobacion_usd"]))
    for m in avisos.factura_recibida(ctx.bd, f, umbral, ctx.usuario.correo):   # la factura llega al correo de quien la revisa
        tareas.add_task(correo.enviar, *m)
    return vistas.factura_detalle(ctx.bd, f)


DOCS_EJEMPLO = RAIZ / "data" / "reto" / "documentos"
EJEMPLOS = [   # un archivo por canal, para probar la lectura con un clic (no se cargan como facturas)
    ("F25_bricksave-proveedor-16_SIM-2026-000016.jpg", "imagen", "Foto (en portugués)"),
    ("F31_braven-proveedor-63_SIM-2026-000063.png", "imagen", "Imagen escaneada"),
    ("F27_bricksave-proveedor-11_SIM-2026-000011.pdf", "pdf", "PDF"),
    ("F26_dapta-proveedor-35_SIM-2026-000035.txt", "chat", "Chat de WhatsApp"),
    ("F28_bricksave-proveedor-21_SIM-2026-000021.eml", "correo", "Correo"),
    ("F23_bricksave-proveedor-13_SIM-2026-000013.xml", "xml", "XML fiscal (CFDI)"),
]


@r.get("/lectura/ejemplos")
def ejemplos_lectura(ctx: Contexto = Depends(requiere("ver"))):
    return [{"nombre": n, "canal": c, "titulo": t} for n, c, t in EJEMPLOS if (DOCS_EJEMPLO / n).exists()]


@r.get("/lectura/ejemplos/{nombre}")
def ejemplo_lectura(nombre: str, ctx: Contexto = Depends(requiere("ver"))):
    if nombre not in {n for n, _, _ in EJEMPLOS} or not (DOCS_EJEMPLO / nombre).exists():
        raise HTTPException(404, "Ese ejemplo no existe.")
    import mimetypes
    return FileResponse(DOCS_EJEMPLO / nombre, media_type=mimetypes.guess_type(nombre)[0] or "application/octet-stream",
                        filename=nombre)


@r.post("/lectura/probar")
async def probar_lectura(archivo: UploadFile = File(...), ctx: Contexto = Depends(requiere("ver"))):
    """
    Lee un documento paso a paso (canal, XML, texto del PDF, OCR, chat o correo) y dice qué haría Kauta con él,
    SIN crear la factura ni mover dinero. Muestra lo que Kauta lee sola: no usa las extracciones de referencia de la demo.
    """
    limitar(f"lectura:{ctx.usuario.id}", 20, 60)
    tope = CONFIG.max_archivo_mb * 1024 * 1024
    datos = await archivo.read(tope + 1)
    if len(datos) > tope:
        raise HTTPException(413, f"El archivo supera {CONFIG.max_archivo_mb} MB.")
    nombre = re.sub(r"[^\w.\-]", "_", Path(archivo.filename or "documento").name)[:100]
    _tipo_real(nombre, datos)
    from dataclasses import asdict

    from kauta import motor
    from kauta.extractor import leer_paso_a_paso
    r = leer_paso_a_paso(nombre, datos)
    ext, reglas, decision = r["extraccion"], agente.reglas_vigentes(ctx.bd), None
    if ext:
        d = motor.evaluar({"factura_id": "PRUEBA", "extraccion": ext, "hashes": r["doc"]["hashes"]}, reglas,
                          agente.beneficiarios_motor(ctx.bd), agente.historial(ctx.bd))
        decision = {"decision": d.decision, "motivo": d.motivo, "beneficiario": d.beneficiario_nombre,
                    "monto_usd": float(d.monto_usd) if d.monto_usd is not None else None, "reglas": [asdict(x) for x in d.reglas]}
    auditoria.registrar(ctx.bd, "lectura.prueba", ctx.actor, "documento", r["doc"]["hashes"][0][:16],
                        f"Prueba de lectura de {nombre} ({r['doc']['canal']}): {r['como'] or 'no se pudo leer'}.", {})
    ctx.bd.commit()
    return {"nombre": nombre, "canal": r["doc"]["canal"], "bytes": len(datos), "pasos": r["pasos"], "como": r["como"],
            "texto": r["texto"][:8000], "palabras": r["palabras"], "extraccion": ext, "decision": decision,
            "en_demo": nombre in agente.EXTRACTOR.ref.ref, "confianza_minima": reglas.get("confianza_minima", 0.85)}


# ----------------------------------------------------------------- buzón de prueba: las 50 facturas del Excel
CARPETA_PRUEBAS = RAIZ / "facturas_de_prueba"
BUZON_EMPRESA = "buzon@brisamar.example"


def _indice_pruebas() -> list[dict]:
    import csv
    ruta = CARPETA_PRUEBAS / "INDICE.csv"
    if not ruta.exists():
        return []
    return [x for x in csv.DictReader(open(ruta, encoding="utf-8-sig"), delimiter=";") if (CARPETA_PRUEBAS / x["archivo"]).exists()]


@r.get("/buzon/pruebas")
def buzon_pruebas(ctx: Contexto = Depends(requiere("facturas.cargar"))):
    """Las facturas de facturas_de_prueba/ y si ya llegaron (por su huella)."""
    import hashlib
    llegadas = {f.hash_documento: f for f in ctx.bd.execute(select(Factura)).scalars()}
    salida = []
    for x in _indice_pruebas():
        f = llegadas.get(hashlib.sha256((CARPETA_PRUEBAS / x["archivo"]).read_bytes()).hexdigest())
        salida.append({**x, "factura": f.id if f else None, "estado": f.estado if f else None})
    return salida


@r.post("/buzon/pruebas/{archivo}/recibir")
def recibir_prueba(archivo: str, tareas: BackgroundTasks, ctx: Contexto = Depends(requiere("facturas.cargar"))):
    """La factura llega por el correo de la empresa, como si la enviara el proveedor: quien prueba la puede aprobar."""
    limitar(f"buzon:{ctx.usuario.id}", 60, 60)
    if archivo not in {x["archivo"] for x in _indice_pruebas()}:
        raise HTTPException(404, "Ese archivo no está en el buzón de prueba.")
    datos = (CARPETA_PRUEBAS / archivo).read_bytes()
    try:
        f = agente.procesar_archivo(ctx.bd, archivo, datos, "buzon", f"Buzón de la empresa (recibido por {ctx.usuario.nombre})",
                                    BUZON_EMPRESA)
    except ErrorNegocio as e:
        raise HTTPException(422, str(e))
    umbral = Decimal(str(agente.reglas_vigentes(ctx.bd)["umbral_aprobacion_usd"]))
    for m in avisos.factura_recibida(ctx.bd, f, umbral, BUZON_EMPRESA):   # el aviso con la factura llega a quien la revisa
        tareas.add_task(correo.enviar, *m)
    return vistas.factura_resumen(ctx.bd, f)


@r.post("/facturas/sorpresa")
def sorpresa(ctx: Contexto = Depends(requiere("facturas.cargar"))):
    """Procesa los XML de data/sorpresa (XML fiscal, un XML malicioso y una nota crédito)."""
    hechas = []
    for p in sorted((RAIZ / "data" / "sorpresa").glob("S0*.xml")):
        if ctx.bd.get(Factura, p.name[:3]):
            continue
        f = agente.procesar_archivo(ctx.bd, p.name, p.read_bytes(), "sorpresa", ctx.actor, ctx.usuario.correo)
        hechas.append(vistas.factura_resumen(ctx.bd, f))
    return hechas


@r.post("/facturas/{fid}/token")
def token_aprobacion(fid: str, datos: TokenFacturaIn, tareas: BackgroundTasks,
                     ctx: Contexto = Depends(requiere("facturas.aprobar"))):
    """Envía al correo de quien aprueba el token de 6 dígitos que autoriza ESTA factura con ESTOS datos."""
    limitar(f"token-factura:{ctx.usuario.id}", 6, 600)
    correcciones = datos.correcciones.model_dump(exclude_none=True) if datos.correcciones else None
    try:
        t, mensaje = autorizacion.emitir(ctx.bd, fid, ctx.usuario, correcciones)
    except ErrorNegocio as e:
        raise HTTPException(409, str(e)) from None
    tareas.add_task(correo.enviar, *mensaje)
    return {"ok": True, "destino": autorizacion.enmascarar(ctx.usuario.correo), "minutos": autorizacion.MINUTOS,
            "vence_en": vistas.iso(t.expira_en), "autoriza": t.resumen, "entrega": correo.entrega(ctx.usuario.correo),
            "totp": ctx.usuario.mfa_activo, "codigo_demo": getattr(t, "codigo_demo", None)}


@r.post("/facturas/{fid}/aprobar")
def aprobar(fid: str, datos: AprobarIn, tareas: BackgroundTasks, ctx: Contexto = Depends(requiere("facturas.aprobar"))):
    """Aprobar exige el token de esta factura (o el código de la app autenticadora): una sesión robada no basta."""
    u = ctx.usuario
    if not datos.comentario.strip():
        raise HTTPException(409, "Escriba por qué aprueba: toda decisión humana debe quedar explicada.")
    correcciones = datos.correcciones.model_dump(exclude_none=True) if datos.correcciones else None
    try:
        autorizacion.verificar(ctx.bd, fid, u, correcciones, datos.token or datos.codigo_totp or "")
        r = agente.aprobar(ctx.bd, fid, u, datos.comentario, correcciones, con_mfa=True)
        if r.get("estado") == "aprobada":
            for m in avisos.factura_aprobada(ctx.bd, ctx.bd.get(Factura, fid), u):
                tareas.add_task(correo.enviar, *m)
        return r
    except ErrorNegocio as e:
        raise HTTPException(409, str(e)) from None
    except autorizacion.ErrorToken as e:
        raise HTTPException(403, str(e)) from None


@r.post("/facturas/{fid}/rechazar")
def rechazar(fid: str, datos: RechazarIn, ctx: Contexto = Depends(requiere("facturas.aprobar"))):
    try:
        return agente.rechazar(ctx.bd, fid, ctx.usuario, datos.comentario)
    except ErrorNegocio as e:
        raise HTTPException(409, str(e))


@r.get("/aprobaciones")
def bandeja_aprobaciones(ctx: Contexto = Depends(requiere("ver"))):
    pendientes = ctx.bd.execute(select(Factura).where(Factura.estado == "pendiente")
                                .order_by(Factura.recibida_en)).scalars().all()
    salida = []
    for f in pendientes:
        d = vistas.factura_resumen(ctx.bd, f)
        d["preguntas"] = vistas.preguntas(ctx.bd, f)
        d["plazo"] = vistas.plazo(ctx.bd, f)
        d["ya_aprobe"] = any(a.usuario_id == ctx.usuario.id for a in f.aprobaciones)
        d["cargue_yo"] = agente.cargada_por_mi(f, ctx.usuario.correo)
        d["aprobadores"] = [a.usuario_nombre for a in f.aprobaciones if a.accion == "aprobar"]
        salida.append(d)
    return salida


# ----------------------------------------------------------------- proveedores
@r.get("/proveedores")
def proveedores(ctx: Contexto = Depends(requiere("ver"))):
    return [vistas.beneficiario_dict(ctx.bd, b) for b in ctx.bd.execute(select(Beneficiario).order_by(Beneficiario.id)).scalars()]


@r.get("/cambios-cuenta")
def cambios(ctx: Contexto = Depends(requiere("ver"))):
    filas = ctx.bd.execute(select(CambioCuenta).order_by(CambioCuenta.creada_en.desc())).scalars().all()
    return [vistas.cambio_dict(ctx.bd, c) for c in filas]


@r.post("/cambios-cuenta/{cid}/verificar")
def verificar_cambio(cid: int, datos: VerificarCambioIn, ctx: Contexto = Depends(requiere("cuentas.verificar"))):
    with BLOQUEO:
        c = ctx.bd.get(CambioCuenta, cid)
        if not c or c.estado != "pendiente":
            raise HTTPException(409, "La solicitud no existe o ya se resolvió.")
        if c.solicitada_por == ctx.usuario.correo:
            raise HTTPException(409, "Segregación de funciones: quien pide el cambio no puede verificarlo.")
        b = ctx.bd.get(Beneficiario, c.beneficiario_id)
        c.verificada_por, c.metodo_verificacion, c.resuelta_en = ctx.actor, datos.metodo, ahora()
        if datos.aprobar:
            anterior = b.cuenta_ultimos4
            nueva = descifrar(c.cuenta_nueva_cifrada, aad=f"cambio:{b.id}")
            b.cuenta_cifrada = cifrar(f"Cuenta {nueva} · {c.banco_nuevo}", aad=f"cuenta:{b.id}")
            b.cuenta_ultimos4, b.banco = c.ultimos4_nuevos, f"{c.banco_nuevo} · verificada por llamada"
            b.verificada_por, b.verificada_en = f"{ctx.actor} · {datos.metodo}", ahora()
            c.estado = "aprobado"
            resumen = f"Cuenta de {b.nombre} cambiada de ···{anterior} a ···{c.ultimos4_nuevos} tras verificación: {datos.metodo}."
        else:
            c.estado = "rechazado"
            resumen = f"Cambio de cuenta de {b.nombre} rechazado ({datos.metodo}). {datos.comentario}".strip()
        auditoria.registrar(ctx.bd, "cuenta.cambio_" + c.estado, ctx.actor, "beneficiario", b.id, resumen,
                            {"solicitud": c.id, "comentario": datos.comentario})
        ctx.bd.commit()
    cambiadas = agente.reevaluar(ctx.bd, ctx.actor, beneficiario_id=c.beneficiario_id) if datos.aprobar else []
    return {"ok": True, "mensaje": resumen, "reevaluadas": cambiadas}


# ----------------------------------------------------------------- reglas
@r.get("/reglas")
def reglas(ctx: Contexto = Depends(requiere("ver"))):
    versiones = ctx.bd.execute(select(VersionReglas).order_by(VersionReglas.version.desc())).scalars().all()
    from kauta.motor import CATALOGO
    return {"vigente": {**versiones[0].parametros, "version": versiones[0].version},
            "catalogo": [{"id": k, **v} for k, v in CATALOGO.items()],
            "versiones": [{"version": v.version, "creada_por": v.creada_por, "creada_en": vistas.iso(v.creada_en),
                           "motivo": v.motivo, "cambios": v.cambios} for v in versiones]}


@r.put("/reglas")
def cambiar_reglas(datos: ReglasIn, ctx: Contexto = Depends(requiere("reglas.editar"))):
    with BLOQUEO:
        actual = agente.reglas_vigentes(ctx.bd)
        nuevos = datos.model_dump(exclude={"motivo"})
        cambios = {k: {"antes": actual.get(k), "despues": v} for k, v in nuevos.items() if actual.get(k) != v}
        if not cambios:
            raise HTTPException(409, "No hay cambios respecto a la versión vigente.")
        version = actual["version"] + 1
        parametros = {k: v for k, v in actual.items() if k != "version"} | nuevos
        ctx.bd.add(VersionReglas(version=version, parametros=parametros, creada_por=ctx.actor, motivo=datos.motivo, cambios=cambios))
        if "presupuesto_periodo_usd" in cambios:  # la sub-wallet se ajusta al nuevo presupuesto
            from decimal import Decimal
            delta = Decimal(str(nuevos["presupuesto_periodo_usd"])) - Decimal(str(actual["presupuesto_periodo_usd"]))
            desde, hacia = ("operativa", "cxp") if delta > 0 else ("cxp", "operativa")
            for per in wallet.periodos_fondeados(ctx.bd):
                if delta != 0:
                    wallet.transferir(ctx.bd, "fondeo", f"Ajuste de la sub-wallet de {per} por cambio de presupuesto (reglas v{version})",
                                      f"REGLAS-v{version}-{per}", per, desde, hacia, abs(delta))
        auditoria.registrar(ctx.bd, "reglas.cambio", ctx.actor, "reglas", str(version),
                            f"Reglas v{version}: " + "; ".join(f"{k}: {v['antes']} → {v['despues']}" for k, v in cambios.items())
                            + f". Motivo: {datos.motivo}", {"cambios": cambios})
        ctx.bd.commit()
    cambiadas = agente.reevaluar(ctx.bd, ctx.actor)
    return {"version": version, "cambios": cambios, "reevaluadas": cambiadas}


@r.post("/reglas/simular")
def simular_reglas(datos: ReglasIn, ctx: Contexto = Depends(requiere("ver"))):
    """¿Qué pasaría si…? Evalúa las facturas abiertas con reglas hipotéticas, sin guardar nada."""
    from kauta import motor
    actual = agente.reglas_vigentes(ctx.bd)
    hipotesis = {**actual, **datos.model_dump(exclude={"motivo"}), "version": actual["version"] + 1}
    bens = agente.beneficiarios_motor(ctx.bd)
    salida = []
    for f in ctx.bd.execute(select(Factura).where(Factura.estado.in_(("frenada", "pendiente")))
                            .order_by(Factura.recibida_en)).scalars():
        d = motor.evaluar({"factura_id": f.id, "extraccion": f.extraccion, "hashes": f.hashes}, hipotesis, bens,
                          agente.historial(ctx.bd, excluir=f.id))
        salida.append({"id": f.id, "beneficiario": f.beneficiario_nombre, "antes": f.decision, "despues": d.decision,
                       "motivo": d.motivo})
    return salida
