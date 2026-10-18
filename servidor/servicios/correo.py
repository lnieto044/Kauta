"""
Envío de correos de la cuenta: restablecer la contraseña, activar una cuenta y avisos de seguridad.

  * Con KAUTA_SMTP_HOST configurado, se envía por SMTP con TLS (STARTTLS en 587, TLS directo en 465).
  * Sin SMTP y en modo demo, el correo se guarda en var/correos/*.eml y se escribe en la consola del
    servidor, igual que el «backend de consola» de los frameworks web: sirve para probar sin un buzón real.
  * Sin SMTP y en producción, NO se escribe en ningún lado (un enlace de restablecimiento en disco sería
    una llave suelta): se registra el error para que operación configure el correo.
  * En la demo, los correos a dominios reservados que no existen (.example, .test, .invalid) van siempre al buzón
    de la demo, aunque haya SMTP: así las personas de ejemplo siguen recibiendo sus tokens y nada rebota.
El envío corre después de responder (tarea en segundo plano): la respuesta tarda lo mismo exista o no
la cuenta, y así no se puede averiguar qué correos están registrados.
"""
from __future__ import annotations

import logging
import re
import smtplib
import ssl
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from ..config import CONFIG, VAR

log = logging.getLogger("uvicorn.error")
BUZON = VAR / "correos"


Adjunto = tuple[str, bytes, str]          # nombre del archivo, contenido y tipo MIME
DOMINIOS_DE_EJEMPLO = (".example", ".test", ".invalid", ".localhost", "example.com", "example.org", "example.net")


def configurado() -> bool:
    return bool(CONFIG.smtp_host)


def de_ejemplo(destino: str) -> bool:
    dominio = destino.rpartition("@")[2].lower().strip(" >")
    return any(dominio == d.lstrip(".") or dominio.endswith(d if d.startswith(".") else "." + d) or dominio == d
               for d in DOMINIOS_DE_EJEMPLO)


def entrega(destino: str | None = None) -> str:
    """Cómo se entrega un correo en este servidor: «correo», «buzon» (demo) o «sin_correo»."""
    if configurado() and not (CONFIG.demo and destino and de_ejemplo(destino)):
        return "correo"
    return "buzon" if CONFIG.demo else "sin_correo"


def enlace(ruta: str) -> str:
    return f"{CONFIG.origen}/#/{ruta}"


def _mensaje(destino: str, asunto: str, texto: str, adjuntos: list[Adjunto] | None = None) -> EmailMessage:
    m = EmailMessage()
    m["From"] = CONFIG.smtp_remitente
    m["To"] = destino
    m["Subject"] = asunto
    m["Date"] = formatdate(localtime=False)
    m["Message-ID"] = make_msgid(domain="kauta.local")
    m["Auto-Submitted"] = "auto-generated"
    m.set_content(texto + "\n\n—\nKauta · cuentas por pagar\nEste es un mensaje automático: no responda a este correo.\n")
    for nombre, datos, tipo in adjuntos or []:
        principal, _, sub = (tipo or "application/octet-stream").partition("/")
        m.add_attachment(datos, maintype=principal, subtype=sub or "octet-stream", filename=nombre)
    return m


def _smtp(m: EmailMessage) -> None:
    """Envía por SMTP con TLS. Lanza el error de smtplib si algo falla."""
    contexto = ssl.create_default_context()
    if CONFIG.smtp_puerto == 465:
        servidor = smtplib.SMTP_SSL(CONFIG.smtp_host, CONFIG.smtp_puerto, context=contexto, timeout=15)
    else:
        servidor = smtplib.SMTP(CONFIG.smtp_host, CONFIG.smtp_puerto, timeout=15)
        servidor.starttls(context=contexto)
    with servidor:
        if CONFIG.smtp_usuario:
            servidor.login(CONFIG.smtp_usuario, CONFIG.smtp_contrasena)
        servidor.send_message(m)


def probar(destino: str) -> tuple[bool, str]:
    """Envía un correo de prueba a la persona y dice, en palabras simples, si llegó al servidor de correo o por qué no."""
    if not configurado():
        return False, ("Kauta no tiene servidor de correo (SMTP) configurado: los correos quedan en el buzón de la demo "
                       "(var/correos y la terminal). No depende de localhost ni de XAMPP: configure Gmail en .env con una "
                       "contraseña de aplicación y reinicie Kauta.")
    if CONFIG.demo and de_ejemplo(destino):
        return False, f"{destino} es un correo de ejemplo (no existe): sus mensajes van al buzón de la demo, no a internet."
    m = _mensaje(destino, "Kauta · Correo de prueba",
                 "Si lee este mensaje, Kauta ya envía correos de verdad: tokens, enlaces y el aviso de cada factura.")
    try:
        _smtp(m)
    except smtplib.SMTPAuthenticationError:
        return False, (f"{CONFIG.smtp_host} rechazó el usuario o la contraseña. En Gmail use una contraseña de aplicación "
                       "(16 letras, myaccount.google.com/apppasswords), no la de su cuenta, y que KAUTA_SMTP_USUARIO sea ese mismo Gmail.")
    except (smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected, OSError) as e:
        return False, (f"No se pudo conectar con {CONFIG.smtp_host}:{CONFIG.smtp_puerto} ({type(e).__name__}). Revise la "
                       "conexión a internet, el puerto (587) y que el antivirus o el firewall no bloqueen el envío.")
    except smtplib.SMTPException as e:
        return False, f"El servidor de correo no aceptó el mensaje ({type(e).__name__})."
    log.info("Correo de prueba enviado a %s", destino)
    return True, (f"Correo de prueba enviado a {destino} por {CONFIG.smtp_host}. Si no aparece en un minuto, revise "
                  "Spam o Promociones.")


def enviar(destino: str, asunto: str, texto: str, adjuntos: list[Adjunto] | None = None) -> None:
    """Envía (o deja en el buzón de la demo) un correo, con adjuntos si los hay. Nunca lanza: un fallo de correo no rompe la API."""
    m = _mensaje(destino, asunto, texto, adjuntos)
    try:
        if entrega(destino) == "correo":
            _smtp(m)
            log.info("Correo enviado a %s: %s", destino, asunto)
        elif CONFIG.demo:
            BUZON.mkdir(parents=True, exist_ok=True)
            sello = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
            archivo = BUZON / f"{sello}-{re.sub(r'[^a-z0-9]+', '-', destino.lower())[:60]}.eml"
            archivo.write_bytes(bytes(m))
            marco = "=" * 78
            log.info("\n%s\n  CORREO DE LA DEMO (no hay SMTP configurado) · guardado en %s\n  Para: %s\n  Asunto: %s\n\n%s\n%s",
                     marco, archivo, destino, asunto, texto, marco)
        else:
            log.error("No se envió el correo «%s» a %s: falta KAUTA_SMTP_HOST en producción.", asunto, destino)
    except Exception:  # noqa: BLE001 - el error se registra; la persona recibe la misma respuesta genérica
        log.exception("Falló el envío del correo «%s» a %s", asunto, destino)
