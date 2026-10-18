/**
 * Gráficas de Kauta (Resumen y Rendimiento): franja de indicadores con variación, barras, columnas,
 * tendencia y cascada. Colores de la marca; cada serie lleva su etiqueta o leyenda (nunca solo el color).
 */
import { useMemo, useRef, useState, type ReactNode } from "react";
import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";
import { dinero, fecha, numero } from "./api";
import { cx } from "./ui";

export type Kpi = { clave: string; nombre: string; unidad: "usd" | "pct" | "num"; mejor: "sube" | "baja" | null; ayuda: string; actual: number | null; anterior: number | null };
export type Punto = { dia: number; fecha: string; pagado: number | null; ritmo: number };
export type Paso = { clave: string; nombre: string; valor: number; tipo: "total" | "frenado" | "otro" | "espera" | "pagado" };
export type DatosRendimiento = {
  periodo: string; periodos: string[]; presupuesto: number; semana: { actual: string | null; anterior: string | null };
  kpis: Kpi[]; semanas: any[]; tendencia: Punto[]; cascada: Paso[];
};

// Estados (significado fijo en toda la app) y categorías validadas con el verificador de paletas (todas con etiqueta)
export const ESTADO = { pagado: "#16C79A", espera: "#FFB547", frenado: "#FF5C5C", neutro: "#5B6782" } as const;
export const CATEGORIA = ["#3B5BFD", "#D98E1F", "#0F9E78", "#7A4FE0"] as const;
const COLOR_PASO: Record<Paso["tipo"], string> = { total: "#0B1736", frenado: "#FF5C5C", espera: "#FFB547", otro: "#5B6782", pagado: "#16C79A" };
const ACCION = "#3B5BFD", REFERENCIA = "#5B6782", GRILLA = "#E3E8F2", TINTA = "#0B1736", TINTA_2 = "#5B6782";
const MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sept", "oct", "nov", "dic"];
/** «19 oct»: corto para ejes y etiquetas. */
export const diaMes = (iso: string) => `${Number(iso.slice(8, 10))} ${MESES[Number(iso.slice(5, 7)) - 1]}`;
export const compacto = (v: number) => (Math.abs(v) >= 1000 ? `${numero(v / 1000, Math.abs(v) >= 10000 ? 0 : 1)}k` : numero(v));

// ---------------------------------------------------------------- variación (indicador de tendencia ↑ ↓)
export type Cambio = { dir: "sube" | "baja" | "igual"; texto: string; tono: "bueno" | "malo" | "neutro" };
export function variacion(actual: number | null | undefined, anterior: number | null | undefined, unidad: "usd" | "pct" | "num", mejor: "sube" | "baja" | null): Cambio | null {
  if (actual == null || anterior == null) return null;
  let delta: number, texto: string;
  if (unidad === "pct") {
    delta = actual - anterior;
    texto = `${delta > 0 ? "+" : ""}${numero(delta, Math.abs(delta) < 10 && delta % 1 ? 1 : 0)} pts`;
  } else if (anterior === 0) {
    if (actual === 0) return { dir: "igual", texto: "sin cambio", tono: "neutro" };
    return { dir: "sube", texto: "nuevo", tono: mejor == null ? "neutro" : mejor === "sube" ? "bueno" : "malo" };
  } else {
    delta = ((actual - anterior) / Math.abs(anterior)) * 100;
    texto = `${delta > 0 ? "+" : ""}${numero(delta, 0)} %`;
  }
  const dir = Math.abs(delta) < 0.5 ? "igual" : delta > 0 ? "sube" : "baja";
  const tono = mejor == null || dir === "igual" ? "neutro" : dir === mejor ? "bueno" : "malo";
  return { dir, texto, tono };
}

export function ChipCambio({ c, contra }: { c: Cambio; contra?: string | null }) {
  const Icono = c.dir === "sube" ? ArrowUpRight : c.dir === "baja" ? ArrowDownRight : Minus;
  const significado = `${c.dir === "sube" ? "Subió" : c.dir === "baja" ? "Bajó" : "Sin cambio"} ${c.texto}${c.tono === "bueno" ? ", mejora" : c.tono === "malo" ? ", empeora" : ""}`;
  return (
    <span className="inline-flex flex-wrap items-center gap-x-1.5 text-[12.5px]" aria-label={contra ? `${significado} frente a ${contra}` : significado}>
      <span className={cx("inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 font-semibold",
        c.tono === "bueno" ? "bg-menta-s text-menta-t" : c.tono === "malo" ? "bg-coral-s text-coral-t" : "bg-niebla text-noche-3")}>
        <Icono className="h-3.5 w-3.5" strokeWidth={2.25} aria-hidden="true" />{c.texto}
      </span>
      {contra && <span className="text-pizarra">vs {contra}</span>}
    </span>
  );
}

// ---------------------------------------------------------------- cabecera de tablero
export function CabeceraTablero({ antetitulo, titulo, texto, accion }: { antetitulo: ReactNode; titulo: string; texto: ReactNode; accion?: ReactNode }) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-4 border-b border-bruma pb-6">
      <div className="max-w-3xl">
        <p className="flex items-center gap-2 text-[12.5px] font-medium text-pizarra"><span className="h-1.5 w-1.5 rounded-full bg-menta" aria-hidden="true" />{antetitulo}</p>
        <h1 className="mt-2 text-[26px] font-semibold leading-tight tracking-tight text-noche sm:text-[30px]">{titulo}</h1>
        <p className="mt-1.5 text-[15px] text-pizarra">{texto}</p>
      </div>
      {accion && <div className="flex flex-wrap items-center gap-2">{accion}</div>}
    </header>
  );
}

// ---------------------------------------------------------------- franja de indicadores (cifras grandes, separadas por líneas)
export type ItemFranja = { etiqueta: string; valor: string; unidad?: string; detalle?: ReactNode; cambio?: Cambio | null; contra?: string | null; tono?: "alerta" | "bien" };
export function FranjaKpi({ items, titulo }: { items: ItemFranja[]; titulo?: string }) {
  return (
    <section aria-label={titulo ?? "Indicadores"} className="overflow-hidden rounded-lg border border-bruma bg-bruma shadow-[0_1px_2px_rgba(11,23,54,0.05)]">
      <div className={cx("grid gap-px", items.length >= 4 ? "grid-cols-1 sm:grid-cols-2 xl:grid-cols-4" : "grid-cols-1 sm:grid-cols-3")}>
        {items.map((k) => (
          <div key={k.etiqueta} className="bg-white px-5 py-5 sm:px-6">
            <p className="flex items-center gap-2 text-[13px] font-medium text-pizarra">
              {k.tono && <span className={cx("h-2 w-2 rounded-full", k.tono === "alerta" ? "bg-ambar" : "bg-menta")} aria-hidden="true" />}{k.etiqueta}
            </p>
            <p className="mt-2 flex items-baseline gap-1.5 text-noche">
              {k.unidad && <span className="text-[14px] font-medium text-pizarra">{k.unidad}</span>}
              <span className="text-[32px] font-semibold leading-none tracking-tight num">{k.valor}</span>
            </p>
            {k.cambio && <p className="mt-2.5"><ChipCambio c={k.cambio} contra={k.contra} /></p>}
            {k.detalle && <p className="mt-2 text-[12.5px] leading-snug text-pizarra">{k.detalle}</p>}
          </div>
        ))}
      </div>
    </section>
  );
}

/** Valor de dinero partido en unidad y cifra, para la franja («USD» pequeño delante). */
export function cifra(v: number | null | undefined, dec = 0): { unidad?: string; valor: string } {
  if (v == null) return { valor: "—" };
  return { unidad: "USD", valor: numero(v, dec) };
}

// ---------------------------------------------------------------- leyenda
export function Leyenda({ series }: { series: { nombre: string; color: string }[] }) {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-[12.5px] text-pizarra">
      {series.map((s) => <span key={s.nombre} className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm" style={{ background: s.color }} aria-hidden="true" />{s.nombre}</span>)}
    </div>
  );
}

// ---------------------------------------------------------------- barras horizontales (simples o apiladas)
export type FilaBarra = { etiqueta: ReactNode; detalle?: ReactNode; partes: { nombre: string; valor: number; color: string }[]; texto: string };
export function BarrasH({ filas, max, alto = 12, formato = (v: number) => dinero(v, "USD", 0) }: { filas: FilaBarra[]; max?: number; alto?: number; formato?: (v: number) => string }) {
  const tope = max ?? Math.max(1, ...filas.map((f) => f.partes.reduce((a, p) => a + p.valor, 0)));
  return (
    <ul className="space-y-3.5">
      {filas.map((f, i) => (
        <li key={i} className="group">
          <div className="flex items-baseline justify-between gap-3 text-[13px]">
            <span className="min-w-0 truncate font-medium text-noche">{f.etiqueta}{f.detalle && <span className="ml-2 font-normal text-pizarra">{f.detalle}</span>}</span>
            <span className="shrink-0 font-semibold text-noche num">{f.texto}</span>
          </div>
          <div className="mt-1.5 flex gap-[2px] rounded-full bg-niebla" style={{ height: alto }}>
            {f.partes.filter((p) => p.valor > 0).map((p) => (
              <span key={p.nombre} className="h-full rounded-full transition-opacity group-hover:opacity-90" style={{ width: `${(p.valor / tope) * 100}%`, background: p.color, minWidth: 3 }}
                title={`${p.nombre}: ${formato(p.valor)}`} />
            ))}
          </div>
        </li>
      ))}
    </ul>
  );
}

// ---------------------------------------------------------------- columnas apiladas (una por semana o por categoría)
export type Columna = { etiqueta: string; subetiqueta?: string; partes: { nombre: string; valor: number; color: string }[]; texto?: string; destacada?: boolean };
export function Columnas({ columnas, alto = 190, formato = (v: number) => numero(v) }: { columnas: Columna[]; alto?: number; formato?: (v: number) => string }) {
  const [foco, setFoco] = useState<number | null>(null);
  const tope = Math.max(1, ...columnas.map((c) => c.partes.reduce((a, p) => a + p.valor, 0)));
  return (
    <div>
      <div className="flex items-end gap-2 border-b border-bruma sm:gap-3" style={{ height: alto + 24 }}>
        {columnas.map((c, i) => {
          const total = c.partes.reduce((a, p) => a + p.valor, 0);
          return (
            <div key={c.etiqueta} className="relative flex h-full min-w-0 flex-1 flex-col items-center justify-end"
              onMouseEnter={() => setFoco(i)} onMouseLeave={() => setFoco(null)} tabIndex={0} onFocus={() => setFoco(i)} onBlur={() => setFoco(null)}
              aria-label={`${c.etiqueta}: ${c.partes.map((p) => `${p.nombre} ${formato(p.valor)}`).join(", ")}`}>
              <span className="mb-1 text-[12px] font-semibold text-noche num">{total > 0 ? (c.texto ?? formato(total)) : ""}</span>
              <div className={cx("flex w-full max-w-[44px] flex-col-reverse gap-[2px]", foco != null && foco !== i && "opacity-60")} style={{ height: (total / tope) * alto }}>
                {c.partes.filter((p) => p.valor > 0).map((p, j, arr) => (
                  <span key={p.nombre} className={cx(j === arr.length - 1 && "rounded-t-[4px]")} style={{ height: `${(p.valor / total) * 100}%`, background: p.color, minHeight: 2 }} />
                ))}
              </div>
              {foco === i && total > 0 && (
                <div className="pointer-events-none absolute bottom-full z-10 mb-1 min-w-[150px] rounded-md border border-bruma bg-white px-3 py-2 text-[12px] shadow-lg">
                  <p className="font-semibold text-noche">{c.etiqueta}</p>
                  {c.partes.map((p) => <p key={p.nombre} className="flex justify-between gap-3"><span className="inline-flex items-center gap-1.5 text-pizarra"><span className="h-2 w-2 rounded-sm" style={{ background: p.color }} />{p.nombre}</span><b className="num">{formato(p.valor)}</b></p>)}
                </div>
              )}
            </div>
          );
        })}
      </div>
      <div className="mt-1.5 flex gap-2 sm:gap-3">
        {columnas.map((c) => (
          <div key={c.etiqueta} className="min-w-0 flex-1 text-center">
            <p className={cx("truncate text-[11.5px]", c.destacada ? "font-semibold text-noche" : "text-pizarra")}>{c.etiqueta}</p>
            {c.subetiqueta && <p className="truncate text-[11px] text-pizarra">{c.subetiqueta}</p>}
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- tendencia: línea + ritmo del presupuesto
export function Tendencia({ puntos, presupuesto }: { puntos: Punto[]; presupuesto: number }) {
  const [foco, setFoco] = useState<number | null>(null);
  const [tabla, setTabla] = useState(false);
  const caja = useRef<SVGSVGElement>(null);
  const W = 1000, H = 290, L = 56, R = 150, T = 16, B = 34;
  const AN = W - L - R, AL = H - T - B;
  const reales = puntos.filter((p) => p.pagado != null);
  const max = Math.max(presupuesto * 1.05, ...reales.map((p) => p.pagado ?? 0), 1);
  const paso = max > 40000 ? 10000 : max > 12000 ? 5000 : 2000;
  const marcas = Array.from({ length: Math.floor(max / paso) + 1 }, (_, i) => i * paso);
  const x = (i: number) => L + (puntos.length > 1 ? (i * AN) / (puntos.length - 1) : AN / 2);
  const y = (v: number) => T + AL - (v / max) * AL;
  const linea = reales.map((p, i) => `${i ? "L" : "M"}${x(p.dia - 1).toFixed(1)} ${y(p.pagado!).toFixed(1)}`).join(" ");
  const area = reales.length ? `${linea} L${x(reales[reales.length - 1].dia - 1).toFixed(1)} ${y(0)} L${x(0)} ${y(0)} Z` : "";
  const ritmo = puntos.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(p.ritmo).toFixed(1)}`).join(" ");
  const ultimo = reales[reales.length - 1];
  const sel = foco != null ? puntos[foco] : null;
  const mover = (e: React.PointerEvent) => {
    const r = caja.current?.getBoundingClientRect();
    if (!r) return;
    const px = ((e.clientX - r.left) / r.width) * W;
    setFoco(Math.max(0, Math.min(puntos.length - 1, Math.round(((px - L) / AN) * (puntos.length - 1)))));
  };
  const teclas = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowRight") setFoco((f) => Math.min(puntos.length - 1, (f ?? -1) + 1));
    if (e.key === "ArrowLeft") setFoco((f) => Math.max(0, (f ?? puntos.length) - 1));
  };
  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-x-5 gap-y-1 text-[12.5px] text-pizarra">
        <span className="inline-flex items-center gap-2"><svg width="18" height="4" aria-hidden="true"><line x1="0" y1="2" x2="18" y2="2" stroke={ACCION} strokeWidth="2.5" /></svg>Pagado acumulado</span>
        <span className="inline-flex items-center gap-2"><svg width="18" height="4" aria-hidden="true"><line x1="0" y1="2" x2="18" y2="2" stroke={REFERENCIA} strokeWidth="2" strokeDasharray="4 3" /></svg>Ritmo del presupuesto (lineal)</span>
        <button type="button" onClick={() => setTabla(!tabla)} className="ml-auto text-[12.5px] font-medium text-azul hover:underline">{tabla ? "Ocultar datos" : "Ver datos"}</button>
      </div>
      <div className="overflow-x-auto"><div className="relative min-w-[640px]">
        <svg ref={caja} viewBox={`0 0 ${W} ${H}`} className="h-auto w-full touch-none outline-none" role="img" tabIndex={0}
          aria-label={`Pagado acumulado del periodo: ${ultimo ? dinero(ultimo.pagado) : "sin pagos"} de ${dinero(presupuesto, "USD", 0)} presupuestados. Use las flechas para recorrer los días.`}
          onPointerMove={mover} onPointerLeave={() => setFoco(null)} onKeyDown={teclas} onBlur={() => setFoco(null)}>
          {marcas.map((m) => (
            <g key={m}>
              <line x1={L} x2={L + AN} y1={y(m)} y2={y(m)} stroke={GRILLA} />
              <text x={L - 10} y={y(m) + 4} textAnchor="end" fontSize="12" fill={TINTA_2}>{compacto(m)}</text>
            </g>
          ))}
          {puntos.map((p, i) => (p.dia === 1 || p.dia % 5 === 0) && (
            <text key={p.dia} x={x(i)} y={H - 10} textAnchor="middle" fontSize="12" fill={TINTA_2}>{p.dia}</text>
          ))}
          <path d={ritmo} fill="none" stroke={REFERENCIA} strokeWidth="2" strokeDasharray="6 5" />
          <text x={L + AN + 10} y={y(puntos[puntos.length - 1]?.ritmo ?? 0) + 4} fontSize="12" fill={TINTA_2}>Presupuesto {compacto(presupuesto)}</text>
          {area && <path d={area} fill={ACCION} fillOpacity="0.1" />}
          {linea && <path d={linea} fill="none" stroke={ACCION} strokeWidth="2.5" strokeLinejoin="round" strokeLinecap="round" />}
          {ultimo && (
            <g>
              <circle cx={x(ultimo.dia - 1)} cy={y(ultimo.pagado!)} r="5" fill={ACCION} stroke="#FFFFFF" strokeWidth="2" />
              <text x={L + AN + 10} y={y(ultimo.pagado!) + 4} fontSize="12.5" fontWeight="600" fill={TINTA}>Pagado {compacto(ultimo.pagado!)}</text>
            </g>
          )}
          {sel && (
            <g pointerEvents="none">
              <line x1={x(foco!)} x2={x(foco!)} y1={T} y2={T + AL} stroke={TINTA_2} strokeWidth="1" />
              {sel.pagado != null && <circle cx={x(foco!)} cy={y(sel.pagado)} r="5" fill={ACCION} stroke="#FFFFFF" strokeWidth="2" />}
              <circle cx={x(foco!)} cy={y(sel.ritmo)} r="4" fill={REFERENCIA} stroke="#FFFFFF" strokeWidth="2" />
            </g>
          )}
        </svg>
        {sel && (
          <div className="pointer-events-none absolute top-2 z-10 min-w-[190px] rounded-md border border-bruma bg-white px-3 py-2 text-[12.5px] shadow-lg"
            style={{ left: `${Math.min(78, Math.max(2, (x(foco!) / W) * 100 - 9))}%` }}>
            <p className="font-medium text-noche">{fecha(sel.fecha, false)}</p>
            <p className="mt-1 flex items-center justify-between gap-3"><span className="inline-flex items-center gap-1.5 text-pizarra"><span className="h-0.5 w-3 bg-azul" />Pagado</span><b className="num">{sel.pagado == null ? "—" : dinero(sel.pagado, "USD", 0)}</b></p>
            <p className="flex items-center justify-between gap-3"><span className="inline-flex items-center gap-1.5 text-pizarra"><span className="h-0.5 w-3 bg-pizarra" />Ritmo</span><b className="num">{dinero(sel.ritmo, "USD", 0)}</b></p>
          </div>
        )}
      </div></div>
      {tabla && (
        <div className="mt-3 max-h-64 overflow-auto rounded-md border border-bruma">
          <table className="w-full text-[13px] num">
            <thead className="sticky top-0 bg-niebla text-left text-[12px] text-pizarra"><tr><th className="px-3 py-1.5">Día</th><th className="px-3 py-1.5 text-right">Pagado acumulado</th><th className="px-3 py-1.5 text-right">Ritmo del presupuesto</th></tr></thead>
            <tbody className="divide-y divide-bruma">
              {puntos.map((p) => <tr key={p.dia}><td className="px-3 py-1">{fecha(p.fecha, false)}</td><td className="px-3 py-1 text-right">{p.pagado == null ? "—" : dinero(p.pagado, "USD", 0)}</td><td className="px-3 py-1 text-right">{dinero(p.ritmo, "USD", 0)}</td></tr>)}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- cascada (waterfall)
export function Cascada({ pasos }: { pasos: Paso[] }) {
  const [foco, setFoco] = useState<number | null>(null);
  const [tabla, setTabla] = useState(false);
  const W = 1000, H = 300, L = 56, R = 16, T = 28, B = 46;
  const AN = W - L - R, AL = H - T - B;
  const barras = useMemo(() => {
    let corriendo = 0;
    return pasos.map((p) => {
      const desde = p.tipo === "total" || p.tipo === "pagado" ? 0 : corriendo;
      const hasta = p.tipo === "total" || p.tipo === "pagado" ? p.valor : corriendo + p.valor;
      corriendo = p.tipo === "total" ? p.valor : hasta;
      return { ...p, desde, hasta };
    });
  }, [pasos]);
  const facturado = pasos[0]?.valor || 1;
  const max = Math.max(facturado, 1);
  const paso = max > 40000 ? 10000 : max > 12000 ? 5000 : 2000;
  const marcas = Array.from({ length: Math.floor(max / paso) + 1 }, (_, i) => i * paso);
  const banda = AN / Math.max(barras.length, 1);
  const ancho = Math.min(24, banda * 0.5);
  const cx_ = (i: number) => L + banda * i + banda / 2;
  const y = (v: number) => T + AL - (v / max) * AL;
  const sel = foco != null ? barras[foco] : null;
  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-x-5 gap-y-1 text-[12.5px] text-pizarra">
        {([["total", "Total facturado"], ["frenado", "Frenado por reglas"], ["espera", "Espera aprobación"], ["otro", "Rechazado o devuelto"], ["pagado", "Pagado"]] as const)
          .filter(([t]) => barras.some((b) => b.tipo === t))
          .map(([t, n]) => <span key={t} className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm" style={{ background: COLOR_PASO[t] }} />{n}</span>)}
        <button type="button" onClick={() => setTabla(!tabla)} className="ml-auto text-[12.5px] font-medium text-azul hover:underline">{tabla ? "Ocultar datos" : "Ver datos"}</button>
      </div>
      <div className="overflow-x-auto"><div className="relative min-w-[640px]">
        <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label={`Cascada: facturado ${dinero(facturado, "USD", 0)}, pagado ${dinero(barras[barras.length - 1]?.valor ?? 0, "USD", 0)}`}>
          {marcas.map((m) => (
            <g key={m}>
              <line x1={L} x2={L + AN} y1={y(m)} y2={y(m)} stroke={GRILLA} />
              <text x={L - 10} y={y(m) + 4} textAnchor="end" fontSize="12" fill={TINTA_2}>{compacto(m)}</text>
            </g>
          ))}
          {barras.map((b, i) => {
            const alto = Math.max(2, Math.abs(y(b.desde) - y(b.hasta)));
            const arriba = Math.min(y(b.desde), y(b.hasta));
            const sig = barras[i + 1];
            const nivel = b.tipo === "total" || b.tipo === "pagado" ? b.valor : b.hasta;
            return (
              <g key={b.clave} onPointerEnter={() => setFoco(i)} onPointerLeave={() => setFoco(null)} onFocus={() => setFoco(i)} onBlur={() => setFoco(null)}
                tabIndex={0} role="img" aria-label={`${b.nombre}: ${dinero(b.valor, "USD", 0)}`} className="outline-none">
                <rect x={cx_(i) - banda / 2} y={T} width={banda} height={AL} fill="transparent" />
                <rect x={cx_(i) - ancho / 2} y={arriba} width={ancho} height={alto} rx="3" fill={COLOR_PASO[b.tipo]}
                  opacity={foco == null || foco === i ? 1 : 0.55} />
                {sig && sig.tipo !== "pagado" && (
                  <line x1={cx_(i) + ancho / 2} x2={cx_(i + 1) - ancho / 2} y1={y(nivel)} y2={y(nivel)} stroke={TINTA_2} strokeWidth="1" strokeDasharray="2 3" />
                )}
                <text x={cx_(i)} y={arriba - 7} textAnchor="middle" fontSize="12.5" fontWeight="600" fill={TINTA}>
                  {b.valor < 0 ? "−" : ""}{compacto(Math.abs(b.valor))}
                </text>
                <text x={cx_(i)} y={H - 24} textAnchor="middle" fontSize="12" fill={TINTA_2}>{b.nombre}</text>
                <text x={cx_(i)} y={H - 9} textAnchor="middle" fontSize="11" fill={TINTA_2}>{numero((Math.abs(b.valor) / facturado) * 100, 0)} %</text>
              </g>
            );
          })}
        </svg>
        {sel && (
          <div className="pointer-events-none absolute top-1 z-10 min-w-[180px] rounded-md border border-bruma bg-white px-3 py-2 text-[12.5px] shadow-lg"
            style={{ left: `${Math.min(80, Math.max(1, (cx_(foco!) / W) * 100 - 9))}%` }}>
            <p className="font-semibold text-noche num">{dinero(sel.valor, "USD", 0)}</p>
            <p className="text-pizarra">{sel.nombre} · {numero((Math.abs(sel.valor) / facturado) * 100, 1)} % de lo facturado</p>
          </div>
        )}
      </div></div>
      {tabla && (
        <table className="mt-3 w-full text-[13px] num">
          <thead className="bg-niebla text-left text-[12px] text-pizarra"><tr><th className="px-3 py-1.5">Paso</th><th className="px-3 py-1.5 text-right">USD</th><th className="px-3 py-1.5 text-right">% de lo facturado</th></tr></thead>
          <tbody className="divide-y divide-bruma">
            {barras.map((b) => <tr key={b.clave}><td className="px-3 py-1">{b.nombre}</td><td className="px-3 py-1 text-right">{dinero(b.valor, "USD", 0)}</td><td className="px-3 py-1 text-right">{numero((Math.abs(b.valor) / facturado) * 100, 1)} %</td></tr>)}
          </tbody>
        </table>
      )}
    </div>
  );
}
