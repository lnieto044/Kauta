import { useState } from "react";
import { ArrowUpRight, ChevronRight, Info } from "lucide-react";
import { dinero, fecha, numero, PERIODO, useApi } from "../api";
import { Cargando, cx, Panel, Vacio } from "../ui";
import { diaMes, BarrasH, CATEGORIA, CabeceraTablero, cifra, Columnas, FranjaKpi, variacion } from "../graficas";
import { CANALES } from "./Facturas";

type Indicadores = {
  finales: number; pagadas: number; facturas: number; con_ia: number; costo_total_usd: number; costo_por_factura_usd: number | null;
  costo_pago_usd: number | null; pago_total_usd: number; sin_ia_pct: number | null; cobertura_pct: number | null; casillas: number;
  casillas_conocidas: number;
};
type Datos = {
  periodo: string; periodos: string[]; anterior: string | null; indicadores: Indicadores; indicadores_anteriores: Indicadores | null;
  componentes: { clave: string; nombre: string; detalle: string; valor_usd: number }[];
  lectura: { metodo: string; nombre: string; facturas: number; costo_usd: number }[];
  por_canal: { canal: string; facturas: number; costo_medio_usd: number }[];
  por_semana: { desde: string; hasta: string; facturas: number; costo_usd: number; costo_medio_usd: number }[];
  en_curso: { facturas: number; por_estado: Record<string, number>; costo_conocido_usd: number };
  tarifas: { lectura_ia_usd: number; revision_minutos: number; hora_revision_usd: number; infraestructura_mes_usd: number };
  calculado_en: string;
};

const fino = (v: number) => dinero(v, "USD", Math.abs(v) > 0 && Math.abs(v) < 1 ? 4 : 2);
const corta = diaMes;

export default function Rendimiento() {
  const [periodo, setPeriodo] = useState<string | null>(null);
  const { datos, cargando, error } = useApi<Datos>(`/costos${periodo ? `?periodo=${periodo}` : ""}`, [periodo]);
  if (!datos) return cargando ? <Cargando filas={6} /> : <Vacio titulo="No se pudieron calcular los costos" texto={error ?? ""} />;
  const i = datos.indicadores, a = datos.indicadores_anteriores;
  const contra = datos.anterior ? PERIODO(datos.anterior) : null;
  const total = datos.componentes.reduce((s, c) => s + c.valor_usd, 0);

  return (
    <div className={cx("space-y-8 transition-opacity", cargando && "opacity-60")}>
      <CabeceraTablero antetitulo={`Costos del periodo · ${PERIODO(datos.periodo)}`} titulo="Rendimiento y costos"
        texto="¿Cuánto cuesta resolver una factura y dónde se va el dinero?"
        accion={<>
          <label className="text-[13px] text-pizarra" htmlFor="periodo-costos">Periodo</label>
          <select id="periodo-costos" className="min-h-9 rounded-md border border-pizarra/25 bg-white px-3 text-[13.5px] shadow-sm"
            value={datos.periodo} onChange={(e) => setPeriodo(e.target.value)}>
            {datos.periodos.map((p) => <option key={p} value={p}>{PERIODO(p)}</option>)}
          </select>
        </>} />

      <FranjaKpi titulo="Costos por factura" items={[
        { etiqueta: "Costo por factura resuelta", ...cifra(i.costo_por_factura_usd, 2), contra,
          cambio: variacion(i.costo_por_factura_usd, a?.costo_por_factura_usd, "usd", "baja"),
          detalle: i.finales ? `${dinero(i.costo_total_usd)} entre ${i.finales} facturas resueltas` : "Aún no hay facturas resueltas en el periodo" },
        { etiqueta: "Costo de pagar una factura", ...cifra(i.costo_pago_usd, 2), contra,
          cambio: variacion(i.costo_pago_usd, a?.costo_pago_usd, "usd", "baja"),
          detalle: `Comisión y cambio de PayPal entre ${i.pagadas} pagadas` },
        { etiqueta: "Leído sin IA", valor: i.sin_ia_pct == null ? "—" : `${numero(i.sin_ia_pct, i.sin_ia_pct % 1 ? 1 : 0)} %`, contra,
          cambio: variacion(i.sin_ia_pct, a?.sin_ia_pct, "pct", "sube"),
          detalle: `${i.facturas - i.con_ia} de ${i.facturas} facturas; ${i.con_ia} con IA` },
        { etiqueta: "Cobertura de costos", valor: i.cobertura_pct == null ? "—" : `${numero(i.cobertura_pct, 0)} %`,
          detalle: `${i.casillas_conocidas} de ${i.casillas} casillas con importe conocido` },
      ]} />

      <Panel titulo="Dónde se va el costo" subtitulo={`Todo lo que costaron las facturas resueltas en ${PERIODO(datos.periodo)}`}
        accion={<p className="text-[15px] font-semibold text-noche num">{dinero(total)} <span className="font-normal text-pizarra">conocidos</span></p>}>
        <div className="flex h-3.5 gap-[3px] overflow-hidden rounded-full bg-niebla" role="img"
          aria-label={datos.componentes.map((c) => `${c.nombre} ${fino(c.valor_usd)}`).join(", ")}>
          {datos.componentes.map((c, k) => c.valor_usd > 0 && (
            <span key={c.clave} className="h-full first:rounded-l-full last:rounded-r-full" title={`${c.nombre}: ${fino(c.valor_usd)}`}
              style={{ width: `${(c.valor_usd / (total || 1)) * 100}%`, minWidth: 4, background: CATEGORIA[k] }} />
          ))}
        </div>
        <ul className="mt-5 divide-y divide-bruma">
          {datos.componentes.map((c, k) => (
            <li key={c.clave} className="flex items-center gap-3 py-3">
              <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: CATEGORIA[k] }} aria-hidden="true" />
              <span className="min-w-0 flex-1">
                <span className="block text-[14px] font-medium text-noche">{c.nombre}</span>
                <span className="block text-[12.5px] text-pizarra">{c.detalle}</span>
              </span>
              <span className="w-14 text-right text-[12.5px] text-pizarra num">{total ? `${numero((c.valor_usd / total) * 100, 0)} %` : "—"}</span>
              <span className="w-28 text-right text-[14px] font-semibold text-noche num">{fino(c.valor_usd)}</span>
            </li>
          ))}
        </ul>
        <details className="group mt-2 border-t border-bruma pt-3">
          <summary className="flex cursor-pointer list-none items-center gap-1.5 text-[13.5px] font-semibold text-azul">
            <ChevronRight className="h-4 w-4 transition-transform group-open:rotate-90" /> Desglosar lectura: XML, texto, OCR e IA
          </summary>
          <table className="mt-3 w-full text-[13px] num">
            <thead><tr className="text-left text-[12px] text-pizarra"><th className="py-1 font-medium">Cómo se leyó</th><th className="py-1 text-right font-medium">Facturas</th><th className="py-1 text-right font-medium">Costo</th></tr></thead>
            <tbody className="divide-y divide-bruma">
              {datos.lectura.map((l) => <tr key={l.metodo}><td className="py-1.5">{l.nombre}</td><td className="py-1.5 text-right">{l.facturas}</td><td className="py-1.5 text-right">{fino(l.costo_usd)}</td></tr>)}
            </tbody>
          </table>
        </details>
      </Panel>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Panel titulo="Costo por factura según el canal" subtitulo="Promedio por factura resuelta, con su parte de la infraestructura">
          {datos.por_canal.length ? (
            <BarrasH formato={(v) => dinero(v)} filas={datos.por_canal.map((c) => ({
              etiqueta: CANALES[c.canal]?.t ?? c.canal, detalle: `${c.facturas} ${c.facturas === 1 ? "resuelta" : "resueltas"}`, texto: dinero(c.costo_medio_usd),
              partes: [{ nombre: "Costo medio", valor: c.costo_medio_usd, color: CATEGORIA[0] }],
            }))} />
          ) : <p className="text-[13.5px] text-pizarra">Sin facturas resueltas en el periodo.</p>}
        </Panel>
        <Panel titulo="Costo por semana" subtitulo="Lo que costó resolver las facturas, por la semana en que llegaron">
          {datos.por_semana.length ? (
            <Columnas formato={(v) => dinero(v, "USD", 0)} columnas={datos.por_semana.map((s) => ({
              etiqueta: corta(s.desde), subetiqueta: `${s.facturas} fact. · ${dinero(s.costo_medio_usd)} c/u`,
              partes: [{ nombre: "Costo", valor: s.costo_usd, color: CATEGORIA[0] }],
            }))} />
          ) : <p className="text-[13.5px] text-pizarra">Sin facturas resueltas en el periodo.</p>}
        </Panel>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
        <section>
          <h2 className="text-[17px] font-semibold text-noche">Lo resuelto y lo que sigue en curso</h2>
          <p className="mt-2 text-[15px] leading-relaxed text-noche-3">
            El costo por factura resuelta usa {dinero(i.costo_total_usd)} entre {i.finales} facturas finales (pagadas, frenadas o rechazadas).
            {datos.en_curso.facturas > 0
              ? ` Otras ${datos.en_curso.facturas} facturas siguen abiertas, con ${dinero(datos.en_curso.costo_conocido_usd)} conocidos que aún no entran en esa métrica.`
              : " No quedan facturas abiertas en el periodo."}
          </p>
          <a href="#/facturas" className="mt-3 inline-flex items-center gap-1 text-[14px] font-semibold text-azul hover:underline">Abrir facturas <ArrowUpRight className="h-4 w-4" /></a>
        </section>
        <aside className="rounded-lg border border-bruma bg-white p-5">
          <p className="flex items-center gap-2 text-[15px] font-semibold text-noche"><Info className="h-4 w-4 text-pizarra" /> Cómo leer estas cifras</p>
          <ul className="mt-3 space-y-2 text-[13.5px] leading-relaxed text-noche-3">
            <li><b>Lectura:</b> el XML fiscal, el texto del PDF y el OCR local no cobran por documento; la IA, unos {dinero(datos.tarifas.lectura_ia_usd, "USD", 3)} por documento (estimado). En modo demo, lo que no es XML se lee con su extracción verificada.</li>
            <li><b>Revisión humana:</b> {datos.tarifas.revision_minutos} minutos por decisión a {dinero(datos.tarifas.hora_revision_usd, "USD", 0)} la hora (estimado).</li>
            <li><b>Pago:</b> la comisión y el cambio reales de cada pago por PayPal; un pago devuelto no cobra comisión.</li>
            <li><b>Infraestructura:</b> {dinero(datos.tarifas.infraestructura_mes_usd, "USD", 0)} al mes repartidos entre las facturas finales; es provisional hasta el cierre.</li>
          </ul>
          <p className="mt-3 border-t border-bruma pt-3 text-[12.5px] text-pizarra">Cálculo actual · {fecha(datos.calculado_en)} · igual para CEO, Finanzas y Administración</p>
        </aside>
      </div>
    </div>
  );
}
