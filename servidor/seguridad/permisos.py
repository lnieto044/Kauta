"""
Control de acceso por roles (RBAC) con mínimo privilegio y segregación de funciones.

Tres roles con trabajos distintos:
  * Finanzas opera y paga: carga facturas, aprueba los montos bajos, paga con token las facturas aprobadas (PayPal),
    gestiona proveedores y la wallet.
  * CEO decide: aprueba las facturas sobre el umbral (las paga Finanzas, no él), define las reglas de pago, aprueba las
    rutas de pago (negociaciones y cambios de moneda) y revisa rendimiento, costos y auditoría.
  * Administrador gestiona la plataforma: personas, roles y accesos, seguridad, la conexión con PayPal y la auditoría.
    Ve todo en modo consulta, pero NO aprueba, NO paga y NO cambia reglas: quien da los accesos no mueve dinero
    (si pudiera, podría crearse un usuario y pagarse a sí mismo).
Además, quien carga una factura no la aprueba, quien pide un cambio de cuenta no lo verifica y aprobar y pagar son
dos pasos: sobre el umbral aprueba el CEO y paga Finanzas, así ningún pago alto depende de una sola persona.
Los permisos se revisan en el servidor en cada petición (la pantalla solo oculta botones; la seguridad real está aquí).
"""
from __future__ import annotations

ROLES: dict[str, dict] = {
    "finanzas": {"nombre": "Finanzas",
                 "descripcion": "Opera y paga: carga facturas, aprueba los montos bajos, paga con token las facturas "
                                "aprobadas por PayPal, gestiona proveedores y la wallet.",
                 "permisos": {"ver", "reportes.ver", "facturas.cargar", "facturas.aprobar", "cuentas.solicitar",
                              "cuentas.verificar", "wallet.fondear", "pagos.ejecutar", "pagos.reintentar",
                              "integraciones.probar"}},
    "ceo": {"nombre": "CEO",
            "descripcion": "Decide: aprueba las facturas sobre el umbral (las paga Finanzas), define las reglas de pago, "
                           "aprueba las rutas de pago y revisa rendimiento, costos y auditoría.",
            "permisos": {"ver", "reportes.ver", "facturas.aprobar", "facturas.firma_alta", "rutas.aprobar", "reglas.editar",
                         "auditoria.ver", "auditoria.exportar"}},
    "admin": {"nombre": "Administrador",
              "descripcion": "Gestiona la plataforma: personas, roles y accesos, seguridad, la conexión con PayPal y la "
                             "auditoría. Ve todo en modo consulta, pero no aprueba, no paga ni cambia reglas.",
              "permisos": {"ver", "reportes.ver", "usuarios.ver", "usuarios.gestionar", "auditoria.ver", "auditoria.exportar",
                           "integraciones.probar", "demo.restablecer", "simulador.usar"}},
}
IDS_ROLES = tuple(ROLES)


# Cómo se le explica cada permiso a una persona que no programa
ETIQUETAS: dict[str, str] = {
    "ver": "Consultar la información",
    "reportes.ver": "Ver rendimiento, costos y rutas de pago",
    "rutas.aprobar": "Aprobar rutas de pago (negociaciones y moneda)",
    "facturas.cargar": "Cargar facturas",
    "facturas.aprobar": "Aprobar o rechazar con token",
    "facturas.firma_alta": "Aprobar los montos sobre el umbral",
    "pagos.ejecutar": "Pagar las facturas aprobadas (con token)",
    "integraciones.probar": "Probar la conexión con PayPal",
    "reglas.editar": "Editar las reglas de pago",
    "cuentas.verificar": "Verificar cambios de cuenta",
    "cuentas.solicitar": "Solicitar cambios de datos",
    "wallet.fondear": "Fondear la wallet",
    "pagos.reintentar": "Reintentar pagos fallidos y consultar PayPal",
    "simulador.usar": "Cargar datos de prueba",
    "auditoria.ver": "Ver la auditoría",
    "auditoria.exportar": "Exportar la auditoría",
    "usuarios.ver": "Ver las personas",
    "usuarios.gestionar": "Invitar personas y cambiar roles",
    "demo.restablecer": "Restablecer la demo",
}


def etiqueta(permiso: str) -> str:
    return ETIQUETAS.get(permiso, permiso)


def tiene(rol: str, permiso: str) -> bool:
    p = ROLES.get(rol, {}).get("permisos", set())
    return "*" in p or permiso in p or (permiso == "ver" and bool(p))


def permisos_de(rol: str) -> list[str]:
    """Permisos concretos del rol; el acceso total («*») se expande a todo el catálogo."""
    p = ROLES.get(rol, {}).get("permisos", set())
    return sorted(ETIQUETAS) if "*" in p else sorted(p)
