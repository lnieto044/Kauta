import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { Check, CircleAlert, CircleCheck, CircleX, Copy, Info, LoaderCircle, X } from "lucide-react";
import type { Decision, Estado, PasoPago, Regla } from "./api";
import { dinero } from "./api";

export const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(" ");

// ---------------------------------------------------------------- marca
/** Isotipo de la marca (igual a assets/icono.svg): las reglas firmes, el brazo menta que paga, el ámbar que escala y el freno coral. */
export function Isotipo({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 512 512" aria-hidden="true">
      <rect width="512" height="512" rx="128" fill="#0B1736" />
      <rect x="124" y="108" width="68" height="296" rx="34" fill="#FFFFFF" />
      <line x1="262" y1="256" x2="384" y2="134" stroke="#16C79A" strokeWidth="66" strokeLinecap="round" />
      <line x1="262" y1="256" x2="384" y2="378" stroke="#FFB547" strokeWidth="66" strokeLinecap="round" />
      <circle cx="262" cy="256" r="50" fill="#FF5C5C" stroke="#0B1736" strokeWidth="16" />
    </svg>
  );
}
export function Logo({ claro = false }: { claro?: boolean }) {
  return (
    <span className="inline-flex items-center gap-2.5">
      <Isotipo size={30} />
      <span className={cx("text-[21px] font-extrabold tracking-[-0.02em]", claro ? "text-white" : "text-noche")}>Kauta</span>
    </span>
  );
}

// ---------------------------------------------------------------- estados
const ESTADOS: Record<Estado, { t: string; c: string }> = {
  pagada: { t: "Pagada", c: "bg-menta-s text-menta-t ring-menta/30" },
  aprobada: { t: "Aprobada · por pagar", c: "bg-azul-s text-azul-t ring-azul/30" },
  pendiente: { t: "Pendiente", c: "bg-ambar-s text-ambar-t ring-ambar/40" },
  frenada: { t: "Frenada", c: "bg-coral-s text-coral-t ring-coral/30" },
  rechazada: { t: "Rechazada", c: "bg-bruma text-pizarra ring-pizarra/20" },
  devuelta: { t: "Pago fallido", c: "bg-white text-coral-t ring-coral/50" },
};
export function EstadoChip({ estado, className }: { estado: Estado; className?: string }) {
  const e = ESTADOS[estado] ?? ESTADOS.rechazada;
  return <span className={cx("inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 whitespace-nowrap", e.c, className)}>
    <span className={cx("h-1.5 w-1.5 rounded-full", estado === "pagada" ? "bg-menta" : estado === "aprobada" ? "bg-azul" : estado === "pendiente" ? "bg-ambar" : estado === "rechazada" ? "bg-pizarra" : "bg-coral")} />
    {e.t}
  </span>;
}
const DECISIONES: Record<Decision, { t: string; c: string }> = {
  pagar: { t: "Pagar", c: "text-menta-t border-menta" },
  escalar: { t: "Escalar", c: "text-ambar-t border-ambar" },
  frenar: { t: "Frenar", c: "text-coral-t border-coral" },
};
export function Sello({ decision, className }: { decision: Decision; className?: string }) {
  const d = DECISIONES[decision];
  return <span className={cx("sello inline-flex items-center rounded-md border-2 px-2.5 py-0.5 text-[12.5px] font-bold uppercase tracking-[0.08em] bg-white", d.c, className)}>{d.t}</span>;
}

// ---------------------------------------------------------------- las 13 reglas
export function colorRegla(r: Regla) {
  if (r.estado === "cumple") return "bg-menta";
  if (r.estado === "no_aplica") return "bg-bruma";
  return r.efecto === "frenar" ? "bg-coral" : "bg-ambar";
}
/** «12 cumplen · 1 falla · 1 no aplica», con singular y plural correctos. */
export function resumenReglas(reglas: Regla[]) {
  const n = (estado: Regla["estado"]) => reglas.filter((r) => r.estado === estado).length;
  const c = (k: number, uno: string, varios: string) => `${k} ${k === 1 ? uno : varios}`;
  const partes = [c(n("cumple"), "cumple", "cumplen"), c(n("falla"), "falla", "fallan")];
  if (n("no_aplica")) partes.push(c(n("no_aplica"), "no aplica", "no aplican"));
  return partes.join(" · ");
}
export function TiraReglas({ reglas, grande = false, animar = false, className }: { reglas: Regla[]; grande?: boolean; animar?: boolean; className?: string }) {
  const orden = [...reglas].sort((a, b) => a.id.localeCompare(b.id));
  return (
    <span className={cx("inline-flex items-end", grande ? "gap-1" : "gap-[2px]", className)} role="img"
      aria-label={`Reglas: ${resumenReglas(orden)}`}>
      {orden.map((r, i) => (
        <span key={r.id} title={`${r.id} · ${r.nombre}: ${r.estado === "cumple" ? "cumple" : r.estado === "falla" ? (r.efecto === "frenar" ? "falla (frena)" : "falla (escala)") : "no aplica"}`}
          className={cx(colorRegla(r), grande ? "h-7 w-[18px] rounded-[4px]" : "h-3.5 w-[5px] rounded-[1.5px]", animar && "celda-animada")}
          style={animar ? { animationDelay: `${i * 85}ms` } : undefined} />
      ))}
    </span>
  );
}

// ---------------------------------------------------------------- contenedores
export function Panel({ titulo, subtitulo, accion, children, className, cuerpo = "p-5" }: { titulo?: ReactNode; subtitulo?: ReactNode; accion?: ReactNode; children: ReactNode; className?: string; cuerpo?: string }) {
  return (
    <section className={cx("rounded-lg border border-bruma bg-white shadow-[0_1px_2px_rgba(11,23,54,0.05)]", className)}>
      {(titulo || accion) && (
        <header className="flex flex-wrap items-center justify-between gap-3 border-b border-bruma px-5 py-3.5">
          <div className="min-w-0">
            {titulo && <h2 className="text-[14px] font-semibold text-noche">{titulo}</h2>}
            {subtitulo && <p className="mt-0.5 text-[12.5px] text-pizarra">{subtitulo}</p>}
          </div>
          {accion}
        </header>
      )}
      <div className={cuerpo}>{children}</div>
    </section>
  );
}
export function Encabezado({ titulo, texto, accion }: { titulo: string; texto?: ReactNode; accion?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4 border-b border-bruma pb-5">
      <div className="max-w-3xl">
        <h1 className="text-[20px] font-semibold leading-tight tracking-tight text-noche sm:text-[22px]">{titulo}</h1>
        {texto && <p className="mt-1 text-[14px] text-pizarra">{texto}</p>}
      </div>
      {accion && <div className="flex flex-wrap gap-2">{accion}</div>}
    </div>
  );
}

// ---------------------------------------------------------------- controles
type Variante = "primario" | "secundario" | "peligro" | "fantasma" | "exito";
const VARIANTES: Record<Variante, string> = {
  primario: "bg-azul text-white shadow-sm hover:bg-azul-t disabled:bg-azul/50",
  secundario: "bg-white text-noche shadow-sm ring-1 ring-pizarra/25 hover:bg-niebla hover:ring-pizarra/40",
  peligro: "bg-white text-coral-t ring-1 ring-coral/40 hover:bg-coral-s",
  fantasma: "text-pizarra hover:text-noche hover:bg-bruma/60",
  exito: "bg-menta-t text-white hover:bg-[#086349]",
};
export function Boton({ variante = "secundario", icono, cargando, children, className, ...p }: React.ButtonHTMLAttributes<HTMLButtonElement> & { variante?: Variante; icono?: ReactNode; cargando?: boolean }) {
  return (
    <button {...p} disabled={p.disabled || cargando}
      className={cx("inline-flex min-h-9 items-center justify-center gap-2 rounded-md px-3.5 py-1.5 text-[13.5px] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-60", VARIANTES[variante], className)}>
      {cargando ? <LoaderCircle className="h-4 w-4 animate-spin" /> : icono}
      {children}
    </button>
  );
}
export function Campo({ etiqueta, ayuda, children, className }: { etiqueta: string; ayuda?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <label className={cx("block", className)}>
      <span className="mb-1.5 block text-[13px] font-semibold text-noche">{etiqueta}</span>
      {children}
      {ayuda && <span className="mt-1 block text-xs text-pizarra">{ayuda}</span>}
    </label>
  );
}
export const claseEntrada = "w-full min-h-10 rounded-md border border-pizarra/25 bg-white px-3 py-2 text-[14px] text-noche shadow-sm placeholder:text-pizarra/70 focus:border-azul focus:outline-none focus:ring-2 focus:ring-azul/20";

// ---------------------------------------------------------------- avisos
export function Aviso({ tono = "info", titulo, children, className }: { tono?: "info" | "exito" | "alerta" | "error"; titulo?: ReactNode; children?: ReactNode; className?: string }) {
  const t = {
    info: ["border border-azul/15 bg-azul-s text-azul-t", <Info key="i" className="h-5 w-5 shrink-0" />],
    exito: ["border border-menta/20 bg-menta-s text-menta-t", <CircleCheck key="i" className="h-5 w-5 shrink-0" />],
    alerta: ["border border-ambar/25 bg-ambar-s text-ambar-t", <CircleAlert key="i" className="h-5 w-5 shrink-0" />],
    error: ["border border-coral/20 bg-coral-s text-coral-t", <CircleX key="i" className="h-5 w-5 shrink-0" />],
  }[tono];
  return (
    <div role={tono === "error" ? "alert" : "status"} className={cx("flex gap-3 rounded-md px-4 py-3 text-[13.5px]", t[0] as string, className)}>
      {t[1]}
      <div className="min-w-0">
        {titulo && <p className="font-semibold">{titulo}</p>}
        {children && <div className={cx(titulo ? "mt-0.5" : "", "text-noche/85")}>{children}</div>}
      </div>
    </div>
  );
}
export function Vacio({ titulo, texto, accion }: { titulo: string; texto?: ReactNode; accion?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-14 text-center">
      <TiraReglas grande reglas={Array.from({ length: 13 }, (_, i) => ({ id: `R${String(i + 1).padStart(2, "0")}`, nombre: "", efecto: "escalar", estado: "no_aplica", detalle: "" }) as Regla)} />
      <p className="mt-5 text-[16px] font-semibold">{titulo}</p>
      {texto && <p className="mt-1 max-w-md text-[14px] text-pizarra">{texto}</p>}
      {accion && <div className="mt-5">{accion}</div>}
    </div>
  );
}
export function Cargando({ filas = 4 }: { filas?: number }) {
  return (
    <div className="space-y-3" aria-busy="true" aria-label="Cargando">
      {Array.from({ length: filas }).map((_, i) => (
        <div key={i} className="h-12 animate-pulse rounded-md bg-bruma/60" />
      ))}
    </div>
  );
}

// ---------------------------------------------------------------- notificaciones
type Toast = { id: number; texto: ReactNode; tono: "exito" | "error" | "info" };
const CtxToast = createContext<(texto: ReactNode, tono?: Toast["tono"]) => void>(() => {});
export const useToast = () => useContext(CtxToast);
export function ProveedorToast({ children }: { children: ReactNode }) {
  const [lista, setLista] = useState<Toast[]>([]);
  const sec = useRef(0);
  const empujar = useCallback((texto: ReactNode, tono: Toast["tono"] = "exito") => {
    const id = ++sec.current;
    setLista((l) => [...l, { id, texto, tono }]);
    setTimeout(() => setLista((l) => l.filter((t) => t.id !== id)), tono === "error" ? 7000 : 4200);
  }, []);
  return (
    <CtxToast.Provider value={empujar}>
      {children}
      <div className="pointer-events-none fixed inset-x-0 bottom-20 z-[60] flex flex-col items-center gap-2 px-4 lg:bottom-6 lg:items-end lg:pr-6" aria-live="polite">
        {lista.map((t) => (
          <div key={t.id} className={cx("paso-animado pointer-events-auto flex max-w-md items-start gap-2.5 rounded-md px-4 py-3 text-[14px] font-medium text-white shadow-lg",
            t.tono === "error" ? "bg-coral-t" : t.tono === "info" ? "bg-noche" : "bg-menta-t")}>
            {t.tono === "error" ? <CircleX className="mt-0.5 h-4 w-4 shrink-0" /> : <Check className="mt-0.5 h-4 w-4 shrink-0" />}
            <span>{t.texto}</span>
          </div>
        ))}
      </div>
    </CtxToast.Provider>
  );
}

// ---------------------------------------------------------------- ventana modal
export function Modal({ abierto, titulo, onCerrar, children, ancho = "max-w-lg" }: { abierto: boolean; titulo: string; onCerrar: () => void; children: ReactNode; ancho?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const cerrar = useRef(onCerrar);
  cerrar.current = onCerrar;
  // El foco va al primer control solo al abrir: si dependiera de onCerrar (una función nueva en cada render),
  // cada tecla devolvería el foco al primer campo y no se podría escribir, por ejemplo, el token de pago.
  useEffect(() => {
    if (!abierto) return;
    const f = (e: KeyboardEvent) => e.key === "Escape" && cerrar.current();
    document.addEventListener("keydown", f);
    ref.current?.querySelector<HTMLElement>("input,textarea,button,select")?.focus();
    return () => document.removeEventListener("keydown", f);
  }, [abierto]);
  if (!abierto) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-noche/50 p-0 sm:items-center sm:p-6" onMouseDown={(e) => e.target === e.currentTarget && onCerrar()}>
      <div ref={ref} role="dialog" aria-modal="true" aria-label={titulo} className={cx("paso-animado max-h-[92vh] w-full overflow-y-auto rounded-t-lg bg-white shadow-2xl sm:rounded-lg", ancho)}>
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-bruma bg-white px-5 py-4">
          <h2 className="text-[15px] font-semibold">{titulo}</h2>
          <button onClick={onCerrar} className="rounded-lg p-1.5 text-pizarra hover:bg-niebla" aria-label="Cerrar"><X className="h-5 w-5" /></button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- datos pequeños
export function Hash({ valor, largo = 12 }: { valor: string | null | undefined; largo?: number }) {
  const toast = useToast();
  if (!valor) return <span className="text-pizarra">—</span>;
  return (
    <button type="button" title={valor} onClick={() => navigator.clipboard?.writeText(valor).then(() => toast("Copiado al portapapeles", "info"))}
      className="inline-flex items-center gap-1 rounded-md bg-niebla px-1.5 py-0.5 font-mono text-[12px] text-noche/80 hover:bg-bruma">
      {valor.length > largo ? valor.slice(0, largo) + "…" : valor}
      <Copy className="h-3 w-3 text-pizarra" />
    </button>
  );
}
export function Dato({ etiqueta, children, className }: { etiqueta: string; children: ReactNode; className?: string }) {
  return (
    <div className={cx("min-w-0", className)}>
      <dt className="text-xs text-pizarra">{etiqueta}</dt>
      <dd className="mt-0.5 truncate text-[14px] font-semibold">{children}</dd>
    </div>
  );
}
export function BarraPresupuesto({ usado, total, className }: { usado: number; total: number; className?: string }) {
  const pct = total > 0 ? Math.min(100, (usado / total) * 100) : 0;
  return (
    <div className={className}>
      <div className="h-2.5 overflow-hidden rounded-full bg-bruma">
        <div className={cx("h-full rounded-full transition-[width] duration-700", pct > 90 ? "bg-coral" : pct > 70 ? "bg-ambar" : "bg-menta")} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- pago: línea de tiempo
export function LineaTiempo({ pasos, animar = false, moneda }: { pasos: PasoPago[]; animar?: boolean; moneda?: string }) {
  const [visibles, setVisibles] = useState(animar ? 0 : pasos.length);
  useEffect(() => {
    if (!animar) {
      setVisibles(pasos.length);
      return;
    }
    setVisibles(0);
    const timers = pasos.map((p, i) => setTimeout(() => setVisibles(i + 1), 500 + Math.min(p.t, 6) * 650 + i * 120));
    return () => timers.forEach(clearTimeout);
  }, [pasos, animar]);
  return (
    <ol className="relative space-y-4 pl-7">
      <span className="absolute left-[9px] top-2 bottom-2 w-0.5 bg-bruma" aria-hidden="true" />
      {pasos.map((p, i) => {
        const hecho = i < visibles;
        const malo = p.paso === "devuelto" || p.paso === "negado";
        return (
          <li key={p.paso} className={cx("relative", hecho ? "paso-animado" : "opacity-35")}>
            <span className={cx("absolute -left-7 top-0.5 flex h-[20px] w-[20px] items-center justify-center rounded-full ring-4 ring-white",
              !hecho ? "bg-bruma" : malo ? "bg-coral" : p.paso === "liquidado" ? "bg-menta" : p.paso === "en_proceso" ? "bg-ambar" : "bg-noche")}>
              {hecho && (malo ? <X className="h-3 w-3 text-white" /> : <Check className="h-3 w-3 text-white" />)}
            </span>
            <p className="text-[14px] font-semibold">{p.titulo}</p>
            <p className="break-words text-[13px] text-pizarra">{p.detalle}</p>
          </li>
        );
      })}
    </ol>
  );
}

// ---------------------------------------------------------------- gráfico del saldo del periodo
export function GraficoSaldo({ serie, presupuesto, compacto = false }: { serie: { id: string; estado: Estado; acumulado: number }[]; presupuesto: number; compacto?: boolean }) {
  const W = compacto ? 360 : 1080, H = compacto ? 230 : 250, X0 = compacto ? 40 : 52, Y0 = 18, AN = W - X0 - 12, AL = H - Y0 - 34;
  const fs = compacto ? 12 : 11.5, r = compacto ? 4.6 : 4.8, cada = compacto ? Math.ceil(serie.length / 6) : serie.length <= 24 ? 1 : 2;
  const max = Math.max(presupuesto * 1.08, ...serie.map((s) => s.acumulado), 1);
  const x = (i: number) => X0 + (serie.length > 1 ? (i * AN) / (serie.length - 1) : AN / 2);
  const y = (v: number) => Y0 + AL - (v / max) * AL;
  const paso = max > 20000 ? 10000 : 5000;
  const marcas = Array.from({ length: Math.floor(max / paso) + 1 }, (_, i) => i * paso);
  const linea = serie.map((s, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(s.acumulado).toFixed(1)}`).join(" ");
  const color = (e: Estado) => (e === "pagada" ? "#16C79A" : e === "pendiente" ? "#FFB547" : e === "rechazada" ? "#5B6782" : "#FF5C5C");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label="Saldo usado del periodo factura por factura">
      {marcas.map((m) => (
        <g key={m}>
          <line x1={X0} x2={W - 12} y1={y(m)} y2={y(m)} stroke="#E3E8F2" />
          <text x={X0 - 8} y={y(m) + 4} textAnchor="end" fontSize={fs} fill="#5B6782">{m >= 1000 ? `${m / 1000}k` : m}</text>
        </g>
      ))}
      <line x1={X0} x2={W - 12} y1={y(presupuesto)} y2={y(presupuesto)} stroke="#FF5C5C" strokeWidth="1.5" strokeDasharray="6 5" />
      <text x={W - 14} y={y(presupuesto) - 6} textAnchor="end" fontSize={fs} fontWeight="600" fill="#C7302F">Presupuesto {dinero(presupuesto, "USD", 0)}</text>
      <path d={linea} fill="none" stroke="#0B1736" strokeWidth="2.2" strokeLinejoin="round" />
      {serie.map((s, i) => (
        <g key={s.id}>
          <circle cx={x(i)} cy={y(s.acumulado)} r={r} fill={color(s.estado)} stroke="#fff" strokeWidth="2">
            <title>{`${s.id}: ${s.estado} · acumulado ${dinero(s.acumulado)}`}</title>
          </circle>
          {i % cada === 0 && <text x={x(i)} y={H - 12} textAnchor="middle" fontSize={compacto ? 11 : 10} fill="#5B6782">{s.id.replace(/^SIM/, "S")}</text>}
        </g>
      ))}
    </svg>
  );
}

export function Validaciones({ lista }: { lista: { campo: string; valido: boolean | null; detalle: string }[] }) {
  if (!lista?.length) return <p className="text-[13px] text-pizarra">Sin validaciones adicionales para este documento.</p>;
  return (
    <ul className="space-y-2">
      {lista.map((v, i) => (
        <li key={i} className="flex gap-2.5 text-[13.5px]">
          {v.valido === true ? <CircleCheck className="mt-0.5 h-4 w-4 shrink-0 text-menta-t" /> : v.valido === false ? <CircleX className="mt-0.5 h-4 w-4 shrink-0 text-coral-t" /> : <Info className="mt-0.5 h-4 w-4 shrink-0 text-pizarra" />}
          <span className="min-w-0 break-words"><span className="font-semibold">{NOMBRES_VALIDACION[v.campo] ?? v.campo.replace(/_/g, " ")}.</span> {v.detalle}</span>
        </li>
      ))}
    </ul>
  );
}
const NOMBRES_VALIDACION: Record<string, string> = {
  id_fiscal: "Identificación fiscal", cufe: "CUFE (DIAN)", timbre_fiscal: "Timbre fiscal (SAT)", totales: "Totales",
  ambiente: "Ambiente DIAN", cufe_contenedor: "Contenedor DIAN", validacion_dian: "Validación DIAN", receptor: "Receptor",
  qr_total: "QR fiscal: total", qr_emisor: "QR fiscal: emisor", qr_moneda: "QR fiscal: moneda", verificacion_sat: "Verificación SAT",
  metodo_pago: "Método de pago", retenciones: "Retenciones", seguridad: "Seguridad del archivo", numero_contenedor: "Número del contenedor",
};
