import { useCallback, useState, type ReactNode } from "react";
import { ArrowRight, Banknote, Inbox, KeyRound, MessageCircleQuestion, ScanText, ShieldCheck, TrendingUp, Upload, Users } from "lucide-react";
import { dinero, fecha, ir, numero, PERIODO, puede, useApi, useCambios, type FacturaResumen, type Usuario } from "../api";
import { BarraPresupuesto, Boton, Cargando, cx, EstadoChip, Panel, Vacio } from "../ui";
import { diaMes, BarrasH, CabeceraTablero, CATEGORIA, Cascada, cifra, Columnas, compacto, ESTADO, FranjaKpi, Leyenda, Tendencia, variacion, type DatosRendimiento } from "../graficas";
import { CANALES } from "./Facturas";
import FlujoPago from "./FlujoPago";
import { ChipResultado, PagarModal, type FacturaAPagar } from "./Pagos";

const NOMBRES: Record<string, string> = {
  R01: "Datos legibles, completos y válidos", R02: "Moneda permitida", R03: "No duplicada", R04: "Un cobro por periodo",
  R05: "Beneficiario no bloqueado", R06: "Beneficiario registrado", R07: "Cuenta registrada", R08: "Cuadra con lo acordado",
  R09: "Máximo por pago", R10: "Umbral de aprobación", R11: "Límite por beneficiario", R12: "Saldo del periodo", R13: "Sin instrucciones ocultas",
};
const corta = diaMes;
const usd = (v: number) => `USD ${compacto(v)}`;
const esAlta = (f: FacturaResumen) => (f as any).reglas?.some((r: any) => r.id === "R10" && r.estado === "falla");

/** Cada rol ve su propio resumen: Finanzas su trabajo del día, el CEO sus decisiones e impacto, el Administrador la plataforma. */
export default function Resumen({ usuario }: { usuario: Usuario }) {
  if (usuario.rol === "admin") return <ResumenAdmin usuario={usuario} />;
  if (usuario.rol === "finanzas") return <ResumenFinanzas usuario={usuario} />;
  return <ResumenDireccion usuario={usuario} />;
}

// ======================================================================== Finanzas: el trabajo del día
function ResumenFinanzas({ usuario }: { usuario: Usuario }) {
  const res = useApi<any>("/resumen");
  const tab = useApi<any>("/tablero/pagos");
  const apr = useApi<FacturaResumen[]>("/aprobaciones");
  const rec = useCallback(() => { res.recargar(); tab.recargar(); apr.recargar(); }, [res.recargar, tab.recargar, apr.recargar]);
  useCambios(rec);
  const [pagando, setPagando] = useState<FacturaAPagar | null>(null);
  if (!res.datos || !tab.datos || !apr.datos) return res.error ? <Vacio titulo="No se pudo cargar el resumen" texto={res.error} /> : <Cargando filas={6} />;
  const d = res.datos, t = tab.datos, m = d.metricas, imp = d.impacto, w = d.wallet;
  const mias = apr.datos.filter((f) => !esAlta(f) && !(f as any).cargue_yo);
  const delCeo = apr.datos.filter(esAlta);
  const usado = d.serie.length ? d.serie[d.serie.length - 1].acumulado : 0;
  const cabecera = (
    <CabeceraTablero antetitulo={`Finanzas · ${PERIODO(d.periodo)}`} titulo={`Hola, ${usuario.nombre.split(" ")[0]}`}
      texto="Su trabajo de hoy: responder a Kauta, pagar lo aprobado y revisar cómo terminó cada pago."
      accion={<>
        {mias.length > 0 && <Boton variante="primario" icono={<MessageCircleQuestion className="h-4 w-4" />} onClick={() => ir("pregunta")}>Responder a Kauta ({mias.length})</Boton>}
        {t.por_pagar.length > 0 && <Boton variante={mias.length ? "secundario" : "primario"} icono={<Banknote className="h-4 w-4" />} onClick={() => ir("pagos")}>Pagar ({t.por_pagar.length})</Boton>}
        <Boton icono={<ScanText className="h-4 w-4" />} onClick={() => ir("lector")}>Probar la lectura</Boton>
      </>} />
  );
  if (m.total === 0) return <ResumenVacio usuario={usuario} cabecera={cabecera} />;
  const r = t.resumen;
  return (
    <div className="space-y-8">
      {cabecera}
      <FranjaKpi titulo="Su trabajo" items={[
        { etiqueta: "Le pregunta Kauta", valor: numero(mias.length), tono: mias.length ? "alerta" : undefined,
          detalle: <>{dinero(mias.reduce((a, f) => a + (f.monto_usd ?? 0), 0), "USD", 0)} para aprobar o rechazar{delCeo.length > 0 && <> · {delCeo.length} más superan el umbral y las aprueba el CEO</>}</> },
        { etiqueta: "Listas para pagar", valor: numero(r.por_pagar.pagos), detalle: <>{dinero(r.por_pagar.usd, "USD", 0)} aprobadas: páguelas con su token</> },
        { etiqueta: "Pagos exitosos", valor: numero(r.exitoso.pagos), tono: "bien", detalle: <>{dinero(r.exitoso.usd, "USD", 0)} · fallidos {r.fallido.pagos} · negados {r.negado.pagos} · en proceso {r.en_proceso.pagos}</> },
        { etiqueta: "Vencen en 7 días o ya vencieron", ...cifra(imp.vencen_7.usd), tono: imp.vencen_7.facturas ? "alerta" : undefined,
          detalle: imp.vencen_7.facturas ? `${imp.vencen_7.facturas} facturas sin pagar: decídalas primero` : "Nada vence esta semana" },
      ]} />

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <Panel titulo="Le pregunta Kauta" subtitulo="Facturas que esperan su respuesta (lo que supera el umbral lo aprueba el CEO)" cuerpo="p-0"
          accion={<a href="#/pregunta" className="inline-flex items-center gap-1 text-[13px] font-semibold text-azul hover:underline">Ver todas <ArrowRight className="h-3.5 w-3.5" /></a>}>
          {apr.datos.length === 0 ? <Vacio titulo="Nada pendiente" texto="Kauta no tiene preguntas por ahora." /> : (
            <ul className="divide-y divide-bruma">
              {[...mias, ...apr.datos.filter((f) => !mias.includes(f))].slice(0, 6).map((f) => (
                <li key={f.id}>
                  <a href={`#/facturas/${f.id}`} className="flex items-center gap-3 px-5 py-3 hover:bg-niebla">
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[14px] font-semibold">{f.beneficiario}</span>
                      <span className="block truncate text-xs text-pizarra"><span className="font-mono">{f.id}</span> · {f.motivo.split(":")[0]}</span>
                    </span>
                    <span className="text-right">
                      <span className="block text-[13px] font-semibold num">{dinero(f.monto_usd)}</span>
                      <span className={cx("text-xs font-medium", esAlta(f) ? "text-pizarra" : "text-ambar-t")}>{esAlta(f) ? "La aprueba el CEO" : (f as any).cargue_yo ? "La cargó usted" : "Le toca a usted"}</span>
                    </span>
                  </a>
                </li>
              ))}
            </ul>
          )}
        </Panel>
        <Panel titulo="Listas para pagar" subtitulo="Aprobadas: al pagar, Kauta revisa las reglas otra vez y abre PayPal" cuerpo="p-0"
          accion={<a href="#/pagos" className="inline-flex items-center gap-1 text-[13px] font-semibold text-azul hover:underline">Ir a Pagos <ArrowRight className="h-3.5 w-3.5" /></a>}>
          {t.por_pagar.length === 0 ? <Vacio titulo="Nada por pagar" texto="Cuando se apruebe una factura, aparece aquí." /> : (
            <ul className="divide-y divide-bruma">
              {t.por_pagar.slice(0, 6).map((f: any) => (
                <li key={f.id} className="flex items-center gap-3 px-5 py-3">
                  <a href={`#/facturas/${f.id}`} className="min-w-0 flex-1">
                    <span className="block truncate text-[14px] font-semibold">{f.beneficiario}</span>
                    <span className="block truncate text-xs text-pizarra"><span className="font-mono">{f.id}</span> · aprobada por {f.aprobada_por.join(" y ")}</span>
                  </a>
                  <span className="text-[13px] font-semibold num">{dinero(f.monto_usd)}</span>
                  {puede(usuario, "pagos.ejecutar") && <Boton variante="primario" icono={<Banknote className="h-4 w-4" />} onClick={() => setPagando(f)}>Pagar</Boton>}
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
        <Panel titulo="Últimos pagos" subtitulo="Cómo terminó cada uno: exitoso, en proceso, fallido o negado" cuerpo="p-0">
          {t.pagos.length === 0 ? <Vacio titulo="Aún no hay pagos" /> : (
            <ul className="divide-y divide-bruma">
              {t.pagos.slice(0, 7).map((p: any) => (
                <li key={p.id}>
                  <a href={`#/facturas/${p.factura_id}`} className="flex items-center gap-3 px-5 py-3 hover:bg-niebla">
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[14px] font-semibold">{p.beneficiario}</span>
                      <span className="block truncate text-xs text-pizarra"><span className="font-mono">{p.id}</span> · {p.riel_nombre} · {fecha(p.creado_en)} · {p.automatico ? "Kauta sola" : "con aprobación"}</span>
                    </span>
                    <span className="text-[13px] font-semibold num">{dinero(p.monto_destino, p.moneda_destino)}</span>
                    <ChipResultado resultado={p.resultado} />
                  </a>
                </li>
              ))}
            </ul>
          )}
        </Panel>
        <div className="space-y-6">
          <Panel titulo="Presupuesto y wallet" subtitulo={`Sub-wallet de cuentas por pagar · ${PERIODO(d.periodo)}`}
            accion={<a href="#/wallet" className="inline-flex items-center gap-1 text-[13px] font-semibold text-azul hover:underline">Abrir <ArrowRight className="h-3.5 w-3.5" /></a>}>
            <p className="flex items-baseline justify-between gap-3 text-[14px]"><span className="font-semibold">Pagado en el periodo</span><span className="num text-pizarra">{dinero(usado, "USD", 0)} de {dinero(d.presupuesto, "USD", 0)}</span></p>
            <BarraPresupuesto usado={usado} total={d.presupuesto} className="mt-2" />
            <dl className="mt-4 grid grid-cols-2 gap-3">
              <div><dt className="text-xs text-pizarra">Disponible para pagar</dt><dd className="text-[17px] font-semibold num">{dinero(w.disponible_cxp)}</dd></div>
              <div><dt className="text-xs text-pizarra">Comisiones y cambio</dt><dd className="text-[17px] font-semibold num">{dinero(w.costos)}</dd></div>
            </dl>
          </Panel>
          <Panel titulo="Cómo llegan las facturas" subtitulo="Por canal y en qué estado están"
            accion={<Leyenda series={[{ nombre: "Pagada", color: ESTADO.pagado }, { nombre: "Espera", color: ESTADO.espera }, { nombre: "Frenada", color: ESTADO.frenado }]} />}>
            <BarrasH formato={(v) => `${numero(v)} facturas`} filas={d.canales.map((c: any) => ({
              etiqueta: CANALES[c.canal]?.t ?? c.canal, texto: `${c.total}`,
              partes: [{ nombre: "Pagada", valor: c.pagada, color: ESTADO.pagado }, { nombre: "Espera", valor: c.pendiente, color: ESTADO.espera },
                       { nombre: "Frenada", valor: c.frenada, color: ESTADO.frenado }, { nombre: "Otra", valor: c.otra, color: ESTADO.neutro }],
            }))} />
          </Panel>
        </div>
      </div>
      <FlujoPago usuario={usuario} />
      <PagarModal f={pagando} usuario={usuario} onCerrar={(cambio) => { setPagando(null); if (cambio) rec(); }} />
    </div>
  );
}

// ======================================================================== Administrador: la plataforma
function ResumenAdmin({ usuario }: { usuario: Usuario }) {
  const { datos: d, error, recargar } = useApi<any>("/plataforma");
  useCambios(recargar);
  if (!d) return error ? <Vacio titulo="No se pudo cargar el resumen" texto={error} /> : <Cargando filas={6} />;
  const tonoInt: Record<string, string> = { ok: "bg-menta", aviso: "bg-ambar", neutro: "bg-pizarra/40" };
  return (
    <div className="space-y-8">
      <CabeceraTablero antetitulo="Administración" titulo={`Hola, ${usuario.nombre.split(" ")[0]}`}
        texto="Personas, accesos, seguridad e integraciones. El dinero lo mueven Finanzas y el CEO: usted supervisa en modo consulta."
        accion={<>
          <Boton variante="primario" icono={<Users className="h-4 w-4" />} onClick={() => ir("personas")}>Personas y roles</Boton>
          <Boton icono={<ShieldCheck className="h-4 w-4" />} onClick={() => ir("seguridad")}>Seguridad</Boton>
        </>} />
      <FranjaKpi titulo="La plataforma" items={[
        { etiqueta: "Personas activas", valor: numero(d.personas.activas), detalle: `${d.personas.con_mfa} con app autenticadora · ${d.personas.bloqueadas} bloqueadas ahora` },
        { etiqueta: "Sesiones abiertas", valor: numero(d.sesiones_activas), detalle: `${d.semana.inicios_de_sesion} inicios de sesión en 7 días · ${d.semana.bloqueos} bloqueos por intentos fallidos` },
        { etiqueta: "Registros en 7 días", valor: numero(d.semana.registros), tono: d.semana.registros ? "alerta" : undefined,
          detalle: "Quien se registra entra como Finanzas: revise y cambie el rol si no corresponde" },
        { etiqueta: "Auditoría", valor: d.auditoria.ok ? "Íntegra" : "Alterada", tono: d.auditoria.ok ? "bien" : "alerta",
          detalle: d.auditoria.ok ? `${numero(d.auditoria.total)} eventos encadenados con HMAC-SHA256` : d.auditoria.mensaje },
      ]} />

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <Panel titulo="Integraciones" subtitulo="Qué está conectado en este servidor y qué falta">
          <ul className="space-y-3">
            {d.integraciones.map((x: any) => (
              <li key={x.nombre} className="flex gap-3">
                <span className={cx("mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full", tonoInt[x.estado] ?? tonoInt.neutro)} aria-hidden="true" />
                <span className="min-w-0 text-[13.5px]"><span className="block font-semibold text-noche">{x.nombre}</span><span className="block text-pizarra">{x.detalle}</span></span>
              </li>
            ))}
          </ul>
          <p className="mt-4 text-[12.5px] text-pizarra">PayPal y el correo se configuran en el archivo <span className="font-mono">.env</span> del servidor; «Probar conexión» de PayPal está en «Wallet y conciliación».</p>
        </Panel>
        <Panel titulo="Personas por rol" subtitulo="Cada rol con un trabajo distinto: nadie aprueba, paga y da accesos a la vez"
          accion={<a href="#/personas" className="inline-flex items-center gap-1 text-[13px] font-semibold text-azul hover:underline">Gestionar <ArrowRight className="h-3.5 w-3.5" /></a>}>
          <BarrasH formato={(v) => `${numero(v)} personas`} filas={d.personas.por_rol.map((x: any, i: number) => ({
            etiqueta: x.nombre, texto: `${x.personas}`, partes: [{ nombre: x.nombre, valor: x.personas, color: CATEGORIA[i % CATEGORIA.length] }],
          }))} />
          <ul className="mt-4 space-y-1 text-[12.5px] text-pizarra">
            <li><b className="text-noche">Finanzas</b> carga, aprueba lo bajo y paga con token.</li>
            <li><b className="text-noche">CEO</b> aprueba lo que supera el umbral, las reglas y las rutas de pago.</li>
            <li><b className="text-noche">Administrador</b> da accesos y supervisa; no mueve dinero.</li>
          </ul>
        </Panel>
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <Panel titulo="Registros recientes" subtitulo="Altas sin invitación: entran con el rol Finanzas sin aprobación" cuerpo="p-0">
          {d.registros.length === 0 ? <Vacio titulo="Nadie se ha registrado" /> : (
            <ul className="divide-y divide-bruma">
              {d.registros.map((x: any) => (
                <li key={x.correo + x.creada_en} className="flex items-center gap-3 px-5 py-3">
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[14px] font-semibold">{x.nombre}</span>
                    <span className="block truncate text-xs text-pizarra">{x.correo} · {fecha(x.creada_en)}{x.resuelta_por && ` · ${x.resuelta_por}`}</span>
                  </span>
                  <span className={cx("rounded-full px-2 py-0.5 text-xs font-semibold", x.estado === "aprobada" ? "bg-menta-s text-menta-t" : x.estado === "pendiente" ? "bg-ambar-s text-ambar-t" : "bg-bruma text-pizarra")}>
                    {x.estado === "aprobada" ? x.rol ?? "Aprobada" : x.estado === "pendiente" ? "Pendiente" : "Rechazada"}</span>
                </li>
              ))}
            </ul>
          )}
        </Panel>
        <Panel titulo="Actividad reciente" subtitulo="Los últimos eventos del registro de auditoría" cuerpo="p-0"
          accion={<a href="#/auditoria" className="inline-flex items-center gap-1 text-[13px] font-semibold text-azul hover:underline">Auditoría <ArrowRight className="h-3.5 w-3.5" /></a>}>
          <ul className="divide-y divide-bruma">
            {d.actividad.map((e: any, i: number) => (
              <li key={i} className="px-5 py-3 text-[13px]">
                <p className="flex flex-wrap items-center gap-x-2 text-xs text-pizarra"><span className="font-mono">{e.tipo}</span> · {e.actor} · {fecha(e.ts)}</p>
                <p className="mt-0.5 line-clamp-2 text-noche/85">{e.resumen}</p>
              </li>
            ))}
          </ul>
        </Panel>
      </div>
    </div>
  );
}

// ======================================================================== CEO: decisiones e impacto
function ResumenDireccion({ usuario }: { usuario: Usuario }) {
  const { datos, cargando, error, recargar } = useApi<any>("/resumen");
  const apr = useApi<FacturaResumen[]>("/aprobaciones");
  const reportes = puede(usuario, "reportes.ver");
  const rend = useApi<DatosRendimiento>(reportes ? "/rendimiento" : null);
  const recargarRend = rend.recargar, recargarApr = apr.recargar;
  const rec = useCallback(() => { recargar(); recargarApr(); if (reportes) recargarRend(); }, [recargar, recargarApr, recargarRend, reportes]);
  useCambios(rec);
  if (cargando && !datos) return <Cargando filas={6} />;
  if (error || !datos) return <Vacio titulo="No se pudo cargar el resumen" texto={error ?? ""} />;
  const m = datos.metricas, imp = datos.impacto, r = rend.datos;
  const nombre = usuario.nombre.split(" ")[0];
  const altas = (apr.datos ?? []).filter(esAlta);
  const acciones = <>
    {altas.length > 0 && puede(usuario, "facturas.firma_alta") && <Boton variante="primario" icono={<KeyRound className="h-4 w-4" />} onClick={() => ir("pregunta")}>Aprobar montos altos ({altas.length})</Boton>}
    {reportes && <Boton icono={<TrendingUp className="h-4 w-4" />} onClick={() => ir("rendimiento")}>Rendimiento y costos</Boton>}
  </>;
  const cabecera = <CabeceraTablero antetitulo={`Dirección · ${PERIODO(datos.periodo)}`} titulo={`Hola, ${nombre}`}
    texto="Lo que espera su aprobación, cómo va el presupuesto y lo que más pesa para la empresa." accion={acciones} />;

  if (m.total === 0) return <ResumenVacio usuario={usuario} cabecera={cabecera} />;

  const usado = datos.serie.length ? datos.serie[datos.serie.length - 1].acumulado : 0;
  const maxFalla = Math.max(1, ...Object.values<number>(datos.fallas_por_regla));
  const contraSemana = r?.semana.anterior ? `semana del ${corta(r.semana.anterior)}` : null;
  const en7 = new Date(imp.hoy + "T12:00:00Z");
  en7.setUTCDate(en7.getUTCDate() + 7);

  return (
    <div className="space-y-10">
      {cabecera}

      <Seccion titulo="Espera su decisión" texto="Lo que supera el umbral de aprobación lo aprueba usted; después Finanzas lo paga con su token.">
        <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
          <Panel titulo="Montos altos por aprobar" subtitulo={`${altas.length} facturas · ${dinero(altas.reduce((a, f) => a + (f.monto_usd ?? 0), 0), "USD", 0)}`} cuerpo="p-0"
            accion={<a href="#/pregunta" className="inline-flex items-center gap-1 text-[13px] font-semibold text-azul hover:underline">Kauta pregunta <ArrowRight className="h-3.5 w-3.5" /></a>}>
            {altas.length === 0 ? <Vacio titulo="Nada espera su aprobación" texto="Lo que supere el umbral aparecerá aquí." /> : (
              <ul className="divide-y divide-bruma">
                {altas.slice(0, 6).map((f) => (
                  <li key={f.id}>
                    <a href={`#/facturas/${f.id}`} className="flex items-center gap-3 px-5 py-3 hover:bg-niebla">
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[14px] font-semibold">{f.beneficiario}</span>
                        <span className="block truncate text-xs text-pizarra"><span className="font-mono">{f.id}</span>{f.fecha_vencimiento && ` · vence ${fecha(f.fecha_vencimiento, false)}`} · {f.motivo.split(":")[0]}</span>
                      </span>
                      <span className="text-[14px] font-semibold num">{dinero(f.monto_usd)}</span>
                    </a>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
          <section className="grid grid-cols-2 gap-4" aria-label="Estado del periodo">
            <Indicador etiqueta="Pagado en el periodo" valor={dinero(usado, "USD", 0)} detalle={`de ${dinero(datos.presupuesto, "USD", 0)} presupuestados`}>
              <BarraPresupuesto usado={usado} total={datos.presupuesto} className="mt-3" />
            </Indicador>
            <Indicador etiqueta="Autonomía de Kauta" valor={`${numero(m.autonomia_pct, 0)} %`} detalle="Decidió sola: pagar o frenar" punto="bg-menta" />
            <Indicador etiqueta="Por pagar" valor={numero(m.aprobadas ?? 0)} detalle="Aprobadas, las paga Finanzas" punto="bg-azul" />
            <Indicador etiqueta="Frenadas" valor={numero(m.frenadas)} detalle="Rompen una regla dura" punto="bg-coral" />
          </section>
        </div>
      </Seccion>

      {r && (
        <Seccion titulo={r.semana.actual ? `Esta semana · desde el ${corta(r.semana.actual)}` : "Esta semana"}
          texto={contraSemana ? `Cada cifra con su variación frente a la ${contraSemana}.` : "Aún no hay una semana anterior para comparar."}>
          <FranjaKpi titulo="Indicadores de la semana" items={r.kpis.map((k) => ({
            etiqueta: k.nombre, ...(k.unidad === "usd" ? cifra(k.actual) : { valor: k.actual == null ? "—" : k.unidad === "pct" ? `${numero(k.actual, 0)} %` : numero(k.actual) }),
            cambio: variacion(k.actual, k.anterior, k.unidad, k.mejor), contra: contraSemana, detalle: k.ayuda,
          }))} />
        </Seccion>
      )}

      <Seccion titulo="Impacto en la empresa" texto="Lo que hay que pagar y cuándo, lo que está en riesgo, dónde se concentra el dinero y cuánto se protege y se ahorra.">
        <FranjaKpi titulo="Impacto" items={[
          { etiqueta: "Por pagar", ...cifra(imp.por_pagar.usd), detalle: `${imp.por_pagar.facturas} facturas esperan una aprobación, el pago o un reintento` },
          { etiqueta: "Vencen en 7 días o ya vencieron", ...cifra(imp.vencen_7.usd), tono: imp.vencen_7.facturas ? "alerta" : undefined,
            detalle: imp.vencen_7.facturas ? `${imp.vencen_7.facturas} facturas sin pagar hasta el ${corta(en7.toISOString().slice(0, 10))}: decidirlas primero` : "Nada vence esta semana" },
          { etiqueta: "Dinero protegido", ...cifra(imp.protegido_usd), detalle: "Frenado por las reglas: disputas, duplicados, máximos y saldo" },
          { etiqueta: "Ahorro con rutas de pago", ...cifra(imp.ahorro_rutas_usd), tono: "bien",
            detalle: `${dinero(imp.ahorro_historias_usd, "USD", 0)} en las 3 historias del reto y ${dinero(imp.ahorro_dia_a_dia_usd, "USD", 0)} en el día a día` },
        ]} />
        <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
          <Panel titulo="Calendario de vencimientos" subtitulo="Lo que falta pagar, por la semana en que vence (equivalente en USD)"
            accion={<Leyenda series={[{ nombre: "Espera aprobación o pago", color: ESTADO.espera }, { nombre: "Pago fallido", color: ESTADO.frenado }]} />}>
            <Columnas formato={usd} columnas={[
              { etiqueta: "Vencidas", subetiqueta: `${imp.vencidas.facturas} fact.`, destacada: imp.vencidas.facturas > 0,
                partes: [{ nombre: "Espera aprobación o pago", valor: imp.vencidas.espera, color: ESTADO.espera }, { nombre: "Pago fallido", valor: imp.vencidas.devuelta, color: ESTADO.frenado }] },
              ...imp.vencimientos.map((s: any, i: number) => ({
                etiqueta: i === 0 ? "Esta semana" : corta(s.desde), subetiqueta: `${s.facturas} fact.`, destacada: i === 0,
                partes: [{ nombre: "Espera aprobación o pago", valor: s.espera, color: ESTADO.espera }, { nombre: "Pago fallido", valor: s.devuelta, color: ESTADO.frenado }],
              })),
            ]} />
            {imp.sin_fecha_usd > 0 && <p className="mt-3 text-[12.5px] text-pizarra">Además, {dinero(imp.sin_fecha_usd, "USD", 0)} sin fecha de vencimiento en el documento.</p>}
          </Panel>
          <Panel titulo="Exposición por moneda" subtitulo="Pagado y por pagar en cada moneda, en USD con las tasas de la política"
            accion={<Leyenda series={[{ nombre: "Pagado", color: ESTADO.pagado }, { nombre: "Por pagar", color: ESTADO.espera }]} />}>
            <BarrasH filas={imp.monedas.map((x: any) => ({
              etiqueta: x.moneda, detalle: `${numero(x.pct, 0)} %`, texto: dinero(x.pagado + x.por_pagar, "USD", 0),
              partes: [{ nombre: "Pagado", valor: x.pagado, color: ESTADO.pagado }, { nombre: "Por pagar", valor: x.por_pagar, color: ESTADO.espera }],
            }))} />
            <p className="mt-4 text-[12.5px] text-pizarra">Lo frenado no cuenta: no sale de la caja. Un cambio fuerte en una moneda con mucho por pagar mueve el costo final.</p>
          </Panel>
        </div>
        <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
          <Panel titulo="Concentración por proveedor" subtitulo={`Los 6 con más dinero comprometido de ${imp.proveedores_total} proveedores`}
            accion={<Leyenda series={[{ nombre: "Pagado", color: ESTADO.pagado }, { nombre: "Por pagar", color: ESTADO.espera }]} />}>
            <BarrasH filas={imp.proveedores.map((x: any) => ({
              etiqueta: x.nombre, detalle: `${numero(x.pct, 1)} %`, texto: dinero(x.pagado + x.por_pagar, "USD", 0),
              partes: [{ nombre: "Pagado", valor: x.pagado, color: ESTADO.pagado }, { nombre: "Por pagar", valor: x.por_pagar, color: ESTADO.espera }],
            }))} />
            <p className="mt-4 text-[12.5px] text-pizarra">Los 3 primeros concentran el {numero(imp.top3_pct, 1)} % de lo comprometido ({dinero(imp.comprometido_usd, "USD", 0)}). Si uno de ellos cambia de cuenta, se verifica por otro canal.</p>
          </Panel>
          <Panel titulo="Dónde fallan las reglas" subtitulo="Veces que cada regla frenó o escaló una factura: dónde está el riesgo"
            accion={<Leyenda series={[{ nombre: "Frena", color: ESTADO.frenado }, { nombre: "Escala", color: ESTADO.espera }]} />}>
            <ul className="space-y-2.5">
              {Object.entries<number>(datos.fallas_por_regla).sort((a, b) => b[1] - a[1]).slice(0, 8).map(([rid, n]) => (
                <li key={rid} className="grid grid-cols-[2.6rem_minmax(0,1fr)_2rem] items-center gap-3 text-[13px]">
                  <span className="font-mono text-pizarra">{rid}</span>
                  <span>
                    <span className="block truncate font-medium">{NOMBRES[rid]}</span>
                    <span className="mt-1 block h-1.5 rounded-full bg-niebla"><span className="block h-full rounded-full" style={{ width: `${(n / maxFalla) * 100}%`, background: ["R03", "R04", "R05", "R09", "R12"].includes(rid) ? ESTADO.frenado : ESTADO.espera }} /></span>
                  </span>
                  <span className="text-right font-semibold num">{n}</span>
                </li>
              ))}
            </ul>
          </Panel>
        </div>
      </Seccion>

      {r && (
        <Seccion titulo={`Cómo va ${PERIODO(datos.periodo)}`} texto="El gasto día a día frente al presupuesto y a dónde fue lo facturado.">
          <Panel titulo="Tendencia del gasto" subtitulo={`Pagado acumulado frente al ritmo del presupuesto de ${dinero(r.presupuesto, "USD", 0)} en ${PERIODO(r.periodo)}`}>
            <Tendencia puntos={r.tendencia} presupuesto={r.presupuesto} />
          </Panel>
          <Panel titulo="De lo facturado a lo pagado" subtitulo="Cascada del periodo: cada barra resta lo que no salió de la wallet y por qué">
            <Cascada pasos={r.cascada} />
          </Panel>
        </Seccion>
      )}

      <section className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {datos.criterios.map((c: any) => (
          <div key={c.criterio} className="rounded-lg border border-bruma bg-white p-5 shadow-[0_1px_2px_rgba(11,23,54,0.05)]">
            <p className="text-[12px] font-semibold uppercase tracking-wider text-pizarra">{c.criterio}</p>
            <p className={cx("mt-1.5 text-[22px] font-semibold tracking-tight num", c.criterio === "Seguridad" ? "text-menta-t" : "text-noche")}>{c.valor}</p>
            <p className="mt-1.5 text-[13px] leading-relaxed text-pizarra">{c.detalle}</p>
          </div>
        ))}
      </section>

      <Panel titulo="Últimas decisiones" subtitulo="Cada barra de colores son las 13 reglas de la factura" cuerpo="p-0"
        accion={<a href="#/facturas" className="inline-flex items-center gap-1 text-[13px] font-semibold text-azul hover:underline">Ver todas <ArrowRight className="h-3.5 w-3.5" /></a>}>
        <ul className="divide-y divide-bruma">
          {datos.ultimas.slice(0, 6).map((f: FacturaResumen) => (
            <li key={f.id}>
              <a href={`#/facturas/${f.id}`} className="flex items-center gap-3 px-5 py-3.5 hover:bg-niebla">
                <span className="w-14 shrink-0 font-mono text-[12px] text-pizarra">{f.id}</span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[14px] font-semibold">{f.beneficiario}</span>
                  <span className="block truncate text-xs text-pizarra">{f.motivo}</span>
                </span>
                <span className="hidden text-right text-[13px] font-semibold num sm:block">{dinero(f.monto, f.moneda ?? "USD")}</span>
                <EstadoChip estado={f.estado} />
              </a>
            </li>
          ))}
        </ul>
      </Panel>
      <p className="text-center text-xs text-pizarra">{numero(m.total)} facturas procesadas · reglas v{datos.version_reglas} · calculado el {fecha(new Date().toISOString())}</p>
    </div>
  );
}

function Seccion({ titulo, texto, children }: { titulo: string; texto?: ReactNode; children: ReactNode }) {
  return (
    <section className="space-y-4">
      <div>
        <h2 className="text-[18px] font-semibold tracking-tight text-noche">{titulo}</h2>
        {texto && <p className="mt-0.5 text-[13.5px] text-pizarra">{texto}</p>}
      </div>
      {children}
    </section>
  );
}

function ResumenVacio({ usuario, cabecera }: { usuario: Usuario; cabecera: ReactNode }) {
  return (
    <div className="space-y-8">
      {cabecera}
      <section className="flex flex-col items-center rounded-lg border border-dashed border-pizarra/30 bg-white px-6 py-14 text-center">
        <span className="grid h-14 w-14 place-items-center rounded-full bg-azul-s text-azul"><Inbox className="h-7 w-7" /></span>
        <h2 className="mt-4 text-[20px] font-semibold text-noche">Todavía no hay facturas</h2>
        <p className="mt-2 max-w-lg text-[14.5px] leading-relaxed text-pizarra">
          Cuando llegue la primera factura por correo, chat, PDF, foto o XML, aquí verá lo pagado, lo que espera a una persona,
          los vencimientos y el dinero protegido.
        </p>
        {puede(usuario, "facturas.cargar") && (
          <Boton variante="primario" className="mt-5" icono={<Upload className="h-4 w-4" />} onClick={() => ir("facturas")}>Cargar facturas</Boton>
        )}
      </section>
      <FlujoPago usuario={usuario} />
    </div>
  );
}

function Indicador({ etiqueta, valor, detalle, punto, children }: { etiqueta: string; valor: string; detalle: string; punto?: string; children?: ReactNode }) {
  return (
    <div className="rounded-lg border border-bruma bg-white p-4 shadow-[0_1px_2px_rgba(11,23,54,0.05)] sm:p-5">
      <p className="flex items-center gap-2 text-[12.5px] font-medium text-pizarra">{punto && <span className={cx("h-2 w-2 rounded-full", punto)} />}{etiqueta}</p>
      <p className="mt-1.5 text-[22px] font-semibold tracking-tight text-noche num sm:text-[24px]">{valor}</p>
      <p className="mt-0.5 text-[12.5px] text-pizarra">{detalle}</p>
      {children}
    </div>
  );
}
