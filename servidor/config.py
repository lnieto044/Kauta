"""
Configuración del servidor. Todo sale de variables de entorno; nada sensible va en el código.

KAUTA_MODO            demo (por defecto) | produccion
KAUTA_BD              URL de la base de datos (SQLite en demo, PostgreSQL en producción). Sin ella se usa la base
                      Postgres que Vercel conecta (Neon: DATABASE_URL_UNPOOLED o DATABASE_URL) y, si no hay, SQLite en var/
KAUTA_CLAVE_DATOS     clave AES-256 en Base64 (32 bytes) para cifrar cuentas bancarias y secretos MFA
KAUTA_CLAVE_FIRMA     clave HMAC en Base64 para firmar aprobaciones y órdenes de pago
KAUTA_CLAVE_AUDITORIA clave HMAC en Base64 para encadenar el registro de auditoría
KAUTA_ORIGEN          origen público permitido (p. ej. https://kauta.ejemplo.com); con él se arman los enlaces de los correos
KAUTA_SMTP_HOST       servidor de correo para enlaces de restablecimiento y activación (sin él, en demo van a var/correos)
KAUTA_SMTP_PUERTO     587 por defecto (STARTTLS); 465 usa TLS directo
KAUTA_SMTP_USUARIO, KAUTA_SMTP_CONTRASENA, KAUTA_SMTP_REMITENTE
KAUTA_ACCESO_DEMO     1 para mostrar en la pantalla de inicio las cuentas de demostración (apagado por defecto)
KAUTA_CODIGOS_EN_PANTALLA  1 (solo demo): el token de las cuentas de ejemplo (@….example) se muestra en pantalla a quien
                      lo pidió, para demos en línea donde nadie ve la terminal. Las cuentas reales siempre lo reciben por correo
KAUTA_PAYPAL_CLIENT_ID, KAUTA_PAYPAL_SECRET   credenciales de una app del sandbox de PayPal (pagos de prueba)
KAUTA_PAYPAL_RECEPTOR correo de la cuenta personal de pruebas (sandbox) que recibe los pagos por PayPal
ANTHROPIC_API_KEY     opcional: activa la lectura con IA de documentos nuevos

Las variables también se pueden poner en un archivo .env en la raíz del proyecto (nunca se sube al repositorio);
lo que ya esté definido en el entorno tiene prioridad.
En modo demo, si faltan las claves se generan al azar y se guardan en var/ con permisos 600.
En producción, si falta una clave el servidor NO arranca (las claves viven en un KMS o gestor de secretos).
"""
from __future__ import annotations

import base64
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]

if not os.environ.get("KAUTA_SIN_DOTENV"):            # las pruebas automáticas lo apagan para no depender del .env local
    try:
        from dotenv import load_dotenv                  # viene con uvicorn[standard]
        load_dotenv(RAIZ / ".env", override=False)
    except ImportError:
        pass

VAR = Path(os.environ.get("KAUTA_VAR", RAIZ / "var"))


def _clave(nombre: str, modo: str) -> bytes:
    valor = os.environ.get(nombre)
    if valor:
        clave = base64.b64decode(valor)
        if len(clave) < 32:
            raise RuntimeError(f"{nombre} debe tener al menos 32 bytes.")
        return clave
    if modo == "produccion":
        raise RuntimeError(f"Falta {nombre}. En producción las claves vienen del gestor de secretos, nunca del disco.")
    VAR.mkdir(parents=True, exist_ok=True)
    ruta = VAR / f"{nombre.lower()}.key"
    if not ruta.exists():
        ruta.write_bytes(base64.b64encode(secrets.token_bytes(32)))
        os.chmod(ruta, 0o600)
    return base64.b64decode(ruta.read_bytes())


@dataclass(frozen=True)
class Config:
    modo: str
    url_bd: str
    clave_datos: bytes = field(repr=False)
    clave_firma: bytes = field(repr=False)
    clave_auditoria: bytes = field(repr=False)
    origen: str
    cookie_segura: bool
    smtp_host: str = ""
    smtp_puerto: int = 587
    smtp_usuario: str = ""
    smtp_contrasena: str = field(default="", repr=False)
    smtp_remitente: str = "Kauta <no-responder@kauta.example>"
    acceso_demo: bool = False
    paypal_client_id: str = ""
    paypal_secret: str = field(default="", repr=False)
    paypal_receptor: str = ""
    origenes_extra: tuple[str, ...] = ()
    codigos_en_pantalla: bool = False
    inactividad_min: int = 30
    duracion_max_h: int = 8
    max_archivo_mb: int = 10
    version: str = "2.1.0"

    @property
    def demo(self) -> bool:
        return self.modo != "produccion"

    @property
    def varias_instancias(self) -> bool:
        """Con PostgreSQL puede haber varias instancias del servidor a la vez (por ejemplo en Vercel)."""
        return not self.url_bd.startswith("sqlite")

    @property
    def nombre_cookie(self) -> str:
        # El prefijo __Host- obliga a Secure, Path=/ y sin Domain: la cookie no se comparte con subdominios
        return "__Host-kauta_sesion" if self.cookie_segura else "kauta_sesion"


def _url_bd() -> str:
    """KAUTA_BD; si no, la base Postgres que conecta Vercel (la conexión directa primero: el candado de la base necesita
    una sesión propia, y el «pooler» de Neon la comparte); si no, SQLite en var/."""
    for nombre in ("KAUTA_BD", "DATABASE_URL_UNPOOLED", "POSTGRES_URL_NON_POOLING", "DATABASE_URL", "POSTGRES_URL"):
        url = os.environ.get(nombre, "").strip()
        if url:
            for prefijo in ("postgres://", "postgresql://"):
                if url.startswith(prefijo):
                    return "postgresql+psycopg://" + url[len(prefijo):]
            return url
    return f"sqlite:///{VAR / 'kauta.db'}"


def _origenes() -> tuple[str, tuple[str, ...]]:
    """El origen público y, en Vercel, también las direcciones propias del despliegue (producción, rama y despliegue)."""
    vercel = [f"https://{d}" for d in (os.environ.get(v, "").strip() for v in
              ("VERCEL_PROJECT_PRODUCTION_URL", "VERCEL_BRANCH_URL", "VERCEL_URL")) if d]
    origen = (os.environ.get("KAUTA_ORIGEN") or (vercel[0] if vercel else "http://localhost:8000")).rstrip("/")
    return origen, tuple(dict.fromkeys(o for o in vercel if o != origen))


def cargar() -> Config:
    modo = os.environ.get("KAUTA_MODO", "demo")
    VAR.mkdir(parents=True, exist_ok=True)
    origen, extra = _origenes()
    return Config(
        modo=modo,
        url_bd=_url_bd(),
        clave_datos=_clave("KAUTA_CLAVE_DATOS", modo),
        clave_firma=_clave("KAUTA_CLAVE_FIRMA", modo),
        clave_auditoria=_clave("KAUTA_CLAVE_AUDITORIA", modo),
        origen=origen.rstrip("/"),
        cookie_segura=origen.startswith("https://"),
        smtp_host=os.environ.get("KAUTA_SMTP_HOST", ""),
        smtp_puerto=int(os.environ.get("KAUTA_SMTP_PUERTO", "587")),
        smtp_usuario=os.environ.get("KAUTA_SMTP_USUARIO", ""),
        smtp_contrasena=os.environ.get("KAUTA_SMTP_CONTRASENA", ""),
        smtp_remitente=os.environ.get("KAUTA_SMTP_REMITENTE", "Kauta <no-responder@kauta.example>"),
        # Las cuentas de prueba con un clic solo existen en demo y solo si se piden expresamente
        acceso_demo=modo != "produccion" and os.environ.get("KAUTA_ACCESO_DEMO") == "1",
        paypal_client_id=os.environ.get("KAUTA_PAYPAL_CLIENT_ID", "").strip(),
        paypal_secret=os.environ.get("KAUTA_PAYPAL_SECRET", "").strip(),
        paypal_receptor=os.environ.get("KAUTA_PAYPAL_RECEPTOR", "").strip(),
        origenes_extra=extra,
        codigos_en_pantalla=modo != "produccion" and os.environ.get("KAUTA_CODIGOS_EN_PANTALLA") == "1",
    )


CONFIG = cargar()
