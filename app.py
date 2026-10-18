"""
Kauta · Pantalla del agente de pagos (Reto Blinka · Hackathon 30X).

Ejecutar:   streamlit run app.py
Modo demo:  funciona sin internet ni clave (usa extracciones verificadas del set).
Modo IA:    pegue su clave de API en la barra lateral para leer documentos nuevos.
"""
from __future__ import annotations

import csv
import json
import os
import time
from pathlib import Path

import streamlit as st

from kauta import motor, ui
from kauta.agente import Agente, cargar_json
from kauta.extractor import ExtractorReferencia, ExtraccionNoDisponible

RAIZ = Path(__file__).resolve().parent
DATA = RAIZ / "data"
st.set_page_config(page_title="Kauta · Agente de pagos", page_icon=str(RAIZ / "assets" / "kauta-favicon.png"),
                   layout="wide", initial_sidebar_state="expanded")
st.markdown(ui.CSS, unsafe_allow_html=True)

PAGINAS = {"tablero": "Tablero", "bandeja": "Bandeja de facturas", "reglas": "Reglas de pago",
           "registro": "Registro de auditoría", "validacion": "Validación del reto"}
qp = st.query_params


# ---------------------------------------------------------------------------
# Estado
# ---------------------------------------------------------------------------
def clave_por_defecto() -> str:
    """Clave de API desde la variable de entorno o, en la nube, desde los secretos de Streamlit."""
    clave = os.environ.get("ANTHROPIC_API_KEY", "")
    if not clave:
        try:
            clave = st.secrets.get("ANTHROPIC_API_KEY", "")
        except Exception:  # noqa: BLE001  (no hay archivo de secretos)
            clave = ""
    return clave


def nuevo_agente(modo: str, api_key: str | None = None) -> Agente:
    if modo == "ia":
        from kauta.extractor import ExtractorIA
        extractor = ExtractorIA(api_key=api_key)
    else:
        extractor = ExtractorReferencia()
    return Agente(cargar_json("reglas.json"), cargar_json("beneficiarios.json"), extractor)


if "agente" not in st.session_state:
    st.session_state.agente = nuevo_agente("demo")
    st.session_state.modo = "demo"
    st.session_state.aviso = None
ag: Agente = st.session_state.agente


def archivos_set() -> list[Path]:
    return sorted(p for p in (DATA / "facturas").iterdir() if p.is_file())


def procesar_set(animado: bool = True) -> None:
    archivos = [p for p in archivos_set() if p.name.split("_")[0] not in ag.facturas]
    if not archivos:
        return
    barra = st.progress(0.0, text="Kauta está leyendo las facturas…") if animado else None
    for i, p in enumerate(archivos, 1):
        try:
            f = ag.procesar(p.name, p.read_bytes())
            txt = f"{f['factura_id']} · {f['decision'].beneficiario_nombre} → {ui.ESTADOS[f['estado']][0]}"
        except Exception as ex:  # noqa: BLE001
            txt = f"{p.name}: no se pudo leer ({ex})"
        if barra:
            barra.progress(i / len(archivos), text=txt)
            time.sleep(0.12)
    if barra:
        barra.empty()


def flujo_demo() -> None:
    """Acciones humanas de ejemplo (para ensayar la demo o tomar capturas)."""
    procesar_set(animado=False)
    if ag.facturas.get("F13", {}).get("estado") == "pendiente":
        ag.aprobar("F13", "Mariana Torres", "Verifiqué el monto en la foto: MXN 18.400", {"monto": 18400})
        ag.aprobar("F10", "Mariana Torres", "Proyecto especial aprobado por dirección")
        ag.rechazar("F08", "Mariana Torres", "Proveedor desconocido y con instrucción sospechosa")


if qp.get("auto") == "1" and not ag.facturas:
    procesar_set(animado=False)
if qp.get("flujo") == "1" and "flujo_hecho" not in st.session_state:
    flujo_demo()
    st.session_state.flujo_hecho = True

# ---------------------------------------------------------------------------
# Barra lateral
# ---------------------------------------------------------------------------
with st.sidebar:
    st.image(str(RAIZ / "assets" / "kauta-logo-oscuro.png"), width=210)
    st.caption("Agente de cuentas por pagar · Autónomo, pero cauto.")
    st.markdown("&nbsp;")
    pag_inicial = qp.get("pagina", "tablero")
    claves = list(PAGINAS)
    pagina = st.radio("Navegación", claves, index=claves.index(pag_inicial) if pag_inicial in claves else 0,
                      format_func=lambda k: PAGINAS[k], label_visibility="collapsed")
    st.markdown("---")
    st.caption("EMPRESA (FICTICIA)")
    st.markdown("**Brisamar Labs Inc.**  \nDelaware C-Corp · Miami, FL  \nPeriodo: **octubre 2026**")
    st.session_state.persona = st.text_input("Aprobador(a)", value=st.session_state.get("persona", "Mariana Torres"))
    st.markdown("---")
    modo = st.radio("Modo de lectura", ["demo", "ia"], index=0 if st.session_state.modo == "demo" else 1,
                    format_func=lambda m: "Demo (sin IA, sin internet)" if m == "demo" else "IA en vivo (requiere clave)")
    clave = None
    if modo == "ia":
        clave = st.text_input("Clave de API", type="password", value=clave_por_defecto())
    if modo != st.session_state.modo:
        if modo == "ia" and not clave:
            st.warning("Pegue la clave de API para activar el modo IA.")
        else:
            try:
                st.session_state.agente = nuevo_agente(modo, clave)
                st.session_state.modo = modo
                st.rerun()
            except Exception as ex:  # noqa: BLE001
                st.error(f"No se pudo activar el modo IA: {ex}")
    if st.button("Procesar las 20 facturas", type="primary"):
        procesar_set()
        st.rerun()
    if st.button("Reiniciar demo"):
        st.session_state.agente = nuevo_agente(st.session_state.modo, clave)
        st.session_state.pop("flujo_hecho", None)
        st.rerun()
    st.caption("Datos 100 % ficticios. Ningún pago es real: Kauta decide, registra y explica.")

persona = st.session_state.persona
m = ag.metricas()


def titulo(t: str, sub: str) -> None:
    st.markdown(f'<div class="k-titulo">{t}</div><div class="k-sub">{sub}</div>', unsafe_allow_html=True)


def vacio() -> None:
    st.markdown('<div class="k-card" style="padding:28px;text-align:center"><div style="font-size:18px;font-weight:700;'
                'color:#0B1736">Aún no hay facturas procesadas</div><div style="color:#5B6782;margin-top:6px">Use '
                '«Procesar las 20 facturas» en la barra lateral o cargue un documento en la Bandeja.</div></div>',
                unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Diálogo de revisión humana
# ---------------------------------------------------------------------------
@st.dialog("Revisión humana", width="large")
def revisar(fid: str) -> None:
    f = ag.facturas[fid]
    d = f["decision"]
    st.markdown(ui.banner_decision(f), unsafe_allow_html=True)
    c1, c2 = st.columns([1, 1])
    with c1:
        prev = DATA / "previews" / f"{fid}.png"
        if prev.exists():
            st.image(str(prev), width="stretch")
        else:
            st.markdown(f'<div class="k-doc">{ui.e(f.get("texto", ""))}</div>', unsafe_allow_html=True)
    with c2:
        st.markdown(ui.datos_extraidos(f["extraccion"], float(ag.reglas["confianza_minima"])), unsafe_allow_html=True)
    fallas = d.fallas("escalar")
    if fallas:
        st.markdown("**Motivos para pedir aprobación:** " + "; ".join(f"{r.id} {motor.CATALOGO[r.id]['falla']}" for r in fallas))
    correccion = None
    if any(r.id == "R01" for r in fallas):
        correccion = st.number_input("Monto verificado por la persona (opcional)", min_value=0.0,
                                     value=float(d.monto or 0), step=100.0)
    comentario = st.text_area("Comentario (queda en el registro)", placeholder="¿Por qué aprueba o rechaza?")
    a, b = st.columns(2)
    if a.button("Aprobar y pagar", type="primary", width="stretch"):
        r = ag.aprobar(fid, persona, comentario, {"monto": correccion} if correccion else None)
        st.session_state.aviso = ("ok" if r["ok"] else "bad", r["mensaje"])
        st.rerun()
    if b.button("Rechazar", width="stretch"):
        r = ag.rechazar(fid, persona, comentario)
        st.session_state.aviso = ("ok" if r["ok"] else "bad", r["mensaje"])
        st.rerun()


def mostrar_aviso() -> None:
    if st.session_state.get("aviso"):
        tono, txt = st.session_state.aviso
        st.markdown(f'<div class="k-{"ok" if tono == "ok" else "bad"}" style="margin-bottom:14px">{ui.e(txt)}</div>',
                    unsafe_allow_html=True)
        st.session_state.aviso = None


# ---------------------------------------------------------------------------
# Páginas
# ---------------------------------------------------------------------------
def pagina_tablero() -> None:
    titulo("Tablero de pagos · octubre 2026",
           f"Brisamar Labs Inc. · Kauta decide lo que cumple las reglas y te pide permiso para lo demás. Modo: "
           f"{ag.extractor.nombre}.")
    mostrar_aviso()
    if not ag.facturas:
        vacio()
        return
    k = st.columns(5)
    pct_uso = 100 * m["pagado_usd"] / m["presupuesto_usd"] if m["presupuesto_usd"] else 0
    k[0].markdown(ui.kpi("Facturas procesadas", f'{m["total"]}', f'{m["pagadas"]} pagadas · {m["frenadas"]} frenadas · '
                         f'{m["pendientes"]} pendientes', "dark"), unsafe_allow_html=True)
    k[1].markdown(ui.kpi("Autonomía", f'{m["autonomia_pct"]:.0f} %'.replace(".", ","),
                         "decididas sin intervención humana", "info"), unsafe_allow_html=True)
    k[2].markdown(ui.kpi("Pagos indebidos", f'{m["pagos_fuera_de_reglas"]}', "fuera de reglas: cero, por diseño", "ok"),
                  unsafe_allow_html=True)
    k[3].markdown(ui.kpi("Pagado (USD)", motor.fmt_dinero(round(m["pagado_usd"])).replace("USD ", "").replace(",00", ""),
                         f'Saldo {motor.fmt_dinero(m["saldo_usd"])} de {motor.fmt_dinero(m["presupuesto_usd"])}'.replace(",00", ""), "ok",
                         barra=pct_uso), unsafe_allow_html=True)
    k[4].markdown(ui.kpi("Decisiones explicadas", f'{m["explicadas_pct"]:.0f} %', "cada una con su regla y motivo",
                         "warn"), unsafe_allow_html=True)
    st.markdown("&nbsp;")
    cols = st.columns(3)
    grupos = [("pagada", cols[0]), ("frenada", cols[1]), ("pendiente", cols[2])]
    for estado, col in grupos:
        fs = [f for f in ag.facturas.values() if f["estado"] == estado]
        if estado == "frenada":
            fs += [f for f in ag.facturas.values() if f["estado"] == "rechazada"]
        total = sum(f["decision"].monto_usd or 0 for f in fs if f["estado"] == estado) if estado == "pagada" else None
        with col:
            st.markdown(ui.encabezado_columna(estado, len([x for x in fs if x["estado"] == estado]), total),
                        unsafe_allow_html=True)
            for f in fs:
                st.markdown(ui.tarjeta_factura(f), unsafe_allow_html=True)
                if f["estado"] == "pendiente":
                    if st.button(f"Revisar {f['factura_id']}", key=f"rev_{f['factura_id']}", width="stretch"):
                        revisar(f["factura_id"])


def pagina_bandeja() -> None:
    titulo("Bandeja de facturas", "Todo lo que llegó por PDF, imagen, correo o chat, con la decisión y su porqué.")
    mostrar_aviso()
    with st.expander("Cargar una factura nueva (PDF, imagen, correo .eml o chat .txt)"):
        sub = st.file_uploader("Documento", type=["pdf", "png", "jpg", "jpeg", "eml", "txt"], label_visibility="collapsed")
        if sub is not None and st.button("Leer y decidir", type="primary"):
            try:
                f = ag.procesar(sub.name, sub.getvalue())
                st.session_state.aviso = ("ok", f"{f['factura_id']}: {f['decision'].motivo}")
            except ExtraccionNoDisponible as ex:
                st.session_state.aviso = ("bad", str(ex))
            except Exception as ex:  # noqa: BLE001
                st.session_state.aviso = ("bad", f"No se pudo leer el documento: {ex}")
            st.rerun()
    if not ag.facturas:
        vacio()
        return
    filas = []
    for f in ag.facturas.values():
        d = f["decision"]
        mot = d.motivo.split(":", 1)[-1].strip()
        filas.append(f'<tr><td><b>{f["factura_id"]}</b></td><td>{ui.chip(ui.CANALES.get(f["canal"], f["canal"]))}</td>'
                     f'<td>{ui.e(d.beneficiario_nombre)}</td><td class="num">{ui.monto_txt(d)}</td>'
                     f'<td>{ui.badge(f["estado"])}</td><td class="mot">{ui.e(mot[:170] + ("…" if len(mot) > 170 else ""))}</td></tr>')
    st.markdown('<table class="k-tabla"><tr><th>ID</th><th>Canal</th><th>Beneficiario</th><th style="text-align:right">'
                'Monto</th><th>Decisión</th><th>Por qué</th></tr>' + "".join(filas) + "</table>", unsafe_allow_html=True)
    st.markdown("&nbsp;")
    ids = list(ag.facturas)
    sel = qp.get("factura", ids[0])
    fid = st.selectbox("Ver el detalle de una factura", ids, index=ids.index(sel) if sel in ids else 0,
                       format_func=lambda i: f"{i} · {ag.facturas[i]['decision'].beneficiario_nombre}")
    detalle(fid)


def detalle(fid: str) -> None:
    f = ag.facturas[fid]
    d = f["decision"]
    st.markdown(ui.banner_decision(f), unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1.05, 0.95, 1.25])
    with c1:
        st.markdown("**Documento original**")
        prev = DATA / "previews" / f"{fid}.png"
        if f["canal"] in ("correo", "chat"):
            st.markdown(f'<div class="k-doc">{ui.e(f.get("texto", "")[:2500])}</div>', unsafe_allow_html=True)
        elif prev.exists():
            st.image(str(prev), width="stretch")
        else:
            st.caption(f["archivo"])
    with c2:
        st.markdown("**Lo que leyó la IA** · confianza por campo")
        st.markdown(ui.datos_extraidos(f["extraccion"], float(ag.reglas["confianza_minima"])), unsafe_allow_html=True)
        if f["estado"] == "pendiente" and st.button("Revisar y decidir", type="primary", width="stretch", key=f"rd_{fid}"):
            revisar(fid)
    with c3:
        st.markdown(f"**Lo que decidió el código** · 13 reglas, versión {d.version_reglas}")
        st.markdown(ui.lista_reglas(d), unsafe_allow_html=True)


def pagina_reglas() -> None:
    titulo("Reglas de pago", "La empresa define los límites. Kauta nunca los cruza sin una persona.")
    mostrar_aviso()
    r = ag.reglas
    with st.form("reglas"):
        c = st.columns(3)
        presupuesto = c[0].number_input("Saldo / presupuesto del periodo (USD)", value=float(r["presupuesto_periodo_usd"]), step=500.0, format="%.0f")
        umbral = c[1].number_input("Umbral de aprobación humana (USD)", value=float(r["umbral_aprobacion_usd"]), step=100.0, format="%.0f")
        maximo = c[2].number_input("Límite máximo por pago (USD)", value=float(r["limite_maximo_pago_usd"]), step=500.0, format="%.0f")
        c = st.columns(3)
        lim_b = c[0].number_input("Límite por beneficiario en el periodo (USD)", value=float(r["limite_beneficiario_periodo_usd"]), step=100.0, format="%.0f")
        tol = c[1].number_input("Tolerancia frente a lo acordado (%)", value=float(r["tolerancia_contrato_pct"]), step=0.5, format="%.1f")
        conf = c[2].number_input("Confianza mínima de lectura (0 a 1)", value=float(r["confianza_minima"]), min_value=0.0, max_value=1.0, step=0.05)
        c = st.columns(3)
        monedas = c[0].multiselect("Monedas permitidas", ["USD", "COP", "MXN", "ARS", "EUR"], default=r["monedas_permitidas"])
        cop = c[1].number_input("Tasa COP por 1 USD", value=float(r["tasas_cambio"]["COP"]), step=10.0, format="%.0f")
        mxn = c[2].number_input("Tasa MXN por 1 USD", value=float(r["tasas_cambio"]["MXN"]), step=0.1)
        if st.form_submit_button("Guardar reglas y reevaluar", type="primary"):
            tasas = dict(r["tasas_cambio"], COP=cop, MXN=mxn)
            ag.actualizar_reglas({"presupuesto_periodo_usd": presupuesto, "umbral_aprobacion_usd": umbral,
                                  "limite_maximo_pago_usd": maximo, "limite_beneficiario_periodo_usd": lim_b,
                                  "tolerancia_contrato_pct": tol, "confianza_minima": conf, "monedas_permitidas": monedas,
                                  "tasas_cambio": tasas}, persona)
            cambiadas = ag.reevaluar(persona)
            st.session_state.aviso = ("ok", f"Reglas guardadas (versión {ag.reglas['version']}). Facturas que cambiaron "
                                            f"de estado: {', '.join(cambiadas) if cambiadas else 'ninguna'}.")
            st.rerun()
    st.markdown("#### Catálogo de reglas")
    filas = "".join(f'<tr><td><b>{rid}</b></td><td>{ui.e(v["nombre"])}</td><td>{ui.badge("frenada" if v["efecto"] == "frenar" else "pendiente").replace("Pendiente de aprobación", "Escala a una persona").replace("Frenada", "Frena el pago")}</td></tr>'
                    for rid, v in motor.CATALOGO.items())
    st.markdown('<table class="k-tabla"><tr><th>ID</th><th>Regla</th><th>Si no se cumple</th></tr>' + filas + "</table>",
                unsafe_allow_html=True)
    st.markdown("#### Beneficiarios")
    filas = []
    for b in ag.beneficiarios:
        cto = b.get("contrato") or {}
        acuerdo = (f'{motor.fmt_dinero(cto["monto"], cto["moneda"])} / mes' if cto.get("tipo") == "fijo_mensual"
                   else f'{motor.fmt_dinero(cto["tarifa_hora"], cto["moneda"])} / hora' if cto else "—")
        est = ui.badge("pagada").replace("Pagada", "Permitido") if b["estado"] == "activo" else ui.badge("frenada").replace("Frenada", "Bloqueado")
        filas.append(f'<tr><td><b>{b["id"]}</b></td><td>{ui.e(b["nombre"])}</td><td>{ui.e(b["id_fiscal"])}</td>'
                     f'<td>{b["pais"]}</td><td>{ui.e(b["categoria"])}</td><td class="num">{acuerdo}</td>'
                     f'<td>…{b["cuenta_registrada"]}</td><td>{est}</td></tr>')
    st.markdown('<table class="k-tabla"><tr><th>ID</th><th>Beneficiario</th><th>Identificación</th><th>País</th>'
                '<th>Servicio</th><th style="text-align:right">Acuerdo</th><th>Cuenta</th><th>Estado</th></tr>'
                + "".join(filas) + "</table>", unsafe_allow_html=True)
    with st.expander("Agregar un beneficiario a la lista permitida"):
        with st.form("nuevo_ben"):
            c = st.columns(3)
            nom = c[0].text_input("Nombre")
            idf = c[1].text_input("Identificación fiscal (NIT, RFC, CUIT, EIN)")
            pais = c[2].selectbox("País", ["CO", "MX", "AR", "US"])
            c = st.columns(4)
            tipo = c[0].selectbox("Contrato", ["fijo_mensual", "por_horas"])
            mon = c[1].selectbox("Moneda", ["USD", "COP", "MXN"])
            val = c[2].number_input("Monto mensual o tarifa por hora", min_value=0.0, step=50.0)
            cta = c[3].text_input("Últimos 4 dígitos de la cuenta", max_chars=4)
            if st.form_submit_button("Agregar") and nom and idf and cta:
                nuevo = {"id": f"B{len(ag.beneficiarios) + 1:02d}", "nombre": nom, "id_fiscal": idf, "pais": pais,
                         "tipo_persona": "juridica", "categoria": "Nuevo", "cuenta_registrada": cta, "contactos": [],
                         "estado": "activo", "motivo_bloqueo": None,
                         "contrato": {"tipo": tipo, "moneda": mon, **({"monto": val} if tipo == "fijo_mensual" else {"tarifa_hora": val})}}
                ag.beneficiarios.append(nuevo)
                ag.registro.agregar("cambio_beneficiarios", actor=persona, motivo=f"Se agregó {nom} ({idf}) a la lista permitida.")
                st.session_state.aviso = ("ok", f"{nom} quedó en la lista permitida. Reevalúe para aplicar el cambio.")
                st.rerun()


def pagina_registro() -> None:
    titulo("Registro de auditoría", "Cada decisión queda escrita en lenguaje claro y encadenada con un hash: si alguien la altera, se nota.")
    ok, seq = ag.registro.verificar()
    n = len(ag.registro.entradas)
    if ok:
        ult = ag.registro.entradas[-1]["hash"][:16] if n else "—"
        st.markdown(f'<div class="k-ok">✓ Cadena íntegra · {n} eventos registrados · último hash {ult}…</div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="k-bad">✕ El registro fue alterado a partir del evento {seq}.</div>', unsafe_allow_html=True)
    st.markdown("&nbsp;")
    c = st.columns([1, 1, 3])
    c[0].download_button("Descargar CSV", ag.registro.a_csv(), "kauta_registro.csv", "text/csv", width="stretch")
    c[1].download_button("Descargar JSONL", "\n".join(json.dumps(x, ensure_ascii=False) for x in ag.registro.entradas),
                         "kauta_registro.jsonl", "application/json", width="stretch")
    etiquetas = {"decision": ("Decisión del agente", ui.AZUL), "aprobacion": ("Aprobación humana", ui.MENTA),
                 "aprobacion_bloqueada": ("Aprobación bloqueada", ui.CORAL), "rechazo": ("Rechazo humano", "#9AA4BA"),
                 "reevaluacion": ("Reevaluación", ui.AMBAR), "cambio_reglas": ("Cambio de reglas", ui.NOCHE),
                 "cambio_beneficiarios": ("Cambio de beneficiarios", ui.NOCHE)}
    for x in reversed(ag.registro.entradas):
        nom, col = etiquetas.get(x["evento"], (x["evento"], ui.PIZARRA))
        fac = f'{x.get("factura_id")} · ' if x.get("factura_id") else ""
        st.markdown(f'<div class="k-ev"><div class="seq">#{x["seq"]}</div><div class="meta"><span class="k-badge" '
                    f'style="background:{col}22;color:{col if col != ui.MENTA else "#0B7A5C"}">{nom}</span><br>{x["fecha"][:16].replace("T", " ")}'
                    f'<br>{ui.e(x.get("actor"))}</div><div><div class="txt"><b>{ui.e(fac)}</b>{ui.e(x.get("motivo"))}</div>'
                    f'<div class="hash">hash {x["hash"][:24]}… ← anterior {x["hash_anterior"][:12]}…</div></div></div>',
                    unsafe_allow_html=True)


def pagina_validacion() -> None:
    titulo("Validación frente al reto", "Cómo se ve el éxito según Blinka, medido sobre nuestro set de 20 facturas.")
    if not ag.facturas:
        vacio()
        return
    esp = {r["factura_id"]: r for r in csv.DictReader(open(DATA / "esperado.csv", encoding="utf-8"))}
    filas, aciertos, autonomos_ok = [], 0, 0
    for fid, f in ag.facturas.items():
        if fid not in esp:
            continue
        e_ = esp[fid]
        inicial = (f.get("decision_inicial") or f["decision"]).decision  # primera decisión, sin ayuda humana
        bien = inicial == e_["decision_esperada"]
        aciertos += bien
        autonomos_ok += bien and inicial in ("pagar", "frenar")
        hoy = ""
        if f["estado"] != {"pagar": "pagada", "frenar": "frenada", "escalar": "pendiente"}[inicial]:
            hoy = f'<div style="font-size:12px;color:#5B6782;margin-top:4px">Hoy: {ui.ESTADOS[f["estado"]][0].lower()}</div>'
        filas.append(f'<tr><td><b>{fid}</b></td><td>{ui.e(e_["beneficiario"])}</td><td>{ui.e(e_["tipo_caso"])}</td>'
                     f'<td>{ui.e(e_["decision_esperada"])}</td><td>{ui.badge({"pagar": "pagada", "frenar": "frenada", "escalar": "pendiente"}[inicial])}{hoy}</td>'
                     f'<td style="font-weight:800;color:{"#0B7A5C" if bien else "#C7302F"}">{"✓" if bien else "✕"}</td>'
                     f'<td class="mot">{ui.e(e_["descripcion"])}</td></tr>')
    total = len(filas)
    c = st.columns(3)
    c[0].markdown(f'<div class="k-pilar"><div class="t">Autonomía</div><div class="v" style="color:{ui.AZUL}">'
                  f'{autonomos_ok}/{total}</div><div class="d">Facturas que Kauta decidió correctamente sin intervención humana '
                  f'({100 * autonomos_ok / total:.0f} %). Las demás las escaló porque las reglas lo exigen.</div></div>'.replace(".0f", ""),
                  unsafe_allow_html=True)
    c[1].markdown(f'<div class="k-pilar"><div class="t">Seguridad</div><div class="v" style="color:#0B7A5C">'
                  f'{m["pagos_fuera_de_reglas"]}</div><div class="d">Pagos aprobados fuera de las reglas. Además: 8.000 facturas '
                  f'aleatorias en la prueba de estrés, 0 pagos indebidos.</div></div>', unsafe_allow_html=True)
    c[2].markdown(f'<div class="k-pilar"><div class="t">Explicabilidad</div><div class="v" style="color:#9A5800">'
                  f'{m["explicadas_pct"]:.0f} %</div><div class="d">Decisiones con motivo en lenguaje claro y las 13 reglas '
                  f'evaluadas, en un registro que cualquiera puede leer sin abrir el código.</div></div>', unsafe_allow_html=True)
    st.markdown("&nbsp;")
    st.markdown(f"**Decisiones correctas frente a lo esperado: {aciertos}/{total}** · se compara la primera decisión de Kauta, "
                f"tomada sola con las reglas del set (versión 1).")
    st.markdown('<table class="k-tabla"><tr><th>ID</th><th>Beneficiario</th><th>Caso</th><th>Esperado</th><th>Kauta</th>'
                '<th>✓</th><th>Qué pone a prueba</th></tr>' + "".join(filas) + "</table>", unsafe_allow_html=True)


{"tablero": pagina_tablero, "bandeja": pagina_bandeja, "reglas": pagina_reglas,
 "registro": pagina_registro, "validacion": pagina_validacion}[pagina]()
