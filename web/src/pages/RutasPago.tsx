import { useState } from "react";
import { BadgeCheck, CircleCheck, Lock, Route, ShieldCheck, TriangleAlert } from "lucide-react";
import { api, avisarCambio, dinero, fecha, numero, puede, useApi, type Usuario } from "../api";
import { Aviso, Boton, Campo, Cargando, claseEntrada, cx, Encabezado, Panel, useToast, Vacio } from "../ui";

type Opcion = {
  factura_id: string; numero: string; entidad_id: string; contraparte: string; concepto: string; opcion_id: string; tipo_opcion: string;
  nombre_opcion: string; descripcion: string; fecha_pago_inicial: string; fecha_pago_final: string; moneda_liquidacion: string; riel: string;
  costo_usd: number; ahorro_vs_base_usd: number; requiere_aprobacion: boolean;
};
type Evento = { fecha: string; dia: number; entidad_id: string; tipo: "pago" | "cobro"; factura_id: string | null; concepto: string; importe_usd: number; saldo_usd: number; reserva_usd: number; margen_usd: number; cumple: boolean };
type Ruta = {
  costo_usd: number; opciones: Opcion[]; condiciones: string[]; requiere_aprobacion: boolean; eventos: Evento[]; saldo_final_usd: number;
  saldo_minimo_consolidado_usd: number; minimo_margen_individual_usd: number; cumple_reservas: boolean; inicio: string;
  entidades: { entidad_id: string; nombre: string; saldo_inicial_usd: number; reserva_usd: number }[];
};
type Historia = {
  historia: string; empresa: string; perfil: string; facturas: number; combinaciones_evaluadas: number; combinaciones_factibles: number;
  base: Ruta; kauta: Ruta; ahorro_usd: number; ahorro_pct: number; referencia: { nombre: string; costo_usd: number; coincide: boolean };
  aprobacion: { aprobada_por: string; comentario: string; creada_en: string; huella: string } | null;
};
type General = {
  facturas: { factura_id: string; numero: string; empresa: string; contraparte: string; pais: string; moneda: string; vencimiento: string; costo_base_usd: number; opcion: string | null; fecha_pago: string | null; costo_kauta_usd: number; ahorro_usd: number; estado: "optimizada" | "contractual" | "revision"; motivo: string }[];
  entidades: { entidad_id: string; empresa: string; facturas: number; costo_base_usd: number; costo_kauta_usd: number; ahorro_usd: number; en_revision: number; caja_utilizable_usd: number; margen_usd: number; cumple_reserva: boolean }[];
  ahorro_usd: number; ahorro_potencial_reto_usd: number; en_revision: number; por_cobrar: { facturas: number; total_usd: number };
};
type Datos = { fecha_corte: string; historias: Historia[]; general: General; ahorro_historias_usd: number; coinciden_con_el_reto: number; historias_total: number };

const SERIE = ["#3B5BFD", "#0B1736"];   // Azul señal y Noche: una por entidad
const GRILLA = "#E3E8F2", TINTA_2 = "#5B6782";

export default function RutasPago({ usuario }: { usuario: Usuario }) {
  const { datos, cargando, error, recargar } = useApi<Datos>("/rutas-pago");
  const [pestana, setPestana] = useState("H1");
  if (!datos) return cargando ? <Cargando filas={6} /> : <Vacio titulo="No se pudieron calcular las rutas" texto={error ?? ""} />;
  const g = datos.general;
  const h = datos.historias.find((x) => x.historia === pestana);

  return (
    <div className="space-y-6">
      <Encabezado titulo="Rutas de pago"
        texto={`Con la caja de cada empresa y las alternativas de cada factura, Kauta elige cuándo y cómo pagar para gastar menos sin romper la reserva mínima. Datos del reto con corte al ${fecha(datos.fecha_corte, false)}.`} />

      <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Indicador etiqueta="Ahorro en las 3 historias" valor={dinero(datos.ahorro_historias_usd)} detalle="Frente a pagar todo como dice el contrato" />
        <Indicador etiqueta="Igual a la referencia del reto" valor={`${datos.coinciden_con_el_reto} de ${datos.historias_total}`} detalle="Mismo costo, saldo mínimo y margen que resumen_rutas.csv" tono="menta" />
        <Indicador etiqueta="Ahorro ejecutable del día a día" valor={dinero(g.ahorro_usd)} detalle={`De ${dinero(g.ahorro_potencial_reto_usd)} potenciales: descuentos vencidos y documentos en revisión no cuentan`} />
        <Indicador etiqueta="Facturas que Kauta no toca" valor={String(g.en_revision)} detalle="En disputa, sin aprobación o con exceso de orden de compra" tono="ambar" />
      </section>

      <div className="flex gap-1 overflow-x-auto border-b border-bruma" role="tablist" aria-label="Historias del reto">
        {[...datos.historias.map((x) => [x.historia, `${x.historia} · ${x.empresa}`] as const), ["GENERAL", `Día a día · ${g.facturas.length} facturas`] as const].map(([v, t]) => (
          <button key={v} role="tab" aria-selected={pestana === v} onClick={() => setPestana(v)}
            className={cx("-mb-px shrink-0 border-b-2 px-4 py-2.5 text-[13.5px] font-medium", pestana === v ? "border-azul text-azul-t" : "border-transparent text-pizarra hover:text-noche")}>{t}</button>
        ))}
      </div>

      {h ? <VistaHistoria h={h} usuario={usuario} alAprobar={recargar} /> : <VistaGeneral g={g} />}
    </div>
  );
}

function Indicador({ etiqueta, valor, detalle, tono }: { etiqueta: string; valor: string; detalle: string; tono?: "menta" | "ambar" }) {
  return (
    <div className="rounded-lg border border-bruma bg-white p-5 shadow-[0_1px_2px_rgba(11,23,54,0.05)]">
      <p className="flex items-center gap-2 text-[12.5px] font-medium text-pizarra">{tono && <span className={cx("h-2 w-2 rounded-full", tono === "menta" ? "bg-menta" : "bg-ambar")} />}{etiqueta}</p>
      <p className="mt-1.5 text-[24px] font-semibold tracking-tight text-noche">{valor}</p>
      <p className="mt-1 text-[12.5px] leading-snug text-pizarra">{detalle}</p>
    </div>
  );
}

// ---------------------------------------------------------------- una historia (H1, H2, H3)
function VistaHistoria({ h, usuario, alAprobar }: { h: Historia; usuario: Usuario; alAprobar: () => void }) {
  const k = h.kauta;
  const nombreEntidad = Object.fromEntries(k.entidades.map((e) => [e.entidad_id, e.nombre]));
  return (
    <div className="space-y-6">
      <section className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
        <Panel titulo={`${h.empresa} · ${h.perfil}`} subtitulo={`${h.facturas} facturas por pagar · ${h.combinaciones_evaluadas} combinaciones evaluadas, ${h.combinaciones_factibles} cumplen la reserva`}>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <div><p className="text-[12.5px] text-pizarra">Pagar como dice el contrato</p><p className="mt-1 text-[20px] font-semibold text-noche-3">{dinero(h.base.costo_usd)}</p></div>
            <div><p className="text-[12.5px] text-pizarra">Ruta de Kauta</p><p className="mt-1 text-[20px] font-semibold text-noche">{dinero(k.costo_usd)}</p></div>
            <div><p className="text-[12.5px] text-pizarra">Ahorro</p><p className="mt-1 text-[20px] font-semibold text-menta-t">{dinero(h.ahorro_usd)}</p><p className="text-[12px] text-pizarra">{numero(h.ahorro_pct, 2)} % del total</p></div>
          </div>
          <div className="mt-5 flex flex-wrap gap-2 text-[12.5px]">
            <Chip ok={k.cumple_reservas} texto={k.cumple_reservas ? `Cumple la reserva en cada evento (margen mínimo ${dinero(k.minimo_margen_individual_usd)})` : "Rompe la reserva"} />
            <Chip ok={h.referencia.coincide} texto={h.referencia.coincide ? `Igual a la ruta del reto: «${h.referencia.nombre}»` : `Distinta de la ruta del reto (${dinero(h.referencia.costo_usd)})`} />
            {k.requiere_aprobacion && !h.aprobacion && <span className="inline-flex items-center gap-1.5 rounded-full bg-ambar-s px-2.5 py-1 font-medium text-ambar-t"><TriangleAlert className="h-3.5 w-3.5" />Necesita aprobación del CEO</span>}
          </div>
        </Panel>
        <Aprobacion h={h} usuario={usuario} alAprobar={alAprobar} />
      </section>

      <Panel titulo="Caja de cada entidad frente a su reserva" subtitulo="Saldo después de cada pago y cobro de la ruta de Kauta; la línea punteada es la reserva mínima que nunca se toca">
        <GraficoCaja ruta={k} nombres={nombreEntidad} />
      </Panel>

      <Panel titulo="Qué paga Kauta, cuándo y cómo" subtitulo="Una alternativa por factura; el ahorro es frente al pago contractual" cuerpo="p-0">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[820px] text-[13.5px]">
            <thead><tr className="border-b border-bruma text-left text-[12px] uppercase tracking-wider text-pizarra">
              {["Factura", "Proveedor", "Alternativa", "Paga", "Riel", "Costo", "Ahorro"].map((t, i) => <th key={t} className={cx("px-5 py-2.5 font-semibold", i >= 5 && "text-right")}>{t}</th>)}
            </tr></thead>
            <tbody className="divide-y divide-bruma">
              {k.opciones.map((o) => (
                <tr key={o.factura_id} className="align-top">
                  <td className="px-5 py-3"><p className="whitespace-nowrap font-mono text-[12.5px]">{o.factura_id}</p><p className="text-[12px] text-pizarra">{o.concepto}</p></td>
                  <td className="px-5 py-3">{o.contraparte}<p className="text-[12px] text-pizarra">{nombreEntidad[o.entidad_id] ?? o.entidad_id}</p></td>
                  <td className="px-5 py-3"><span className={cx("rounded px-2 py-0.5 text-[12px] font-semibold", o.tipo_opcion === "BASE" ? "bg-niebla text-noche-3" : "bg-azul-s text-azul-t")}>{o.nombre_opcion}</span>
                    <p className="mt-1 max-w-[280px] text-[12px] leading-snug text-pizarra">{o.descripcion}</p>
                    {o.requiere_aprobacion && <p className="mt-1 inline-flex items-center gap-1 text-[12px] font-medium text-ambar-t"><Lock className="h-3 w-3" />Requiere aprobación</p>}</td>
                  <td className="px-5 py-3 whitespace-nowrap">{fecha(o.fecha_pago_inicial, false)}{o.fecha_pago_final !== o.fecha_pago_inicial && <p className="text-[12px] text-pizarra">y {fecha(o.fecha_pago_final, false)}</p>}</td>
                  <td className="px-5 py-3 whitespace-nowrap text-[12.5px]">{o.riel} · {o.moneda_liquidacion}</td>
                  <td className="px-5 py-3 whitespace-nowrap text-right num">{dinero(o.costo_usd)}</td>
                  <td className={cx("px-5 py-3 whitespace-nowrap text-right font-semibold num", o.ahorro_vs_base_usd > 0 ? "text-menta-t" : o.ahorro_vs_base_usd < 0 ? "text-coral-t" : "text-pizarra")}>
                    {o.ahorro_vs_base_usd === 0 ? "—" : dinero(o.ahorro_vs_base_usd)}
                    {o.ahorro_vs_base_usd < 0 && <p className="text-[12px] font-normal text-pizarra">recargo</p>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      {k.condiciones.length > 0 && (
        <Aviso tono="alerta" titulo="Condiciones antes de ejecutar">
          <ul className="mt-1 list-disc space-y-1 pl-5">{k.condiciones.map((c) => <li key={c}>{c}</li>)}</ul>
        </Aviso>
      )}

      <Panel titulo="Movimientos de caja de la ruta" subtitulo="Cada fila es un pago o un cobro previsto, en el orden en que se revisa la reserva" cuerpo="p-0">
        <div className="max-h-80 overflow-auto">
          <table className="w-full min-w-[760px] text-[13px] num">
            <thead className="sticky top-0 bg-niebla"><tr className="text-left text-[12px] text-pizarra">
              {["Día", "Entidad", "Concepto", "Importe", "Saldo", "Margen sobre la reserva"].map((t, i) => <th key={t} className={cx("px-4 py-2 font-semibold", i >= 3 && "text-right")}>{t}</th>)}
            </tr></thead>
            <tbody className="divide-y divide-bruma">
              {k.eventos.map((e, i) => (
                <tr key={i}>
                  <td className="px-4 py-1.5 whitespace-nowrap">{fecha(e.fecha, false)} <span className="text-pizarra">(día {e.dia})</span></td>
                  <td className="px-4 py-1.5">{nombreEntidad[e.entidad_id] ?? e.entidad_id}</td>
                  <td className="px-4 py-1.5">{e.tipo === "cobro" ? "Cobro previsto" : `${e.factura_id} · ${e.concepto}`}</td>
                  <td className={cx("px-4 py-1.5 text-right", e.importe_usd > 0 ? "text-menta-t" : "")}>{dinero(e.importe_usd)}</td>
                  <td className="px-4 py-1.5 text-right">{dinero(e.saldo_usd)}</td>
                  <td className={cx("px-4 py-1.5 text-right font-medium", e.cumple ? "text-noche" : "text-coral-t")}>{dinero(e.margen_usd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}

function Chip({ ok, texto }: { ok: boolean; texto: string }) {
  return <span className={cx("inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 font-medium", ok ? "bg-menta-s text-menta-t" : "bg-coral-s text-coral-t")}>
    {ok ? <CircleCheck className="h-3.5 w-3.5" /> : <TriangleAlert className="h-3.5 w-3.5" />}{texto}</span>;
}

function Aprobacion({ h, usuario, alAprobar }: { h: Historia; usuario: Usuario; alAprobar: () => void }) {
  const [comentario, setComentario] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const toast = useToast();
  const aprobar = async () => {
    setEnviando(true);
    setError(null);
    try {
      const r = await api<any>(`/rutas-pago/${h.historia}/aprobar`, { cuerpo: { comentario } });
      toast(r.mensaje);
      setComentario("");
      avisarCambio();
      alAprobar();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setEnviando(false);
    }
  };
  return (
    <Panel titulo="Aprobación de la ruta" subtitulo="Las negociaciones y los cambios de moneda los decide el CEO; la firma queda en la auditoría">
      {h.aprobacion ? (
        <div className="space-y-2 text-[13.5px]">
          <p className="flex items-center gap-2 font-semibold text-menta-t"><BadgeCheck className="h-5 w-5" /> Aprobada por {h.aprobacion.aprobada_por}</p>
          <p className="text-pizarra">{fecha(h.aprobacion.creada_en)} · huella {h.aprobacion.huella}</p>
          <p className="rounded-md bg-niebla px-3 py-2 text-noche-3">«{h.aprobacion.comentario}»</p>
        </div>
      ) : puede(usuario, "rutas.aprobar") ? (
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); aprobar(); }}>
          <Campo etiqueta="Comentario de la decisión">
            <textarea className={claseEntrada + " min-h-[72px]"} value={comentario} onChange={(e) => setComentario(e.target.value)} maxLength={500}
              placeholder="Ej.: Negociar la prórroga con el proveedor y confirmar el cobro del día 25." required />
          </Campo>
          {error && <Aviso tono="error">{error}</Aviso>}
          <Boton variante="primario" type="submit" cargando={enviando} disabled={comentario.trim().length < 3} icono={<ShieldCheck className="h-4 w-4" />}>Aprobar ruta</Boton>
        </form>
      ) : (
        <p className="flex gap-2 text-[13.5px] text-pizarra"><Route className="mt-0.5 h-4 w-4 shrink-0 text-azul" />Pendiente de la aprobación del CEO. Cuando la apruebe, Finanzas la ejecuta al cumplirse sus condiciones.</p>
      )}
    </Panel>
  );
}

// ---------------------------------------------------------------- gráfica: saldo escalonado vs reserva, por entidad
function GraficoCaja({ ruta, nombres }: { ruta: Ruta; nombres: Record<string, string> }) {
  const W = 1000, H = 300, L = 64, R = 170, T = 16, B = 36;
  const AN = W - L - R, AL = H - T - B;
  const ultimoDia = Math.max(30, ...ruta.eventos.map((e) => e.dia));
  const series = ruta.entidades.map((ent, i) => {
    const puntos = [{ dia: 0, saldo: ent.saldo_inicial_usd }];
    for (const e of ruta.eventos.filter((x) => x.entidad_id === ent.entidad_id)) puntos.push({ dia: e.dia, saldo: e.saldo_usd });
    return { ...ent, color: SERIE[i % SERIE.length], puntos };
  });
  const max = Math.max(...series.flatMap((s) => s.puntos.map((p) => p.saldo)), 1) * 1.08;
  const paso = max > 60000 ? 20000 : max > 30000 ? 10000 : 5000;
  const marcas = Array.from({ length: Math.floor(max / paso) + 1 }, (_, i) => i * paso);
  const x = (d: number) => L + (d / ultimoDia) * AN;
  const y = (v: number) => T + AL - (v / max) * AL;
  const escalones = (pts: { dia: number; saldo: number }[]) => {
    let d = `M${x(pts[0].dia)} ${y(pts[0].saldo)}`;
    for (let i = 1; i < pts.length; i++) d += ` H${x(pts[i].dia)} V${y(pts[i].saldo)}`;
    return d + ` H${x(ultimoDia)}`;
  };
  return (
    <div>
      <div className="mb-2 flex flex-wrap gap-x-5 gap-y-1 text-[12.5px] text-pizarra">
        {series.map((s) => (
          <span key={s.entidad_id} className="inline-flex items-center gap-2">
            <svg width="18" height="4" aria-hidden="true"><line x1="0" y1="2" x2="18" y2="2" stroke={s.color} strokeWidth="2.5" /></svg>{nombres[s.entidad_id] ?? s.entidad_id}
            <svg width="18" height="4" aria-hidden="true"><line x1="0" y1="2" x2="18" y2="2" stroke={s.color} strokeWidth="1.5" strokeDasharray="4 3" /></svg>reserva
          </span>
        ))}
      </div>
      <div className="overflow-x-auto"><svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full min-w-[640px]" role="img"
        aria-label={`Saldo por entidad durante la ruta; el margen mínimo sobre la reserva es ${dinero(ruta.minimo_margen_individual_usd)}`}>
        {marcas.map((m) => (
          <g key={m}><line x1={L} x2={L + AN} y1={y(m)} y2={y(m)} stroke={GRILLA} />
            <text x={L - 10} y={y(m) + 4} textAnchor="end" fontSize="12" fill={TINTA_2}>{m >= 1000 ? `${m / 1000}k` : m}</text></g>
        ))}
        {[0, 7, 14, 21, 28, 35, 42].filter((d) => d <= ultimoDia).map((d) => (
          <text key={d} x={x(d)} y={H - 12} textAnchor="middle" fontSize="12" fill={TINTA_2}>día {d}</text>
        ))}
        {series.map((s) => (
          <g key={s.entidad_id}>
            <line x1={L} x2={L + AN} y1={y(s.reserva_usd)} y2={y(s.reserva_usd)} stroke={s.color} strokeWidth="1.5" strokeDasharray="6 5" opacity="0.8" />
            <path d={escalones(s.puntos)} fill="none" stroke={s.color} strokeWidth="2.5" strokeLinejoin="round" />
            {s.puntos.slice(1).map((p, i) => (
              <circle key={i} cx={x(p.dia)} cy={y(p.saldo)} r="4.5" fill={s.color} stroke="#FFFFFF" strokeWidth="2">
                <title>{`Día ${p.dia}: saldo ${dinero(p.saldo)} (reserva ${dinero(s.reserva_usd)})`}</title>
              </circle>
            ))}
            <text x={L + AN + 10} y={y(s.puntos[s.puntos.length - 1].saldo) + 4} fontSize="12.5" fontWeight="600" fill="#0B1736">
              {dinero(s.puntos[s.puntos.length - 1].saldo, "USD", 0)}
            </text>
            <text x={L + AN + 10} y={y(s.reserva_usd) + 16} fontSize="11.5" fill={TINTA_2}>reserva {dinero(s.reserva_usd, "USD", 0)}</text>
          </g>
        ))}
      </svg></div>
    </div>
  );
}

// ---------------------------------------------------------------- el día a día (escenario general)
function VistaGeneral({ g }: { g: General }) {
  const [empresa, setEmpresa] = useState("");
  const filas = g.facturas.filter((f) => !empresa || f.empresa === empresa);
  const ESTADO = { optimizada: ["Ruta optimizada", "bg-menta-s text-menta-t"], contractual: ["Pago contractual", "bg-niebla text-noche-3"], revision: ["En revisión", "bg-ambar-s text-ambar-t"] } as const;
  return (
    <div className="space-y-6">
      <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-5">
        {g.entidades.map((e) => (
          <button key={e.entidad_id} type="button" onClick={() => setEmpresa(empresa === e.empresa ? "" : e.empresa)}
            className={cx("rounded-lg border bg-white p-4 text-left shadow-[0_1px_2px_rgba(11,23,54,0.05)]", empresa === e.empresa ? "border-azul ring-2 ring-azul-s" : "border-bruma hover:border-pizarra/40")}>
            <p className="text-[13.5px] font-semibold">{e.empresa}</p>
            <p className="mt-1 text-[12.5px] text-pizarra">{e.facturas} facturas · {e.en_revision} en revisión</p>
            <p className="mt-2 text-[18px] font-semibold text-menta-t">{dinero(e.ahorro_usd)}</p>
            <p className="text-[12px] text-pizarra">de ahorro · margen de caja {dinero(e.margen_usd, "USD", 0)}</p>
          </button>
        ))}
      </section>
      <Panel titulo={`Facturas por pagar${empresa ? ` · ${empresa}` : ""}`} subtitulo="La alternativa ejecutable más barata de cada factura; las que piden revisión esperan a una persona" cuerpo="p-0">
        <div className="max-h-[520px] overflow-auto">
          <table className="w-full min-w-[900px] text-[13px]">
            <thead className="sticky top-0 z-10 bg-white"><tr className="border-b border-bruma text-left text-[12px] uppercase tracking-wider text-pizarra">
              {["Factura", "Proveedor", "Vence", "Costo contractual", "Kauta", "Ahorro", "Estado"].map((t, i) => <th key={t} className={cx("px-4 py-2.5 font-semibold", (i === 3 || i === 5) && "text-right")}>{t}</th>)}
            </tr></thead>
            <tbody className="divide-y divide-bruma">
              {filas.map((f) => (
                <tr key={f.factura_id} className="align-top">
                  <td className="px-4 py-2.5"><p className="whitespace-nowrap font-mono text-[12px]">{f.factura_id}</p><p className="text-[12px] text-pizarra">{f.empresa}</p></td>
                  <td className="px-4 py-2.5">{f.contraparte}<p className="text-[12px] text-pizarra">{f.pais} · {f.moneda}</p></td>
                  <td className="px-4 py-2.5 whitespace-nowrap">{fecha(f.vencimiento, false)}</td>
                  <td className="px-4 py-2.5 whitespace-nowrap text-right num">{dinero(f.costo_base_usd)}</td>
                  <td className="px-4 py-2.5">{f.opcion ?? "—"}{f.fecha_pago && <p className="whitespace-nowrap text-[12px] text-pizarra">paga {fecha(f.fecha_pago, false)}</p>}</td>
                  <td className={cx("px-4 py-2.5 whitespace-nowrap text-right font-semibold num", f.ahorro_usd > 0 ? "text-menta-t" : "text-pizarra")}>{f.ahorro_usd > 0 ? dinero(f.ahorro_usd) : "—"}</td>
                  <td className="px-4 py-2.5"><span className={cx("rounded px-2 py-0.5 text-[12px] font-semibold", ESTADO[f.estado][1])}>{ESTADO[f.estado][0]}</span>
                    {f.motivo && <p className="mt-1 max-w-[220px] text-[12px] leading-snug text-pizarra">{f.motivo}</p>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
      <p className="text-[12.5px] text-pizarra">Por cobrar en el escenario general: {g.por_cobrar.facturas} facturas por {dinero(g.por_cobrar.total_usd, "USD", 0)}. Son ingresos previstos: no se usan para pagar hasta que lleguen.</p>
    </div>
  );
}
