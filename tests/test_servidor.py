"""Pruebas del servidor: identidad, token por factura, doble aprobación, wallet, idempotencia, auditoría y simulador."""
import codecs
import email
import email.policy
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
_TMP = tempfile.mkdtemp(prefix="kauta-test-")
os.environ["KAUTA_VAR"] = _TMP
os.environ["KAUTA_BD"] = os.environ.get("KAUTA_PRUEBAS_BD") or f"sqlite:///{_TMP}/prueba.db"   # KAUTA_PRUEBAS_BD: probar con PostgreSQL
os.environ["KAUTA_SIN_DOTENV"] = "1"          # las pruebas no leen el .env local (SMTP, PayPal, acceso demo)

from fastapi.testclient import TestClient  # noqa: E402

from servidor.main import app  # noqa: E402
from servidor.seguridad.limites import LIMITADOR  # noqa: E402

CLAVE = "Kauta-30X-demo-2026"
ORIGEN = {"Origin": "http://localhost:8000"}


@pytest.fixture(scope="module")
def cliente():
    with TestClient(app, base_url="http://localhost:8000") as c:
        yield c
    shutil.rmtree(_TMP, ignore_errors=True)


def entrar(c, correo, clave=CLAVE):
    LIMITADOR.reiniciar()
    c.post("/api/auth/logout", headers=ORIGEN)
    r = c.post("/api/auth/login", json={"correo": correo, "contrasena": clave}, headers=ORIGEN)
    assert r.status_code == 200, r.text
    return {**ORIGEN, "X-CSRF-Token": r.json()["usuario"]["csrf"]}


def ultimo_correo(destino):
    """El último correo que Kauta dejó en el buzón de la demo para esa persona (sin SMTP no sale nada a internet)."""
    for archivo in sorted((Path(_TMP) / "correos").glob("*.eml"), reverse=True):
        m = email.message_from_bytes(archivo.read_bytes(), policy=email.policy.default)
        if m["To"] == destino:
            return m.get_content()
    raise AssertionError(f"No hay correos para {destino}")


def token_de(c, fid, h, correo, correcciones=None):
    r = c.post(f"/api/facturas/{fid}/token", json={"correcciones": correcciones}, headers=h)
    assert r.status_code == 200, r.text
    return re.search(r"^\s+(\d{6})$", ultimo_correo(correo), re.M).group(1)


def aprobar(c, fid, h, correo, comentario):
    return c.post(f"/api/facturas/{fid}/aprobar", json={"comentario": comentario, "token": token_de(c, fid, h, correo)}, headers=h)


def token_pago(c, fid, h, correo):
    r = c.post(f"/api/facturas/{fid}/pago/token", json={}, headers=h)
    assert r.status_code == 200, r.text
    return re.search(r"^\s+(\d{6})$", ultimo_correo(correo), re.M).group(1)


def pagar(c, fid, h, correo, metodo="directo"):
    """Paga una factura aprobada con el token de pago que llega al correo de quien paga."""
    return c.post(f"/api/facturas/{fid}/pagar", json={"token": token_pago(c, fid, h, correo), "metodo": metodo}, headers=h)


def test_set_oficial_20_de_20(cliente):
    h = entrar(cliente, "carlos.rivera@brisamar.example")
    m = cliente.get("/api/resumen", headers=h).json()["metricas"]
    assert m["set_aciertos"] == 20 and m["pagos_fuera_de_reglas"] == 0 and m["trampas_detenidas"] == m["trampas_total"] == 11



def test_rendimiento_cuadra_con_los_datos(cliente):
    h = entrar(cliente, "carlos.rivera@brisamar.example")                  # CEO
    r = cliente.get("/api/rendimiento?periodo=2026-10", headers=h).json()
    resumen = cliente.get("/api/resumen", headers=h).json()
    pagado = resumen["serie"][-1]["acumulado"]
    cascada = {p["clave"]: p["valor"] for p in r["cascada"]}
    assert cascada["pagado"] == pagado                                      # la cascada termina en lo pagado del Resumen
    assert round(cascada["facturado"] + sum(v for k, v in cascada.items() if k not in ("facturado", "pagado")), 2) == pagado
    assert [s["recibidas"] for s in r["semanas"]] == [6, 9, 5]              # semanas del 28 sep, 5 oct y 12 oct
    assert r["semana"] == {"actual": "2026-10-12", "anterior": "2026-10-05"} and len(r["kpis"]) == 4
    assert max(x["pagado"] or 0 for x in r["tendencia"]) == pagado and len(r["tendencia"]) == 31
    h = entrar(cliente, "equipo@kauta.example")                             # el Administrador tiene acceso total
    assert cliente.get("/api/rendimiento", headers=h).status_code == 200


def test_facturas_del_dataset_del_reto_por_canal(cliente):
    """Las 30 facturas hechas con los ítems de facturas.csv y detalle_factura.csv llegan por 5 canales y se deciden con las reglas."""
    import csv
    h = entrar(cliente, "mariana.torres@brisamar.example")
    todas = cliente.get("/api/facturas", headers=h).json()
    reto = sorted((f for f in todas if "F21" <= f["id"] <= "F50"), key=lambda f: f["id"])
    assert len(todas) == 50 and len(reto) == 30
    assert {f["canal"] for f in reto} == {"pdf", "xml", "correo", "chat", "imagen"}
    assert sum(f["estado"] == "pagada" for f in reto) == 6 and sum(f["estado"] == "frenada" for f in reto) == 10
    d = cliente.get("/api/facturas/F23", headers=h).json()                   # CFDI de México: lectura exacta del XML, sin IA
    ext = d["extraccion"]
    assert ext["metodo_lectura"] == "xml_fiscal" and ext["moneda"] == "MXN" and ext["monto"] == 70250.12
    detalle = [x for x in csv.DictReader(open(RAIZ / "data" / "reto" / "detalle_factura.csv", encoding="utf-8-sig"))
               if x["factura_id"] == "SIM-FAC-0013"]
    assert [l["codigo"] for l in ext["lineas"]] == [x["sku_servicio"] for x in detalle]           # los ítems del Excel
    assert [l["total"] for l in ext["lineas"]] == [float(x["importe_bruto_linea"]) for x in detalle]
    d = cliente.get("/api/facturas/F38", headers=h).json()                   # en disputa en el dataset: proveedor bloqueado
    assert d["estado"] == "frenada" and "R05" in d["motivo"] and "disputa" in d["motivo"]
    d = cliente.get("/api/facturas/F26", headers=h).json()                   # base facturada superior a la orden de compra
    assert d["estado"] == "pendiente" and "R08" in d["motivo"] and "SIM-OC-35" in d["motivo"]
    assert d["extraccion"]["orden_compra"] == "SIM-OC-35" and len(d["extraccion"]["lineas"]) == 3


def test_costos_e_impacto(cliente):
    """Rendimiento y costos: costo por factura resuelta y de qué está hecho; el Resumen: impacto en la empresa."""
    h = entrar(cliente, "carlos.rivera@brisamar.example")
    c = cliente.get("/api/costos?periodo=2026-10", headers=h).json()
    i = c["indicadores"]
    assert c["anterior"] == "2026-09" and c["indicadores_anteriores"]["facturas"] == 30
    partes = {x["clave"]: x["valor_usd"] for x in c["componentes"]}
    assert set(partes) == {"lectura", "revision", "pago", "infraestructura"}
    assert round(sum(partes.values()), 2) == i["costo_total_usd"]                      # la barra suma el total
    assert i["costo_por_factura_usd"] == round(i["costo_total_usd"] / i["finales"], 2)
    assert sum(x["facturas"] for x in c["lectura"]) == i["facturas"] == 20
    imp = cliente.get("/api/resumen", headers=h).json()["impacto"]
    assert imp["vencen_7"]["usd"] <= imp["vencen_30"]["usd"] <= imp["por_pagar"]["usd"]   # lo urgente es parte de lo que falta
    assert imp["vencen_7"]["facturas"] <= imp["vencen_30"]["facturas"] <= imp["por_pagar"]["facturas"] == 20
    assert imp["ahorro_historias_usd"] == 6987.18 and imp["protegido_usd"] > 0
    assert round(sum(x["pct"] for x in imp["monedas"])) == 100 and len(imp["proveedores"]) <= 6
    assert cliente.get("/api/costos", headers=entrar(cliente, "andrea.gomez@brisamar.example")).status_code == 200


def test_monto_alto_lo_aprueba_el_ceo_y_lo_paga_finanzas(cliente):
    """Sobre el umbral aprueba el CEO y paga Finanzas: dos personas distintas, y nadie de Finanzas aprueba solo."""
    h = entrar(cliente, "jurado@kauta.example")
    d = cliente.get("/api/simulador/escenarios/supera_umbral?periodo=2026-12", headers=h).json()
    f = cliente.post("/api/simulador/factura", json=d, headers=h).json()
    assert f["estado"] == "pendiente" and f["aprobaciones_requeridas"] == 1
    h1 = entrar(cliente, "mariana.torres@brisamar.example")                 # Finanzas no aprueba montos altos
    r = cliente.post(f"/api/facturas/{f['id']}/token", json={}, headers=h1)
    assert r.status_code == 409 and "CEO" in r.json()["detail"]
    h2 = entrar(cliente, "carlos.rivera@brisamar.example")                  # el CEO aprueba: queda lista para pagar
    r = aprobar(cliente, f["id"], h2, "carlos.rivera@brisamar.example", "Proyecto aprobado por la gerencia.").json()
    assert r["completa"] is True and r["estado"] == "aprobada" and r["pago"] is None
    assert cliente.post(f"/api/facturas/{f['id']}/pago/token", json={}, headers=h2).status_code == 403   # el CEO no paga
    h1 = entrar(cliente, "mariana.torres@brisamar.example")                 # Finanzas paga con su token
    r = pagar(cliente, f["id"], h1, "mariana.torres@brisamar.example")
    assert r.status_code == 200 and r.json()["resultado"] == "exitoso", r.text
    det = cliente.get(f"/api/facturas/{f['id']}", headers=h1).json()
    assert det["estado"] == "pagada" and det["pago_detalle"]["estado"] == "liquidado" and det["motivo"].startswith("Pagada por Mariana")


def test_conciliacion_y_estado_de_paypal(cliente):
    h = entrar(cliente, "carlos.rivera@brisamar.example")
    r = cliente.get("/api/conciliacion?periodo=2026-10", headers=h)
    assert r.status_code == 200 and r.content.startswith(codecs.BOM_UTF8)   # BOM: Excel abre con tildes
    lineas = r.content.decode("utf-8-sig").strip().split("\r\n")
    assert lineas[0].startswith("Factura;Número;Recibida;Canal") and len(lineas) == 1 + 20
    est = cliente.get("/api/paypal/estado", headers=h).json()
    assert est["modo"] == "simulado" and est["client_id"] is False and "secret" in est
    assert not any(isinstance(v, str) and len(v) > 40 for v in est.values() if v != est["api"])   # nunca devuelve secretos
    assert cliente.post("/api/paypal/probar", json={}, headers=h).status_code == 403            # el CEO no configura PayPal
    r = cliente.post("/api/paypal/probar", json={}, headers=entrar(cliente, "equipo@kauta.example")).json()
    assert r["ok"] is False and "KAUTA_PAYPAL_CLIENT_ID" in r["mensaje"]


def test_rutas_de_pago_por_la_api(cliente):
    h = entrar(cliente, "mariana.torres@brisamar.example")                 # Finanzas ve las rutas, pero no las aprueba
    r = cliente.get("/api/rutas-pago", headers=h).json()
    assert r["coinciden_con_el_reto"] == 3 and r["ahorro_historias_usd"] == 6987.18
    assert cliente.post("/api/rutas-pago/H1/aprobar", json={"comentario": "De acuerdo"}, headers=h).status_code == 403
    h = entrar(cliente, "carlos.rivera@brisamar.example")                  # el CEO la aprueba y queda firmada
    assert cliente.post("/api/rutas-pago/H1/aprobar", json={"comentario": "Negociar prórroga con Atlas"}, headers=h).status_code == 200
    h1 = next(x for x in cliente.get("/api/rutas-pago", headers=h).json()["historias"] if x["historia"] == "H1")
    assert h1["aprobacion"]["aprobada_por"].startswith("Carlos Rivera")
    assert cliente.get("/api/rutas-pago", headers=entrar(cliente, "equipo@kauta.example")).status_code == 200  # acceso total

def test_sin_sesion_y_sin_csrf(cliente):
    cliente.post("/api/auth/logout", headers=ORIGEN)
    assert cliente.get("/api/facturas").status_code == 401
    h = entrar(cliente, "mariana.torres@brisamar.example")
    r = cliente.post("/api/facturas/F09/rechazar", json={"comentario": "x"}, headers=ORIGEN)  # sin token CSRF
    assert r.status_code == 403
    r = cliente.post("/api/facturas/F09/rechazar", json={"comentario": "x"}, headers={**h, "Origin": "https://atacante.example"})
    assert r.status_code == 403


def test_contrasena_incorrecta_es_generica(cliente):
    LIMITADOR.reiniciar()
    r1 = cliente.post("/api/auth/login", json={"correo": "mariana.torres@brisamar.example", "contrasena": "mala"}, headers=ORIGEN)
    r2 = cliente.post("/api/auth/login", json={"correo": "nadie@x.example", "contrasena": "mala"}, headers=ORIGEN)
    assert r1.status_code == r2.status_code == 401 and r1.json() == r2.json()


def test_permisos_por_rol(cliente):
    h = entrar(cliente, "carlos.rivera@brisamar.example")  # CEO: aprueba, pero no carga facturas ni fondea la wallet
    h.pop("Content-Type", None)
    r = cliente.post("/api/facturas/cargar", files={"archivo": ("f.xml", b"<a/>", "application/xml")}, headers=h)
    assert r.status_code == 403
    assert cliente.post("/api/wallet/fondear", json={"monto": 10}, headers=h).status_code == 403
    h = entrar(cliente, "mariana.torres@brisamar.example")  # Finanzas: no ve ni gestiona personas
    assert cliente.get("/api/personas", headers=h).status_code == 403
    assert cliente.put("/api/personas/1/rol", json={"rol": "admin"}, headers=h).status_code == 403
    h = entrar(cliente, "equipo@kauta.example")              # Administrador: gestiona accesos y ve todo, pero no mueve dinero
    assert cliente.get("/api/personas", headers=h).status_code == 200
    permisos = set(cliente.get("/api/auth/yo", headers=h).json()["usuario"]["permisos"])
    assert {"usuarios.gestionar", "integraciones.probar", "reportes.ver"} <= permisos
    assert not {"facturas.aprobar", "rutas.aprobar", "reglas.editar", "wallet.fondear", "pagos.reintentar", "pagos.ejecutar"} & permisos
    assert cliente.post("/api/facturas/F09/token", json={}, headers=h).status_code == 403
    assert cliente.post("/api/wallet/fondear", json={"monto": 10}, headers=h).status_code == 403


def test_regla_dura_no_se_salta_aprobando(cliente):
    h = entrar(cliente, "mariana.torres@brisamar.example")
    r = cliente.post("/api/facturas/F10/aprobar", json={"comentario": "Conforme."}, headers=h)
    assert r.status_code == 409 and "R12" in r.json()["detail"]


def test_aprobar_y_pagar_son_dos_pasos(cliente):
    h = entrar(cliente, "jurado@kauta.example")
    d = cliente.get("/api/simulador/escenarios/monto_inflado?periodo=2026-11", headers=h).json()
    f = cliente.post("/api/simulador/factura", json=d, headers=h).json()
    assert f["estado"] == "pendiente"
    assert cliente.post(f"/api/facturas/{f['id']}/token", json={}, headers=h).status_code == 403   # el Administrador no aprueba
    h1 = entrar(cliente, "mariana.torres@brisamar.example")                 # bajo el umbral, Finanzas aprueba
    r = aprobar(cliente, f["id"], h1, "mariana.torres@brisamar.example", "Trabajo extra aprobado.").json()
    assert r["completa"] is True and r["estado"] == "aprobada" and r["pago"] is None
    assert cliente.get(f"/api/facturas/{f['id']}", headers=h1).json()["pago_detalle"] is None      # aún no sale dinero
    assert cliente.post(f"/api/facturas/{f['id']}/token", json={}, headers=h1).status_code == 409  # no se aprueba otra vez
    tablero = cliente.get("/api/tablero/pagos", headers=h1).json()
    assert f["id"] in [x["id"] for x in tablero["por_pagar"]]
    r = cliente.post(f"/api/facturas/{f['id']}/pagar", json={"token": "123456"}, headers=h1)         # sin token pedido, no
    assert r.status_code == 403
    r = pagar(cliente, f["id"], h1, "mariana.torres@brisamar.example").json()
    assert r["resultado"] == "exitoso" and r["pago"]["estado"] == "liquidado"
    r = cliente.post(f"/api/facturas/{f['id']}/pago/token", json={}, headers=h1)
    assert r.status_code == 409 and "ya está pagada" in r.json()["detail"]                    # no se paga dos veces
    tablero = cliente.get("/api/tablero/pagos", headers=h1).json()
    assert f["id"] not in [x["id"] for x in tablero["por_pagar"]]
    assert any(x["factura_id"] == f["id"] and x["resultado"] == "exitoso" for x in tablero["pagos"])


def test_pago_negado_no_mueve_dinero(cliente):
    """Si al pagar ya no se cumple una regla dura (el proveedor quedó bloqueado), Kauta niega el pago sin tocar la wallet."""
    from servidor.db import SesionBD
    from servidor.modelos import Beneficiario, Factura
    h = entrar(cliente, "jurado@kauta.example")
    d = cliente.get("/api/simulador/escenarios/monto_inflado?periodo=2026-12", headers=h).json()
    f = cliente.post("/api/simulador/factura", json=d, headers=h).json()
    h1 = entrar(cliente, "mariana.torres@brisamar.example")
    assert aprobar(cliente, f["id"], h1, "mariana.torres@brisamar.example", "Conforme.").json()["estado"] == "aprobada"
    codigo = token_pago(cliente, f["id"], h1, "mariana.torres@brisamar.example")
    with SesionBD() as bd:                                                  # entre el token y el pago, se bloquea el proveedor
        ben = bd.get(Beneficiario, bd.get(Factura, f["id"]).beneficiario_id)
        ben.estado, ben.motivo_bloqueo = "bloqueado", "Investigación de fraude (prueba)"
        bd.commit()
        ben_id = ben.id
    antes = cliente.get("/api/wallet", headers=h1).json()
    r = cliente.post(f"/api/facturas/{f['id']}/pagar", json={"token": codigo, "metodo": "directo"}, headers=h1)
    assert r.status_code == 200 and r.json()["resultado"] == "negado", r.text
    assert r.json()["pago"]["comision_usd"] == 0 and r.json()["pago"]["estado"] == "negado"
    assert cliente.get(f"/api/facturas/{f['id']}", headers=h1).json()["estado"] == "frenada"
    despues = cliente.get("/api/wallet", headers=h1).json()
    assert despues["cuentas"] == antes["cuentas"] and despues["libro"]["ok"] is True                # ni un dólar se movió
    with SesionBD() as bd:
        ben = bd.get(Beneficiario, ben_id)
        ben.estado, ben.motivo_bloqueo = "activo", None
        bd.commit()


def test_firma_alterada_bloquea_el_pago(cliente):
    from servidor.db import SesionBD
    from servidor.modelos import Factura
    from servidor.servicios import agente, pagos
    h = entrar(cliente, "jurado@kauta.example")
    d = cliente.get("/api/simulador/escenarios/monto_inflado?periodo=2026-11", headers=h).json()
    f = cliente.post("/api/simulador/factura", json=d, headers=h).json()
    h = entrar(cliente, "mariana.torres@brisamar.example")
    assert aprobar(cliente, f["id"], h, "mariana.torres@brisamar.example", "Trabajo extra aprobado.").status_code == 200
    with SesionBD() as bd:  # alguien altera el monto directamente en la base de datos después de aprobar
        fac = bd.get(Factura, f["id"])
        fac.monto_usd = fac.monto_usd + 1
        with pytest.raises(ValueError, match="ya no coincide"):
            pagos.crear_y_ejecutar(bd, fac, agente.reglas_vigentes(bd), "prueba", intento=9)
        bd.rollback()


def test_un_solo_pago_vivo_por_factura(cliente):
    from sqlalchemy.exc import IntegrityError
    from servidor.db import SesionBD
    from servidor.modelos import Pago
    with SesionBD() as bd:
        p = bd.query(Pago).filter(Pago.estado == "liquidado").first()
        copia = Pago(**{c.name: getattr(p, c.name) for c in Pago.__table__.columns if c.name not in ("id", "clave_idempotencia")},
                     id="PAG-COPIA", clave_idempotencia="otra-clave")
        bd.add(copia)
        with pytest.raises(IntegrityError):
            bd.commit()


def test_auditoria_detecta_alteraciones(cliente):
    from servidor.db import SesionBD
    from servidor.modelos import EventoAuditoria
    from servidor.servicios import auditoria
    with SesionBD() as bd:
        assert auditoria.verificar(bd)["ok"]
        ev = bd.get(EventoAuditoria, 3)
        original = ev.resumen
        ev.resumen = original + " (editado)"
        bd.flush()
        r = auditoria.verificar(bd)
        assert not r["ok"] and r["evento_alterado"] == 3
        bd.rollback()


def test_libro_mayor_cuadrado(cliente):
    h = entrar(cliente, "carlos.rivera@brisamar.example")
    w = cliente.get("/api/wallet", headers=h).json()
    assert w["libro"]["ok"] is True


def test_simulador_anio_sin_pagos_indebidos(cliente):
    h = entrar(cliente, "jurado@kauta.example")
    for semilla in (1, 7, 30):
        r = cliente.post("/api/simulador/anio", json={"meses": 12, "trampas_pct": 40, "semilla": semilla}, headers=h).json()
        assert r["pagos_indebidos"] == 0 and r["trampas_pagadas"] == 0 and r["total"] > 100


def test_carga_rechaza_tipos_falsos(cliente):
    h = entrar(cliente, "andrea.gomez@brisamar.example")
    h.pop("Content-Type", None)
    r = cliente.post("/api/facturas/cargar", files={"archivo": ("factura.pdf", b"MZ\x90\x00 ejecutable", "application/pdf")}, headers=h)
    assert r.status_code == 415
    r = cliente.post("/api/facturas/cargar", files={"archivo": ("x.exe", b"MZ", "application/octet-stream")}, headers=h)
    assert r.status_code == 415


def test_xml_malicioso_por_la_api(cliente):
    h = entrar(cliente, "andrea.gomez@brisamar.example")
    datos = (RAIZ / "data" / "sorpresa" / "S03_proveedor-desconocido_FX-001.xml").read_bytes()
    r = cliente.post("/api/facturas/cargar", files={"archivo": ("ataque.xml", datos, "application/xml")}, headers=h)
    assert r.status_code == 200
    f = r.json()
    assert f["estado"] == "pendiente" and f["regla"] == "R01" and "seguridad" in f["motivo"].lower()


def test_politica_de_contrasenas():
    from servidor.seguridad.contrasenas import problemas_politica
    from servidor.servicios.semilla import CONTRASENA_DEMO, USUARIOS_DEMO
    assert problemas_politica("corta-2026") != []                      # menos de 15 caracteres
    assert problemas_politica("password1234567") != []                 # contraseña común
    assert problemas_politica("mariana.torres-2026-ok", "mariana.torres@brisamar.example") != []  # contiene el usuario
    assert problemas_politica("una frase larga sin reglas raras") == []  # sin reglas de composición
    assert all(problemas_politica(CONTRASENA_DEMO, c) == [] for c, *_ in USUARIOS_DEMO)


def test_personas_invitacion_registro_y_roles(cliente):
    h = entrar(cliente, "equipo@kauta.example")                      # administración
    assert cliente.get("/api/personas", headers=h).status_code == 200
    r = cliente.post("/api/personas/invitar", headers=h, json={
        "correo": "prueba.alta@brisamar.example", "nombre": "Prueba Alta", "cargo": "Analista", "rol": "finanzas"})
    assert r.status_code == 200
    codigo = r.json()["codigo"]
    # quien no es administración no invita ni ve la lista
    h2 = entrar(cliente, "andrea.gomez@brisamar.example")
    assert cliente.post("/api/personas/invitar", headers=h2, json={
        "correo": "x@brisamar.example", "nombre": "X Y", "cargo": "", "rol": "admin"}).status_code == 403
    assert cliente.get("/api/personas", headers=h2).status_code == 403
    LIMITADOR.reiniciar()
    cliente.post("/api/auth/logout", headers=ORIGEN)
    # el registro necesita el código correcto y una contraseña que cumpla la política
    assert cliente.post("/api/personas/registro", headers=ORIGEN, json={
        "correo": "prueba.alta@brisamar.example", "codigo": "KAUX-0000-0000",
        "contrasena": "una frase larga y propia"}).status_code == 409
    assert cliente.post("/api/personas/registro", headers=ORIGEN, json={
        "correo": "prueba.alta@brisamar.example", "codigo": codigo, "contrasena": "corta"}).status_code == 422
    r = cliente.post("/api/personas/registro", headers=ORIGEN, json={
        "correo": "prueba.alta@brisamar.example", "codigo": codigo, "contrasena": "una frase larga y propia"})
    assert r.status_code == 200 and r.json()["rol"] == "finanzas"      # el rol lo decide la invitación
    assert cliente.post("/api/personas/registro", headers=ORIGEN, json={      # el código sirve una sola vez
        "correo": "prueba.alta@brisamar.example", "codigo": codigo, "contrasena": "otra frase larga aun"}).status_code == 409
    # la persona nueva entra con su rol y puede cambiar su propia contraseña
    nh = entrar(cliente, "prueba.alta@brisamar.example", "una frase larga y propia")
    assert cliente.post("/api/personas/mi-contrasena", headers=nh, json={
        "actual": "una frase larga y propia", "nueva": "mi nueva frase de acceso"}).status_code == 200
    # administración la desactiva y deja de poder entrar
    h = entrar(cliente, "equipo@kauta.example")
    uid = [u["id"] for u in cliente.get("/api/personas", headers=h).json()["usuarios"]
           if u["correo"] == "prueba.alta@brisamar.example"][0]
    assert cliente.put(f"/api/personas/{uid}/rol", headers=h, json={"rol": "ceo"}).status_code == 200
    assert cliente.put(f"/api/personas/{uid}/rol", headers=h, json={"rol": "auditor"}).status_code == 422  # rol que ya no existe
    assert cliente.put(f"/api/personas/{uid}/activo", headers=h, json={"activo": False}).json()["activo"] is False
    LIMITADOR.reiniciar()
    assert cliente.post("/api/auth/login", headers=ORIGEN, json={
        "correo": "prueba.alta@brisamar.example", "contrasena": "mi nueva frase de acceso"}).status_code == 401
    # siempre debe quedar alguien en administración
    h = entrar(cliente, "equipo@kauta.example")
    admins = {u["correo"]: u["id"] for u in cliente.get("/api/personas", headers=h).json()["usuarios"] if u["rol"] == "admin"}
    assert set(admins) == {"equipo@kauta.example", "jurado@kauta.example"}
    assert cliente.put(f"/api/personas/{admins['jurado@kauta.example']}/rol", headers=h, json={"rol": "ceo"}).status_code == 200
    assert cliente.put(f"/api/personas/{admins['equipo@kauta.example']}/rol", headers=h, json={"rol": "finanzas"}).status_code == 409
    assert cliente.put(f"/api/personas/{admins['jurado@kauta.example']}/rol", headers=h, json={"rol": "admin"}).status_code == 200


def test_lector_local_sin_ia(cliente):
    """El OCR es opcional: si Tesseract no está, Kauta sigue funcionando con los otros lectores."""
    from kauta import ocr
    if not ocr.disponible():
        pytest.skip("Tesseract con el idioma spa no está instalado")
    ruta = RAIZ / "data" / "facturas" / "F09_soporte-nexo_SN-3307.pdf"
    campos = ocr.leer(ruta.name, ruta.read_bytes())
    assert campos and campos["beneficiario"]["id_fiscal"].replace(".", "").replace(" ", "") == "NIT900618442-0"
    assert campos["numero_factura"] == "SN-3307" and campos["monto"] == 2450.0 and campos["moneda"] == "USD"
    assert campos["cuenta_destino"] == "6618" and campos["tipo_documento"] == "factura"
    assert all(campos["confianza"][c] >= 0.8 for c in ("beneficiario", "numero_factura", "moneda", "monto"))
    # la foto borrosa es justo la que no se debe adivinar: sin total legible y con confianza en cero
    borrosa = RAIZ / "data" / "facturas" / "F13_ana-rios_foto-factura.jpg"
    campos = ocr.leer(borrosa.name, borrosa.read_bytes())
    assert campos["monto"] is None and campos["confianza"]["monto"] == 0.0
    assert "sin_total_legible" in campos["alertas"]
    # fotos del dataset del reto (en portugués y en español): proveedor, número, total y cuenta, y nunca el cliente
    empresa = {"nombre": "Brisamar Labs Inc.", "id_fiscal": "EIN 88-4410273"}
    for nombre, prov, num, monto, cuenta in [
            ("F25_bricksave-proveedor-16_SIM-2026-000016.jpg", "SIM Bricksave Proveedor 16", "SIM-2026-000016", 10870.13, "2695"),
            ("F31_braven-proveedor-63_SIM-2026-000063.png", "SIM Braven Proveedor 63", "SIM-2026-000063", 16752120.0, "4434")]:
        ruta = RAIZ / "data" / "reto" / "documentos" / nombre
        c = ocr.leer(nombre, ruta.read_bytes(), cliente=empresa)
        assert (c["beneficiario"]["nombre"], c["numero_factura"], c["monto"], c["cuenta_destino"]) == (prov, num, monto, cuenta)
        assert "4410273" not in (c["beneficiario"]["id_fiscal"] or "")


def test_probar_lectura_no_crea_facturas(cliente):
    """Cualquier rol prueba cómo lee Kauta un chat (y una foto, si hay OCR): pasos, datos y qué haría, sin crear nada."""
    from kauta import ocr
    h = entrar(cliente, "carlos.rivera@brisamar.example")
    h.pop("Content-Type", None)
    antes = len(cliente.get("/api/facturas", headers=h).json())
    chat = (RAIZ / "data" / "facturas" / "F12_andres-rojas_chat.txt").read_bytes()
    r = cliente.post("/api/lectura/probar", files={"archivo": ("mi_chat.txt", chat, "text/plain")}, headers=h)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["canal"] == "chat" and d["en_demo"] is False
    assert [x["paso"] for x in d["pasos"] if x["estado"] == "usado"][:2] == ["canal", "texto"]
    assert d["extraccion"]["monto"] == 4800000.0 and d["extraccion"]["moneda"] == "COP" and d["extraccion"]["cuenta_destino"] == "0093"
    assert d["decision"]["decision"] in ("escalar", "frenar")                   # nunca paga a la cuenta del chat
    if ocr.disponible():
        foto = (RAIZ / "data" / "reto" / "documentos" / "F31_braven-proveedor-63_SIM-2026-000063.png").read_bytes()
        d = cliente.post("/api/lectura/probar", files={"archivo": ("foto.png", foto, "image/png")}, headers=h).json()
        assert any(x["paso"] == "ocr" and x["estado"] == "usado" for x in d["pasos"]) and len(d["palabras"]) > 50
        assert d["extraccion"]["monto"] == 16752120.0 and d["extraccion"]["numero_factura"] == "SIM-2026-000063"
    assert len(cliente.get("/api/facturas", headers=h).json()) == antes                 # no creó ninguna factura
    falso = cliente.post("/api/lectura/probar", files={"archivo": ("x.png", b"%PDF-1.4 no soy png", "image/png")}, headers=h)
    assert falso.status_code == 415


def test_buzon_de_prueba_y_aviso_con_la_factura(cliente):
    """Las 50 facturas del Excel llegan por el buzón; quien revisa recibe el aviso con el documento adjunto."""
    h = entrar(cliente, "mariana.torres@brisamar.example")
    lista = cliente.get("/api/buzon/pruebas", headers=h).json()
    assert len(lista) == 50 and {"pdf", "imagen", "correo", "chat", "xml"} <= {x["canal"] for x in lista}
    assert not any(x["archivo"].lower().endswith(".zip") for x in lista)                # sin canal ZIP
    x = next(x for x in lista if x["regla"] == "R10" and x["canal"] == "pdf")
    f = cliente.post(f"/api/buzon/pruebas/{x['archivo']}/recibir", json={}, headers=h).json()
    assert f["estado"] == "pendiente" and f["canal"] == "pdf"
    for archivo in sorted((Path(_TMP) / "correos").glob("*.eml"), reverse=True):     # supera el umbral: el aviso va al CEO
        m = email.message_from_bytes(archivo.read_bytes(), policy=email.policy.default)
        if m["To"] == "carlos.rivera@brisamar.example" and f["id"] in m["Subject"]:
            assert [a.get_filename() for a in m.iter_attachments()] == [x["archivo"]]
            break
    else:
        raise AssertionError("El CEO no recibió el aviso de la factura")
    otra = next(y for y in cliente.get("/api/buzon/pruebas", headers=h).json() if y["archivo"] == x["archivo"])
    assert otra["factura"] == f["id"]                                                 # ya llegó: no se recibe dos veces sin verlo
    assert cliente.post("/api/buzon/pruebas/no-existe.pdf/recibir", json={}, headers=h).status_code == 404


def test_probar_correo_explica_lo_que_falta(cliente):
    """Sin SMTP, la prueba de correo dice que no depende de localhost ni de XAMPP sino del servidor de correo."""
    h = entrar(cliente, "mariana.torres@brisamar.example")
    r = cliente.post("/api/correo/probar", json={}, headers=h).json()
    assert r["ok"] is False and r["smtp"] is False and "contraseña de aplicación" in r["mensaje"]


# ---------------------------------------------------------------------------- identidad y token por factura
def crear_persona(c, correo, rol, clave="una frase larga para pruebas"):
    """Alta completa por invitación: administración invita y la persona elige su contraseña."""
    h = entrar(c, "equipo@kauta.example")
    codigo = c.post("/api/personas/invitar", headers=h, json={"correo": correo, "nombre": "Persona Prueba", "cargo": "Prueba",
                                                              "rol": rol}).json()["codigo"]
    c.post("/api/auth/logout", headers=ORIGEN)
    r = c.post("/api/personas/registro", headers=ORIGEN, json={"correo": correo, "codigo": codigo, "contrasena": clave})
    assert r.status_code == 200, r.text
    return clave


def test_token_por_factura(cliente):
    h = entrar(cliente, "jurado@kauta.example")
    d = cliente.get("/api/simulador/escenarios/monto_inflado?periodo=2026-11", headers=h).json()
    fid = cliente.post("/api/simulador/factura", json=d, headers=h).json()["id"]
    h = entrar(cliente, "mariana.torres@brisamar.example")
    url = f"/api/facturas/{fid}/aprobar"
    assert cliente.post(url, json={"comentario": "Sin token."}, headers=h).status_code == 403          # sin token no se aprueba
    codigo = token_de(cliente, fid, h, "mariana.torres@brisamar.example")
    texto = ultimo_correo("mariana.torres@brisamar.example")
    assert fid in texto and "cuenta ···" in texto                                   # el correo dice qué se autoriza
    malo = "000000" if codigo != "000000" else "111111"
    assert cliente.post(url, json={"comentario": "Token malo.", "token": malo}, headers=h).status_code == 403
    # el token queda ligado a los datos: si se corrige el monto, el token emitido para el monto original no sirve
    r = cliente.post(url, json={"comentario": "Otro monto.", "token": codigo, "correcciones": {"monto": 1.5}}, headers=h)
    assert r.status_code == 403 and "no coincide" in r.json()["detail"]
    r = cliente.post(url, json={"comentario": "Trabajo extra aprobado.", "token": codigo}, headers=h)
    assert r.status_code == 200, r.text
    assert cliente.post(url, json={"comentario": "Repetir.", "token": codigo}, headers=h).status_code == 409  # ya no está pendiente
    from servidor.db import SesionBD
    from servidor.modelos import EventoAuditoria
    with SesionBD() as bd:                                                          # el código nunca queda en la auditoría
        eventos = bd.query(EventoAuditoria).filter(EventoAuditoria.tipo.like("aprobacion.token%")).all()
        assert eventos and not any(codigo in (e.resumen + str(e.datos)) for e in eventos)


def test_token_vence_y_se_agota(cliente):
    from servidor.db import SesionBD
    from servidor.modelos import TokenFactura
    h = entrar(cliente, "jurado@kauta.example")
    d = cliente.get("/api/simulador/escenarios/monto_inflado?periodo=2026-12", headers=h).json()
    fid = cliente.post("/api/simulador/factura", json=d, headers=h).json()["id"]
    h = entrar(cliente, "carlos.rivera@brisamar.example")
    url = f"/api/facturas/{fid}/aprobar"
    codigo = token_de(cliente, fid, h, "carlos.rivera@brisamar.example")
    malo = "999999" if codigo != "999999" else "888888"
    for _ in range(5):
        assert cliente.post(url, json={"comentario": "x", "token": malo}, headers=h).status_code == 403
    assert cliente.post(url, json={"comentario": "x", "token": codigo}, headers=h).status_code == 403  # 5 fallos anulan el token
    codigo = token_de(cliente, fid, h, "carlos.rivera@brisamar.example")
    with SesionBD() as bd:                                                          # vence a los 5 minutos
        t = bd.query(TokenFactura).filter_by(factura_id=fid, usado_en=None).one()
        t.expira_en = t.creado_en
        bd.commit()
    assert cliente.post(url, json={"comentario": "x", "token": codigo}, headers=h).status_code == 403


def test_olvide_mi_contrasena(cliente):
    correo = "olvido@brisamar.example"
    clave = crear_persona(cliente, correo, "finanzas")
    nh = entrar(cliente, correo, clave)                                             # una sesión abierta antes del cambio
    LIMITADOR.reiniciar()
    r1 = cliente.post("/api/auth/olvide", json={"correo": correo}, headers=ORIGEN)
    r2 = cliente.post("/api/auth/olvide", json={"correo": "nadie@brisamar.example"}, headers=ORIGEN)
    assert r1.status_code == r2.status_code == 200 and r1.json() == r2.json()       # no revela quién tiene cuenta
    token = re.search(r"#/restablecer/([A-Za-z0-9_\-]+)", ultimo_correo(correo)).group(1)
    assert cliente.post("/api/auth/enlace", json={"token": token}, headers=ORIGEN).json()["tipo"] == "restablecer"
    r = cliente.post("/api/auth/restablecer", json={"token": token, "contrasena": "corta"}, headers=ORIGEN)
    assert r.status_code == 422 and "al menos 15 caracteres" in r.json()["detail"]   # mensaje en español
    r = cliente.post("/api/auth/restablecer", json={"token": token, "contrasena": "mi frase nueva y segura"}, headers=ORIGEN)
    assert r.status_code == 200, r.text
    assert cliente.get("/api/facturas", headers=nh).status_code == 401              # se cerraron las sesiones abiertas
    assert cliente.post("/api/auth/restablecer", json={"token": token, "contrasena": "otra frase nueva y segura"},
                        headers=ORIGEN).status_code == 409                          # el enlace sirve una vez
    LIMITADOR.reiniciar()
    assert cliente.post("/api/auth/login", json={"correo": correo, "contrasena": clave}, headers=ORIGEN).status_code == 401
    entrar(cliente, correo, "mi frase nueva y segura")


def test_registro_entra_como_finanzas_sin_aprobacion(cliente):
    """Quien se registra queda con el rol Finanzas (el que paga) sin esperar a nadie; el Administrador puede cambiarlo."""
    correo = "nueva.persona@brisamar.example"
    LIMITADOR.reiniciar()
    cliente.post("/api/auth/logout", headers=ORIGEN)
    r = cliente.post("/api/personas/solicitar", headers=ORIGEN, json={"correo": correo, "nombre": "Nueva Persona",
                                                                       "cargo": "Contadora", "mensaje": "Ingreso el lunes"})
    assert r.status_code == 200 and r.json()["automatico"] is True, r.text
    assert "Nueva Persona" in ultimo_correo("equipo@kauta.example")                 # administración recibe el aviso
    LIMITADOR.reiniciar()
    assert cliente.post("/api/auth/login", json={"correo": correo, "contrasena": "cualquier frase de prueba"},
                        headers=ORIGEN).status_code == 401                          # sin activar el correo no entra
    token = re.search(r"#/activar/([A-Za-z0-9_\-]+)", ultimo_correo(correo)).group(1)   # el enlace llega a SU correo
    assert cliente.post("/api/auth/enlace", json={"token": token}, headers=ORIGEN).json()["tipo"] == "activar"
    assert cliente.post("/api/auth/restablecer", json={"token": token, "contrasena": "mi frase de activacion"},
                        headers=ORIGEN).status_code == 200
    nh = entrar(cliente, correo, "mi frase de activacion")
    yo = cliente.get("/api/auth/yo", headers=nh).json()["usuario"]
    assert yo["rol"] == "finanzas" and "pagos.ejecutar" in yo["permisos"]
    h = entrar(cliente, "equipo@kauta.example")                             # el Administrador le cambia el rol
    assert cliente.put(f"/api/personas/{yo['id']}/rol", json={"rol": "ceo"}, headers=h).status_code == 200
    # un registro repetido con un correo que ya tiene cuenta no crea nada y no lo revela
    LIMITADOR.reiniciar()
    assert cliente.post("/api/personas/solicitar", headers=ORIGEN, json={"correo": correo, "nombre": "Otra Vez"}).status_code == 200
    assert "usted ya tiene una cuenta" in ultimo_correo(correo)


def test_alta_con_aprobacion_si_se_apaga_el_registro(cliente, monkeypatch):
    from servidor.servicios import usuarios
    monkeypatch.setattr(usuarios, "ROL_REGISTRO", "")
    correo = "con.aprobacion@brisamar.example"
    LIMITADOR.reiniciar()
    cliente.post("/api/auth/logout", headers=ORIGEN)
    r = cliente.post("/api/personas/solicitar", headers=ORIGEN, json={"correo": correo, "nombre": "Con Aprobación", "cargo": "Analista"})
    assert r.status_code == 200 and r.json()["automatico"] is False
    h = entrar(cliente, "equipo@kauta.example")
    s = [x for x in cliente.get("/api/personas", headers=h).json()["solicitudes"] if x["correo"] == correo][0]
    assert s["estado"] == "pendiente"
    r = cliente.post(f"/api/personas/solicitudes/{s['id']}/aprobar", json={"rol": "finanzas"}, headers=h)
    assert r.status_code == 200 and r.json()["solicitud"]["estado"] == "aprobada"
    assert re.search(r"#/activar/([A-Za-z0-9_\-]+)", ultimo_correo(correo))


def test_cambio_de_contrasena_cierra_otras_sesiones(cliente):
    correo = "cambio.clave@brisamar.example"
    clave = crear_persona(cliente, correo, "ceo")
    with TestClient(app, base_url="http://localhost:8000") as otro:                 # otro dispositivo
        h_otro = entrar(otro, correo, clave)
        h = entrar(cliente, correo, clave)
        r = cliente.post("/api/personas/mi-contrasena", headers=h, json={"actual": clave, "nueva": "una frase distinta y nueva"})
        assert r.status_code == 200, r.text
        assert cliente.get("/api/facturas", headers=h).status_code == 200            # esta sesión sigue
        assert otro.get("/api/facturas", headers=h_otro).status_code == 401           # la otra se cerró


def test_bloqueo_no_revela_la_cuenta(cliente):
    correo = "bloqueo@brisamar.example"
    clave = crear_persona(cliente, correo, "finanzas")
    LIMITADOR.reiniciar()

    def login(c):
        return cliente.post("/api/auth/login", json={"correo": correo, "contrasena": c}, headers=ORIGEN).status_code

    assert [login("frase equivocada de prueba") for _ in range(5)] == [401] * 5
    assert login("frase equivocada de prueba") == 401                               # bloqueada, pero no se dice a ciegas
    assert login(clave) == 423                                                      # solo quien sabe la contraseña lo ve


def test_codigos_mfa_fallidos_bloquean(cliente):
    import pyotp
    correo = "mfa.bloqueo@brisamar.example"
    clave = crear_persona(cliente, correo, "finanzas")
    h = entrar(cliente, correo, clave)
    secreto = cliente.post("/api/auth/mfa/iniciar", json={}, headers=h).json()["secreto"]
    assert cliente.post("/api/auth/mfa/confirmar", json={"codigo": pyotp.TOTP(secreto).now()}, headers=h).status_code == 200
    LIMITADOR.reiniciar()
    cliente.post("/api/auth/logout", headers=ORIGEN)
    malo = "000000" if pyotp.TOTP(secreto).now() != "000000" else "111111"
    for _ in range(5):
        r = cliente.post("/api/auth/login", json={"correo": correo, "contrasena": clave, "codigo": malo}, headers=ORIGEN)
        assert r.status_code == 401
    r = cliente.post("/api/auth/login", json={"correo": correo, "contrasena": clave, "codigo": pyotp.TOTP(secreto).now()},
                     headers=ORIGEN)
    assert r.status_code == 423


def test_acceso_demo_apagado_por_defecto(cliente):
    assert cliente.get("/api/auth/demo").status_code == 404                         # nadie entra con un clic ni ve la contraseña
    assert cliente.get("/api/auth/config").json()["entrega_correo"] == "buzon"


# ---------------------------------------------------------------------------- pagos por PayPal (sandbox)
class SandboxFalso:
    """Imita la API de Payouts del sandbox de PayPal: token, lote creado y consulta del estado del pago."""

    def __init__(self, estados=("SUCCESS",), rechazo=None):
        self.estados, self.rechazo, self.envios = list(estados), rechazo, []

    def __call__(self, metodo, ruta, cuerpo=None, *, token=None, formulario=None, extra=None):
        from servidor.servicios.paypal import ErrorPayPal
        if ruta == "/v1/oauth2/token":
            return {"access_token": "token-de-prueba", "expires_in": 3600}
        assert token == "token-de-prueba"
        if metodo == "POST":
            if self.rechazo:
                raise ErrorPayPal(self.rechazo)
            self.envios.append(cuerpo)
            return {"batch_header": {"payout_batch_id": f"LOTE{len(self.envios)}", "batch_status": "PENDING"}}
        estado = self.estados.pop(0) if len(self.estados) > 1 else self.estados[0]
        return {"batch_header": {"batch_status": "SUCCESS" if estado == "SUCCESS" else "PROCESSING"},
                "items": [{"payout_item_id": "ITEM1", "transaction_id": "TX-PRUEBA", "transaction_status": estado}]}


@pytest.fixture
def sandbox(monkeypatch):
    from servidor.servicios import paypal

    def poner(**kw):
        falso = SandboxFalso(**kw)
        monkeypatch.setattr(paypal, "_credenciales", lambda: ("id-de-prueba", "secreto-de-prueba", "sb-receptor@personal.example.com"))
        monkeypatch.setattr(paypal, "_pedir", falso)
        monkeypatch.setattr(paypal, "ESPERA_S", 0)
        paypal._token.update(valor=None, vence=0)
        return falso
    return poner


def factura_paypal(c, h, escenario="normal", periodo="2026-11"):
    d = c.get(f"/api/simulador/escenarios/{escenario}?periodo={periodo}", headers=h).json()
    r = c.post("/api/simulador/factura", json={**d, "riel": "PAYPAL"}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def test_paypal_simulado_sin_credenciales(cliente):
    h = entrar(cliente, "jurado@kauta.example")
    paypal = [x for x in cliente.get("/api/rieles", headers=h).json() if x["codigo"] == "PAYPAL"][0]
    assert paypal["modo"] == "simulado" and paypal["receptor"] is None
    f = factura_paypal(cliente, h)
    p = f["pago_detalle"]
    assert f["estado"] == "pagada" and p["riel"] == "PAYPAL" and p["estado"] == "liquidado"
    assert p["moneda_destino"] == "USD" and p["paypal"]["modo"] == "simulado"


def test_paypal_sandbox_paga(cliente, sandbox):
    falso = sandbox()
    h = entrar(cliente, "jurado@kauta.example")
    f = factura_paypal(cliente, h)
    p = f["pago_detalle"]
    assert f["estado"] == "pagada" and p["estado"] == "liquidado" and p["referencia"] == "LOTE1"
    item = falso.envios[0]["items"][0]
    assert item["receiver"] == "sb-receptor@personal.example.com" and item["amount"]["currency"] == "USD"
    assert item["amount"]["value"] == f"{p['monto_usd']:.2f}" and item["sender_item_id"] == p["id"]
    assert falso.envios[0]["sender_batch_header"]["sender_batch_id"].startswith(f"kauta-{p['id']}-")
    assert p["cuenta"] == "PayPal sb-···@personal.example.com"                      # el correo se ve enmascarado
    assert cliente.get("/api/wallet", headers=h).json()["libro"]["ok"] is True


def test_paypal_rechazo_devuelve_el_dinero(cliente, sandbox):
    sandbox(rechazo="PayPal rechazó la operación (INSUFFICIENT_FUNDS).")
    h = entrar(cliente, "jurado@kauta.example")
    f = factura_paypal(cliente, h)
    p = f["pago_detalle"]
    assert f["estado"] == "devuelta" and p["estado"] == "devuelto" and "INSUFFICIENT_FUNDS" in p["motivo_devolucion"]
    assert p["comision_usd"] == 0                                                   # sin envío no hay comisión
    assert cliente.get("/api/wallet", headers=h).json()["libro"]["ok"] is True


def test_paypal_explica_el_rechazo_en_espanol(monkeypatch):
    """PayPal responde en inglés; la pantalla muestra el código y qué hacer, en español."""
    import io
    import json
    import urllib.error

    from servidor.servicios import paypal

    def rechazar(peticion, timeout):
        cuerpo = {"name": "INSUFFICIENT_FUNDS", "message": "Sender does not have sufficient funds.", "debug_id": "x1"}
        raise urllib.error.HTTPError(peticion.full_url, 422, "Unprocessable", {}, io.BytesIO(json.dumps(cuerpo).encode()))
    monkeypatch.setattr(paypal.urllib.request, "urlopen", rechazar)
    with pytest.raises(paypal.ErrorPayPal) as e:
        paypal._pedir("POST", "/v1/payments/payouts", {}, token="t")
    assert "INSUFFICIENT_FUNDS" in str(e.value) and "saldo" in str(e.value) and "Sender" not in str(e.value)


def test_paypal_en_proceso_y_consulta(cliente, sandbox):
    sandbox(estados=("PENDING", "PENDING", "PENDING", "SUCCESS"))
    h = entrar(cliente, "jurado@kauta.example")
    p = factura_paypal(cliente, h, periodo="2026-12")["pago_detalle"]
    assert p["estado"] == "enviado" and p["paypal"]["consultable"] is True
    h_ceo = entrar(cliente, "carlos.rivera@brisamar.example")
    assert cliente.post(f"/api/pagos/{p['id']}/paypal", json={}, headers=h_ceo).status_code == 403   # el CEO no gestiona pagos
    h = entrar(cliente, "mariana.torres@brisamar.example")                 # Finanzas consulta en PayPal
    r = cliente.post(f"/api/pagos/{p['id']}/paypal", json={}, headers=h)
    assert r.status_code == 200 and r.json()["pago"]["estado"] == "liquidado"
    assert cliente.post(f"/api/pagos/{p['id']}/paypal", json={}, headers=h).status_code == 409   # ya no está en proceso


def test_paypal_tras_aprobacion_del_ceo(cliente, sandbox):
    falso = sandbox()
    h = entrar(cliente, "jurado@kauta.example")
    assert cliente.post("/api/demo/restablecer", json={"con_set": False}, headers=h).status_code == 200  # presupuestos llenos
    f = factura_paypal(cliente, h, escenario="supera_umbral", periodo="2026-11")
    assert f["estado"] == "pendiente" and f["riel_pago"] == "PAYPAL" and not falso.envios   # aún no sale dinero
    h2 = entrar(cliente, "carlos.rivera@brisamar.example")
    assert aprobar(cliente, f["id"], h2, "carlos.rivera@brisamar.example", "Aprobado.").json()["estado"] == "aprobada"
    assert not falso.envios                                                 # aprobar no paga
    h1 = entrar(cliente, "mariana.torres@brisamar.example")
    r = pagar(cliente, f["id"], h1, "mariana.torres@brisamar.example").json()
    assert r["resultado"] == "exitoso" and r["pago"]["riel"] == "PAYPAL" and len(falso.envios) == 1


def test_ventana_de_paypal_aprobar_y_rechazar(cliente):
    """Sin credenciales, la ventana de PayPal se simula: rechazar deja el pago negado (sin mover dinero) y aprobar lo paga."""
    h = entrar(cliente, "jurado@kauta.example")
    d = cliente.get("/api/simulador/escenarios/monto_inflado?periodo=2026-11", headers=h).json()
    f = cliente.post("/api/simulador/factura", json=d, headers=h).json()
    h1 = entrar(cliente, "mariana.torres@brisamar.example")
    assert aprobar(cliente, f["id"], h1, "mariana.torres@brisamar.example", "Conforme.").json()["estado"] == "aprobada"
    antes = cliente.get("/api/wallet", headers=h1).json()["cuentas"]
    r = pagar(cliente, f["id"], h1, "mariana.torres@brisamar.example", metodo="ventana").json()
    assert r["resultado"] == "en_proceso" and r["aprobar_en_paypal"].startswith("/#/pagos/paypal-simulado/")
    pid = r["pago"]["id"]
    assert cliente.post(f"/api/facturas/{f['id']}/pago/token", json={}, headers=h1).status_code == 200   # sigue aprobada
    r = cliente.post(f"/api/pagos/{pid}/checkout/simulado", json={"aprobar": False}, headers=h1).json()
    assert r["resultado"] == "negado" and cliente.get("/api/wallet", headers=h1).json()["cuentas"] == antes   # nada se movió
    r = pagar(cliente, f["id"], h1, "mariana.torres@brisamar.example", metodo="ventana").json()     # se puede pagar otra vez
    r = cliente.post(f"/api/pagos/{r['pago']['id']}/checkout/simulado", json={"aprobar": True}, headers=h1).json()
    assert r["resultado"] == "exitoso" and cliente.get(f"/api/facturas/{f['id']}", headers=h1).json()["estado"] == "pagada"
    assert cliente.get("/api/wallet", headers=h1).json()["libro"]["ok"] is True


def test_ventana_de_paypal_real_vuelve_y_cobra(cliente, monkeypatch):
    """Con el sandbox: Kauta crea la orden, PayPal devuelve al navegador con ?token=<orden> y Kauta la cobra."""
    from servidor.servicios import paypal
    monkeypatch.setattr(paypal, "_credenciales", lambda: ("id", "secreto", "sb-receptor@personal.example.com"))
    monkeypatch.setattr(paypal, "crear_orden", lambda pid, monto, moneda, desc, volver, cancelar:
                        {"orden": "ORDEN123", "estado": "PAYER_ACTION_REQUIRED", "aprobar": "https://www.sandbox.paypal.com/checkoutnow?token=ORDEN123"})
    monkeypatch.setattr(paypal, "capturar_orden", lambda orden: {"estado": "COMPLETED", "captura": "CAP9", "pagador": "sb-···@personal.example.com"})
    h = entrar(cliente, "jurado@kauta.example")
    d = cliente.get("/api/simulador/escenarios/monto_inflado?periodo=2026-10", headers=h).json()
    f = cliente.post("/api/simulador/factura", json=d, headers=h).json()
    h1 = entrar(cliente, "mariana.torres@brisamar.example")
    assert aprobar(cliente, f["id"], h1, "mariana.torres@brisamar.example", "Conforme.").json()["estado"] == "aprobada"
    r = pagar(cliente, f["id"], h1, "mariana.torres@brisamar.example", metodo="ventana").json()
    assert r["aprobar_en_paypal"].startswith("https://www.sandbox.paypal.com/") and r["pago"]["referencia"] == "ORDEN123"
    pid = r["pago"]["id"]
    otro = cliente.get(f"/api/paypal/volver?pago={pid}&token=OTRA", follow_redirects=False)       # otra orden: no cobra nada
    assert otro.status_code == 303 and cliente.get(f"/api/pagos/{pid}", headers=h1).json()["estado"] == "reservado"
    cliente.cookies.clear()                                                  # PayPal vuelve sin la cookie de sesión (Strict)
    v = cliente.get(f"/api/paypal/volver?pago={pid}&token=ORDEN123&PayerID=X", follow_redirects=False)
    assert v.status_code == 303 and v.headers["location"] == f"/#/pagos/{pid}"
    h1 = entrar(cliente, "mariana.torres@brisamar.example")
    p = cliente.get(f"/api/pagos/{pid}", headers=h1).json()
    assert p["resultado"] == "exitoso" and cliente.get(f"/api/facturas/{f['id']}", headers=h1).json()["estado"] == "pagada"


def test_paypal_fallido_se_ve_como_fallido(cliente, sandbox):
    """Si PayPal no acepta el envío, el resultado es «fallido», el dinero vuelve y la factura queda devuelta."""
    sandbox(rechazo="PayPal rechazó la operación (INSUFFICIENT_FUNDS). La cuenta Business del sandbox no tiene saldo.")
    h = entrar(cliente, "jurado@kauta.example")
    f = factura_paypal(cliente, h, escenario="supera_umbral", periodo="2026-10")
    h2 = entrar(cliente, "carlos.rivera@brisamar.example")
    assert aprobar(cliente, f["id"], h2, "carlos.rivera@brisamar.example", "Aprobado.").json()["estado"] == "aprobada"
    h1 = entrar(cliente, "mariana.torres@brisamar.example")
    r = pagar(cliente, f["id"], h1, "mariana.torres@brisamar.example").json()
    assert r["resultado"] == "fallido" and "INSUFFICIENT_FUNDS" in r["pago"]["motivo_devolucion"]
    assert cliente.get(f"/api/facturas/{f['id']}", headers=h1).json()["estado"] == "devuelta"
    tablero = cliente.get("/api/tablero/pagos", headers=h1).json()
    assert tablero["resumen"]["fallido"]["pagos"] >= 1 and cliente.get("/api/wallet", headers=h1).json()["libro"]["ok"]
