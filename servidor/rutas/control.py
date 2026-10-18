"""Resumen para el jurado, auditoría, centro de seguridad y restablecimiento de la demo."""
from __future__ import annotations

import platform
from collections import Counter
from datetime import date, datetime, timedelta, timezone

import fastapi
import sqlalchemy
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select

from ..config import CONFIG
from ..esquemas import RestablecerIn
from ..modelos import EventoAuditoria, Factura, Pago
from ..seguridad.cabeceras import CSP
from ..seguridad.cifrado import ID_CLAVE
from ..seguridad.limites import LIMITADOR
from ..seguridad.sesiones import Contexto, requiere
from kauta import ocr
from kauta import rutas as rutas_reto

from ..servicios import agente, auditoria, correo, costos, rendimiento, semilla, wallet
from .. import vistas

r = APIRouter(prefix="/api", tags=["Control"])


@r.get("/resumen")
def resumen(ctx: Contexto = Depends(requiere("ver"))):
    bd = ctx.bd
    m = agente.metricas(bd)
    reglas = agente.reglas_vigentes(bd)
    fs = bd.execute(select(Factura).order_by(Factura.recibida_en, Factura.id)).scalars().all()
    acumulado, serie = 0.0, []
    for f in fs:
        if f.estado == "pagada" and f.periodo == reglas["periodo_actual"]:
            acumulado += float(f.monto_usd or 0)
        serie.append({"id": f.id, "estado": f.estado, "acumulado": round(acumulado, 2)})
    fallas = Counter(r["id"] for f in fs for r in f.reglas if r["estado"] == "falla")
    pagos_ = bd.execute(select(Pago)).scalars().all()
    por_riel = Counter(p.riel for p in pagos_ if p.estado == "liquidado")
    ultimas = [vistas.factura_resumen(bd, f) for f in sorted(fs, key=lambda x: x.recibida_en, reverse=True)[:8]]
    # Todo lo recibido, por canal y por semana de llegada (hora de Bogotá), con lo que decidió Kauta al recibirlo
    canales: dict[str, dict] = {}
    semanas: dict[str, dict] = {}
    for f in fs:
        c = canales.setdefault(f.canal, {"canal": f.canal, "total": 0, "pagada": 0, "pendiente": 0, "frenada": 0, "otra": 0,
                                         "monto_usd": 0.0})
        c["total"] += 1
        c["pendiente" if f.estado == "aprobada" else f.estado if f.estado in ("pagada", "pendiente", "frenada") else "otra"] += 1
        c["monto_usd"] = round(c["monto_usd"] + float(f.monto_usd or 0), 2)
        dia = (f.recibida_en - timedelta(hours=5)).date()
        lunes = (dia - timedelta(days=dia.weekday())).isoformat()
        w = semanas.setdefault(lunes, {"desde": lunes, "pagar": 0, "escalar": 0, "frenar": 0})
        if f.decision_inicial in ("pagar", "escalar", "frenar"):
            w[f.decision_inicial] += 1
    return {"metricas": m, "wallet": wallet.resumen(bd), "presupuesto": reglas["presupuesto_periodo_usd"],
            "canales": sorted(canales.values(), key=lambda x: -x["total"]), "semanas": [semanas[k] for k in sorted(semanas)],
            "impacto": _impacto(fs, m),
            "periodo": reglas["periodo_actual"], "version_reglas": reglas["version"], "serie": serie,
            "fallas_por_regla": dict(sorted(fallas.items())), "pagos_por_riel": dict(por_riel), "ultimas": ultimas,
            "extractor": agente.EXTRACTOR.modo,
            "criterios": [
                {"criterio": "Autonomía", "valor": f"{m['autonomia_set_pct']:.0f} %",
                 "detalle": f"Del set oficial, Kauta resolvió sola (pagar o frenar) {m['autonomia_set_pct']:.0f} % en su primera decisión "
                            f"y acertó {m['set_aciertos']} de {m['set_total']}. Con todo lo procesado: {m['autonomia_pct']:.0f} %."},
                {"criterio": "Seguridad", "valor": f"{m['pagos_fuera_de_reglas']} pagos indebidos",
                 "detalle": f"Trampas del set detenidas: {m['trampas_detenidas']} de {m['trampas_total']}. Ningún pago sale fuera de las reglas."},
                {"criterio": "Explicabilidad", "valor": f"{m['explicadas_pct']:.0f} %",
                 "detalle": "Cada decisión trae su motivo en lenguaje claro y el resultado de las 13 reglas."},
            ]}


def _impacto(fs: list[Factura], m: dict) -> dict:
    """Lo que más pesa para la empresa: lo que falta pagar y cuándo vence, el riesgo de atraso, la exposición por moneda,
    la concentración en pocos proveedores, el dinero protegido y el ahorro posible con las rutas de pago."""
    hoy = (datetime.now(timezone.utc) - timedelta(hours=5)).date()
    lunes_hoy = hoy - timedelta(days=hoy.weekday())
    abiertas = [f for f in fs if f.estado in ("pendiente", "aprobada", "devuelta") and f.monto_usd is not None]
    semanas = [{"desde": (lunes_hoy + timedelta(weeks=i)).isoformat(), "espera": 0.0, "devuelta": 0.0, "facturas": 0} for i in range(6)]
    vencidas = {"espera": 0.0, "devuelta": 0.0, "facturas": 0}
    sin_fecha, prox7, prox30 = 0.0, [], []
    for f in abiertas:
        clave = "espera" if f.estado in ("pendiente", "aprobada") else "devuelta"
        try:
            vence = date.fromisoformat((f.extraccion or {}).get("fecha_vencimiento") or "")
        except ValueError:
            sin_fecha += float(f.monto_usd)
            continue
        if vence <= hoy + timedelta(days=7):
            prox7.append(f)
        if vence <= hoy + timedelta(days=30):
            prox30.append(f)
        destino = vencidas if vence < lunes_hoy else (semanas[(vence - lunes_hoy).days // 7] if (vence - lunes_hoy).days < 42 else None)
        if destino is not None:
            destino[clave] = round(destino[clave] + float(f.monto_usd), 2)
            destino["facturas"] += 1
    activas = [f for f in fs if f.estado != "rechazada" and f.monto_usd is not None]
    # Comprometido = pagado + por pagar (lo frenado no sale de la caja)
    total = sum(float(f.monto_usd) for f in activas if f.estado != "frenada") or 1.0
    monedas: dict[str, dict] = {}
    proveedores: dict[str, dict] = {}
    for f in activas:
        x = monedas.setdefault(f.moneda or "?", {"moneda": f.moneda or "?", "pagado": 0.0, "por_pagar": 0.0, "frenado": 0.0})
        y = proveedores.setdefault(f.beneficiario_nombre, {"nombre": f.beneficiario_nombre, "pagado": 0.0, "por_pagar": 0.0, "frenado": 0.0})
        clave = "pagado" if f.estado == "pagada" else "frenado" if f.estado == "frenada" else "por_pagar"
        for d in (x, y):
            d[clave] = round(d[clave] + float(f.monto_usd), 2)
    suma = lambda d: d["pagado"] + d["por_pagar"]  # noqa: E731
    top = sorted((d for d in proveedores.values() if suma(d) > 0), key=lambda d: -suma(d))[:6]
    usd = lambda lista: round(sum(float(f.monto_usd) for f in lista), 2)  # noqa: E731
    rutas = rutas_reto.resumen()
    return {
        "hoy": hoy.isoformat(), "vencimientos": semanas, "vencidas": vencidas, "sin_fecha_usd": round(sin_fecha, 2),
        "vencen_7": {"facturas": len(prox7), "usd": usd(prox7)}, "vencen_30": {"facturas": len(prox30), "usd": usd(prox30)},
        "por_pagar": {"facturas": len(abiertas), "usd": usd(abiertas)},
        "monedas": sorted(({**d, "pct": round(100 * suma(d) / total, 1)} for d in monedas.values() if suma(d) > 0),
                          key=lambda d: -suma(d)),
        "proveedores": [{**d, "pct": round(100 * suma(d) / total, 1)} for d in top],
        "top3_pct": round(100 * sum(suma(d) for d in top[:3]) / total, 1),
        "proveedores_total": sum(1 for d in proveedores.values() if suma(d) > 0), "comprometido_usd": round(total, 2),
        "protegido_usd": m["dinero_protegido_usd"],
        "ahorro_rutas_usd": round(rutas["ahorro_historias_usd"] + rutas["general"]["ahorro_usd"], 2),
        "ahorro_historias_usd": rutas["ahorro_historias_usd"], "ahorro_dia_a_dia_usd": rutas["general"]["ahorro_usd"],
    }


@r.get("/rendimiento")
def ver_rendimiento(periodo: str | None = None, ctx: Contexto = Depends(requiere("reportes.ver"))):
    """Indicadores semana contra semana, tendencia del gasto y cascada de lo facturado a lo pagado."""
    return rendimiento.calcular(ctx.bd, (periodo or "")[:7] or None)


@r.get("/costos")
def ver_costos(periodo: str | None = None, ctx: Contexto = Depends(requiere("reportes.ver"))):
    """Costo por factura resuelta y de qué está hecho: lectura, revisión humana, pago e infraestructura."""
    return costos.calcular(ctx.bd, (periodo or "")[:7] or None)


@r.post("/correo/probar")
def probar_correo(ctx: Contexto = Depends(requiere("ver"))):
    """Envía un correo de prueba a quien lo pide (a su propio correo) y dice si salió o por qué no."""
    from ..seguridad.limites import limitar
    limitar(f"correo-prueba:{ctx.usuario.id}", 3, 600)
    ok, mensaje = correo.probar(ctx.usuario.correo)
    auditoria.registrar(ctx.bd, "correo.prueba", ctx.actor, "usuario", str(ctx.usuario.id),
                        f"Prueba de correo a {ctx.usuario.correo}: {'enviado' if ok else 'no enviado'}.", {})
    ctx.bd.commit()
    return {"ok": ok, "mensaje": mensaje, "entrega": correo.entrega(ctx.usuario.correo), "smtp": correo.configurado(),
            "servidor": CONFIG.smtp_host or None}


@r.get("/plataforma")
def plataforma(ctx: Contexto = Depends(requiere("usuarios.ver"))):
    """El resumen de administración: personas y accesos, seguridad, integridad de la auditoría e integraciones."""
    import os

    from ..modelos import Sesion, SolicitudAcceso, Usuario, ahora
    from ..seguridad.permisos import ROLES
    from ..servicios import paypal
    bd = ctx.bd
    hoy = ahora()
    hace7 = hoy - timedelta(days=7)
    us = bd.execute(select(Usuario)).scalars().all()
    por_rol = Counter(u.rol for u in us if u.activo)
    sesiones = bd.execute(select(Sesion).where(Sesion.revocada.is_(False), Sesion.expira_en > hoy)).scalars().all()
    recientes = bd.execute(select(EventoAuditoria).order_by(EventoAuditoria.id.desc()).limit(600)).scalars().all()
    semana = [e for e in recientes if e.ts >= hace7.isoformat()[:19]]
    tipos = Counter(e.tipo for e in semana)
    solicitudes = bd.execute(select(SolicitudAcceso).order_by(SolicitudAcceso.id.desc()).limit(6)).scalars().all()
    pp = paypal.estado()
    return {
        "personas": {"activas": sum(1 for u in us if u.activo), "inactivas": sum(1 for u in us if not u.activo),
                     "bloqueadas": sum(1 for u in us if u.bloqueado_hasta and u.bloqueado_hasta > hoy),
                     "con_mfa": sum(1 for u in us if u.activo and u.mfa_activo),
                     "por_rol": [{"rol": k, "nombre": v["nombre"], "personas": por_rol.get(k, 0)} for k, v in ROLES.items()]},
        "sesiones_activas": len(sesiones),
        "semana": {"inicios_de_sesion": tipos.get("seguridad.inicio_sesion", 0), "bloqueos": tipos.get("seguridad.bloqueo_cuenta", 0),
                   "registros": tipos.get("usuario.registro", 0) + tipos.get("usuario.acceso_solicitado", 0),
                   "cambios_de_rol": tipos.get("usuario.rol_cambiado", 0), "eventos": len(semana)},
        "registros": [{"nombre": s.nombre, "correo": s.correo, "estado": s.estado, "rol": ROLES.get(s.rol or "", {}).get("nombre"),
                       "resuelta_por": s.resuelta_por, "creada_en": vistas.iso(s.creada_en)} for s in solicitudes],
        "auditoria": auditoria.verificar(bd),
        "integraciones": [
            {"nombre": "PayPal", "estado": "ok" if pp["modo"] == "sandbox" else "aviso",
             "detalle": f"Sandbox conectado · recibe {pp['receptor_enmascarado']}" if pp["modo"] == "sandbox" else "Sin credenciales: pagos simulados"},
            {"nombre": "Correo", "estado": "ok" if correo.configurado() else "aviso",
             "detalle": f"SMTP real ({CONFIG.smtp_host}): los avisos y tokens llegan al correo de cada persona" if correo.configurado()
             else "Sin SMTP: los correos quedan en el buzón de la demo (var/correos y la terminal)"},
            {"nombre": "OCR (Tesseract)", "estado": "ok" if ocr.disponible() else "aviso",
             "detalle": f"{ocr.version()} · {', '.join(ocr.idiomas_instalados())}" if ocr.disponible() else "No instalado: fotos y PDF escaneados no se leen sin IA"},
            {"nombre": "IA (Claude)", "estado": "ok" if os.environ.get("ANTHROPIC_API_KEY") else "neutro",
             "detalle": "Clave configurada: lee lo que nada más pudo leer" if os.environ.get("ANTHROPIC_API_KEY")
             else "Opcional y apagada: Kauta lee sin IA (XML, texto, OCR)"},
        ],
        "actividad": [{"ts": e.ts, "tipo": e.tipo, "actor": e.actor, "resumen": e.resumen} for e in recientes[:8]],
    }


@r.get("/auditoria")
def eventos(limite: int = 200, tipo: str | None = None, ctx: Contexto = Depends(requiere("auditoria.ver"))):
    consulta = select(EventoAuditoria).order_by(EventoAuditoria.id.desc()).limit(min(max(limite, 1), 1000))
    if tipo:
        consulta = consulta.where(EventoAuditoria.tipo.startswith(tipo[:30]))
    return {"verificacion": auditoria.verificar(ctx.bd),
            "eventos": [{"id": e.id, "ts": e.ts, "tipo": e.tipo, "actor": e.actor, "entidad": e.entidad,
                         "entidad_id": e.entidad_id, "resumen": e.resumen, "hash": e.hash, "hash_anterior": e.hash_anterior}
                        for e in ctx.bd.execute(consulta).scalars()]}


@r.get("/auditoria/exportar")
def exportar(formato: str = "csv", ctx: Contexto = Depends(requiere("auditoria.exportar"))):
    if formato not in ("csv", "jsonl"):
        raise HTTPException(422, "Formato: csv o jsonl.")
    contenido = auditoria.exportar(ctx.bd, formato)
    auditoria.registrar(ctx.bd, "auditoria.exportada", ctx.actor, "auditoria", None, f"Registro exportado en {formato}.", {})
    ctx.bd.commit()
    return Response(contenido, media_type="text/csv" if formato == "csv" else "application/x-ndjson",
                    headers={"Content-Disposition": f'attachment; filename="kauta-auditoria.{formato}"'})


@r.get("/seguridad")
def seguridad(ctx: Contexto = Depends(requiere("ver"))):
    cadena = auditoria.verificar(ctx.bd)
    libro = wallet.verificar_libro(ctx.bd)
    lector = {"ocr_disponible": ocr.disponible(), "motor": ocr.version(), "idiomas": ocr.idiomas_instalados()}
    a = lambda cat, ctrl, det, est="activo", ref="": {"categoria": cat, "control": ctrl, "detalle": det, "estado": est, "referencia": ref}
    controles = [
        a("Agente de IA", "La IA lee, el código decide", "El modelo solo extrae datos; las 13 reglas son código determinista y probado. La IA no tiene herramientas ni puede mover dinero.", ref="OWASP LLM06 (agencia excesiva)"),
        a("Agente de IA", "Documento = dato, nunca instrucción", "Prompt de sistema con la regla, detector determinista de instrucciones ocultas y regla R13.", ref="OWASP LLM01 (inyección de instrucciones)"),
        a("Agente de IA", "Salida validada", "El JSON del modelo se normaliza y valida (tipos, rangos, fechas, monedas ISO); lo inválido escala.", ref="OWASP LLM05 (manejo de la salida)"),
        a("Agente de IA", "XML fiscal sin IA", "CFDI y facturas DIAN se leen de forma exacta y determinista; duplicados por UUID/CUFE.", ref="Anexo 20 SAT · Anexo técnico DIAN"),
        a("Agente de IA", "Lectura local antes que la IA",
          f"Fotos y PDF escaneados se leen con OCR dentro del servidor ({ocr.version()}, idiomas {ocr.IDIOMAS}): el documento no sale de la empresa. La IA solo se llama si el lector local no alcanza la confianza mínima.",
          est="activo" if ocr.disponible() else "no disponible", ref="Minimización de datos · GDPR art. 5"),
        a("Archivos", "XML seguro", "defusedxml bloquea DTD, entidades y referencias externas (XXE, «billion laughs»).", ref="OWASP XXE · CWE-611"),
        a("Archivos", "ZIP seguro", "Límite de archivos y tamaño, sin rutas peligrosas («zip slip»), sin ZIP cifrados ni «bombas ZIP».", ref="CWE-22 · CWE-409"),
        a("Archivos", "Tipo real del archivo", "Se valida por bytes mágicos; las vistas previas se re-codifican a PNG y nunca se sirve el original.", ref="OWASP ASVS V12"),
        a("Identidad", "Contraseñas Argon2id", "64 MiB, 3 iteraciones, 4 hilos; mínimo 15 caracteres sin reglas de composición ni caducidad; lista de contraseñas comunes; hash señuelo contra enumeración de usuarios; bloqueo tras 5 intentos.", ref="OWASP ASVS V6 · NIST SP 800-63B-4"),
        a("Identidad", "Segundo factor TOTP", "RFC 6238 con anti-repetición; cuenta para el bloqueo por intentos y sirve como token al aprobar pagos. Passkeys en la hoja de ruta.",
          est="activo" if ctx.usuario.mfa_activo else "disponible", ref="NIST SP 800-63B AAL2"),
        a("Identidad", "Recuperación de contraseña", "Enlace de un solo uso (256 bits, solo se guarda su SHA-256) que vence en 60 minutos; misma respuesta exista o no la cuenta; al usarlo se cierran todas las sesiones y se avisa por correo.",
          est="activo" if correo.entrega() == "correo" else "demo", ref="OWASP Forgot Password Cheat Sheet"),
        a("Identidad", "Alta controlada", "Por invitación con código o por solicitud que aprueba administración; nadie elige su rol y la cuenta se activa desde el correo de la persona.", ref="OWASP ASVS V2 · ISO/IEC 27001 A.5.18"),
        a("Sesiones", "Sesión del lado del servidor", f"Token de 256 bits en cookie HttpOnly y SameSite=Strict; en la base solo su hash; inactividad {CONFIG.inactividad_min} min, máximo {CONFIG.duracion_max_h} h.", ref="OWASP ASVS V7"),
        a("Sesiones", "Anti-CSRF", "Token sincronizado en cabecera X-CSRF-Token y verificación de Origin.", ref="OWASP CSRF Cheat Sheet"),
        a("Acceso", "Roles y mínimo privilegio", "Permisos verificados en el servidor en cada petición; denegar por defecto.", ref="OWASP ASVS V8"),
        a("Acceso", "Segregación de funciones", "Quien carga no aprueba; quien pide un cambio de cuenta no lo verifica.", ref="COSO · SOX 404"),
        a("Pagos", "Token por factura", "Cada aprobación exige un código de 6 dígitos que llega al correo de quien aprueba, ligado con HMAC a esa factura, monto, moneda y cuenta; vence en 5 minutos, sirve una vez y admite 5 intentos. La app autenticadora también sirve.", ref="PSD2 · autenticación reforzada (SCA)"),
        a("Pagos", "Doble aprobación (4 ojos)", "Sobre el umbral se necesitan dos personas distintas.", ref="Control de tesorería"),
        a("Pagos", "Firma de la transacción", "Cada aprobación y orden se firma con HMAC-SHA256 sobre monto, cuenta y documento; se verifica antes de pagar.", ref="PSD2 · vinculación dinámica"),
        a("Pagos", "Confirmación de titular", "El nombre de la cuenta destino debe coincidir con el beneficiario registrado.", ref="Confirmation of Payee"),
        a("Pagos", "Cambios de cuenta verificados", "Un cambio de cuenta nunca se aplica solo: requiere verificación por un canal independiente.", ref="Prevención de fraude BEC"),
        a("Pagos", "Idempotencia y unicidad", "Clave única por pago e índice único parcial: la base de datos impide pagar dos veces la misma factura.", ref="Diseño de APIs de pago"),
        a("Datos", "Cifrado en reposo", f"Cuentas bancarias y secretos MFA con AES-256-GCM ligado al registro (AAD). Clave {ID_CLAVE}.", ref="NIST SP 800-38D"),
        a("Datos", "Auditoría a prueba de alteraciones", cadena["mensaje"], est="activo" if cadena["ok"] else "alerta", ref="ISO/IEC 27001 A.8.15"),
        a("Datos", "Libro mayor cuadrado", libro["mensaje"], est="activo" if libro["ok"] else "alerta", ref="Doble partida"),
        a("Red", "Cabeceras de seguridad", "CSP estricta, nosniff, frame-ancestors none, COOP/CORP, Referrer-Policy; HSTS con HTTPS.", ref="OWASP Secure Headers"),
        a("Red", "Límites de peticiones", "Ventana deslizante por IP, cuenta y usuario (inicio de sesión, cargas y simulador).", ref="OWASP API4:2023"),
        a("Operación", "Secretos fuera del código", "Claves por variables de entorno; en producción el servidor no arranca sin ellas (KMS).", est="demo" if CONFIG.demo else "activo", ref="12-Factor · NIST SP 800-57"),
    ]
    return {"modo": CONFIG.modo, "controles": controles, "csp": CSP, "auditoria": cadena, "libro": libro, "lector": lector,
            "versiones": {"python": platform.python_version(), "fastapi": fastapi.__version__, "sqlalchemy": sqlalchemy.__version__,
                          "kauta": CONFIG.version}}


@r.post("/demo/restablecer")
def restablecer(datos: RestablecerIn, ctx: Contexto = Depends(requiere("demo.restablecer"))):
    if not CONFIG.demo:
        raise HTTPException(404)
    semilla.restablecer(ctx.bd, datos.con_set, ctx.actor)
    LIMITADOR.reiniciar()
    return {"ok": True}
