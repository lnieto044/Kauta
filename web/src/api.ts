import { useCallback, useEffect, useRef, useState } from "react";

// ---------------------------------------------------------------- tipos
export type Estado = "pagada" | "aprobada" | "frenada" | "pendiente" | "rechazada" | "devuelta";
export type Resultado = "exitoso" | "en_proceso" | "fallido" | "negado";
export type Decision = "pagar" | "frenar" | "escalar";

export interface Regla {
  id: string;
  nombre: string;
  efecto: "frenar" | "escalar";
  estado: "cumple" | "falla" | "no_aplica";
  detalle: string;
}
export interface Validacion {
  campo: string;
  valido: boolean | null;
  detalle: string;
}
export interface PasoPago {
  paso: string;
  titulo: string;
  detalle: string;
  t: number;
}
export interface Pago {
  id: string;
  factura_id: string;
  beneficiario: string;
  riel: string;
  riel_nombre: string;
  liquidacion: string;
  monto_factura: number;
  moneda_factura: string;
  monto_usd: number;
  moneda_destino: string;
  monto_destino: number;
  tasa_referencia: number;
  tasa_aplicada: number;
  comision_usd: number;
  costo_fx_usd: number;
  costo_total_usd: number;
  cuenta: string;
  titular: string | null;
  referencia: string;
  estado: "reservado" | "enviado" | "liquidado" | "devuelto" | "negado";
  resultado: Resultado;
  firma: string;
  clave_idempotencia: string;
  linea_tiempo: PasoPago[];
  paypal: { modo: "sandbox" | "simulado"; consultable: boolean; metodo?: "ventana" | "checkout" | "directo"; enlace?: string | null } | null;
  motivo_devolucion: string | null;
  creado_en: string;
  liquidado_en: string | null;
}
export interface FacturaResumen {
  id: string;
  archivo: string;
  canal: string;
  origen: string;
  beneficiario: string;
  beneficiario_id: string | null;
  numero: string | null;
  monto: number | null;
  moneda: string | null;
  monto_usd: number | null;
  periodo: string;
  decision: Decision;
  decision_inicial: Decision;
  estado: Estado;
  motivo: string;
  regla: string;
  regla_inicial: string;
  recibida_en: string;
  metodo_lectura: string;
  fecha_vencimiento: string | null;
  aprobaciones_requeridas: number;
  aprobaciones_hechas: number;
  aprobada_por: string[];
  pago: { id: string; estado: string; resultado: Resultado; riel: string } | null;
}
export interface Pregunta {
  regla: string;
  titulo: string;
  pregunta: string;
  detalle: string;
}
export interface Plazo {
  vence: string;
  dias: number;
  dias_riel: number;
  riel: string | null;
}
export interface FacturaDetalle extends FacturaResumen {
  extraccion: Record<string, any>;
  reglas: Regla[];
  reglas_iniciales: Regla[];
  motivo_inicial: string;
  texto: string;
  modelo: string;
  hash_documento: string;
  hashes: string[];
  version_reglas: number;
  cargada_por: string;
  id_fiscal_unico: string | null;
  tiene_vista: boolean;
  aprobaciones: { usuario: string; nivel: number; accion: string; comentario: string; correcciones: Record<string, any>; firma: string; con_mfa: boolean; creada_en: string }[];
  preguntas: Pregunta[];
  plazo: Plazo | null;
  pago_detalle: Pago | null;
  cambio_cuenta: CambioCuenta | null;
  riel_pago: string | null;
  riel_pago_nombre: string | null;
}
export interface CambioCuenta {
  id: number;
  beneficiario_id: string;
  beneficiario: string;
  factura_id: string | null;
  banco_nuevo: string;
  cuenta_nueva: string;
  cuenta_actual: string | null;
  origen: string;
  estado: "pendiente" | "aprobado" | "rechazado";
  solicitada_por: string;
  verificada_por: string | null;
  metodo_verificacion: string | null;
  creada_en: string;
  resuelta_en: string | null;
}
export interface Usuario {
  id: number;
  correo: string;
  nombre: string;
  cargo: string;
  rol: string;
  rol_nombre: string;
  mfa_activo: boolean;
  permisos: string[];
  csrf: string | null;
}

// ---------------------------------------------------------------- cliente
let csrf: string | null = null;
let alExpirar: () => void = () => {};
export const fijarCsrf = (t: string | null) => (csrf = t);
export const alPerderSesion = (fn: () => void) => (alExpirar = fn);

export class ErrorApi extends Error {
  constructor(public estado: number, mensaje: string, public datos?: any) {
    super(mensaje);
  }
}

export async function api<T = any>(ruta: string, opciones: { metodo?: string; cuerpo?: unknown; formulario?: FormData } = {}): Promise<T> {
  const metodo = opciones.metodo ?? (opciones.cuerpo !== undefined || opciones.formulario ? "POST" : "GET");
  const cabeceras: Record<string, string> = { Accept: "application/json" };
  if (opciones.cuerpo !== undefined) cabeceras["Content-Type"] = "application/json";
  if (metodo !== "GET" && csrf) cabeceras["X-CSRF-Token"] = csrf;
  const r = await fetch("/api" + ruta, {
    method: metodo,
    headers: cabeceras,
    credentials: "same-origin",
    body: opciones.formulario ?? (opciones.cuerpo !== undefined ? JSON.stringify(opciones.cuerpo) : undefined),
  });
  const tipo = r.headers.get("content-type") ?? "";
  const datos = tipo.includes("json") ? await r.json().catch(() => ({})) : null;
  if (!r.ok) {
    if (r.status === 401 && !ruta.startsWith("/auth/login")) alExpirar();
    const detalle = typeof datos?.detail === "string" ? datos.detail : `Error ${r.status}`;
    throw new ErrorApi(r.status, detalle, datos);
  }
  return datos as T;
}

export function useApi<T = any>(ruta: string | null, deps: unknown[] = []) {
  const [datos, setDatos] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [cargando, setCargando] = useState(true);
  const vivo = useRef(true);
  const cargar = useCallback(async () => {
    if (!ruta) return;
    setCargando(true);
    try {
      const d = await api<T>(ruta);
      if (vivo.current) {
        setDatos(d);
        setError(null);
      }
    } catch (e) {
      if (vivo.current) setError((e as Error).message);
    } finally {
      if (vivo.current) setCargando(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ruta, ...deps]);
  useEffect(() => {
    vivo.current = true;
    cargar();
    return () => {
      vivo.current = false;
    };
  }, [cargar]);
  return { datos, error, cargando, recargar: cargar, setDatos };
}

// ---------------------------------------------------------------- navegación por hash
export function useRuta(): [string[], (r: string) => void] {
  const leer = () => (window.location.hash.replace(/^#\/?/, "") || "resumen").split("/").filter(Boolean);
  const [partes, setPartes] = useState<string[]>(leer());
  useEffect(() => {
    const f = () => {
      setPartes(leer());
      window.scrollTo({ top: 0 });
    };
    window.addEventListener("hashchange", f);
    return () => window.removeEventListener("hashchange", f);
  }, []);
  return [partes, (r: string) => (window.location.hash = "/" + r)];
}
export const ir = (r: string) => (window.location.hash = "/" + r);

// ---------------------------------------------------------------- formato
const nf = (dec: number) => new Intl.NumberFormat("es-CO", { minimumFractionDigits: dec, maximumFractionDigits: dec });
export function dinero(v: number | null | undefined, moneda = "USD", dec?: number) {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const d = dec ?? (moneda === "COP" || moneda === "CLP" ? 0 : 2);
  return `${moneda} ${nf(d).format(v)}`;
}
export const numero = (v: number, dec = 0) => nf(dec).format(v);
export function fecha(iso: string | null | undefined, conHora = true) {
  if (!iso) return "—";
  const d = new Date(iso.length === 10 ? iso + "T12:00:00Z" : iso);
  return new Intl.DateTimeFormat("es-CO", {
    day: "numeric",
    month: "short",
    ...(conHora ? { hour: "2-digit", minute: "2-digit" } : { year: "numeric" }),
    timeZone: "America/Bogota",
  }).format(d);
}
export const PERIODO = (p: string) => {
  const [a, m] = p.split("-").map(Number);
  return new Intl.DateTimeFormat("es-CO", { month: "long", year: "numeric", timeZone: "UTC" }).format(new Date(Date.UTC(a, m - 1, 15)));
};
export const puede = (u: Usuario | null, permiso: string) => !!u && u.permisos.includes(permiso);

// ---------------------------------------------------------------- avisos de cambio entre pantallas
export const avisarCambio = () => window.dispatchEvent(new Event("kauta:cambio"));
export function useCambios(fn: () => void) {
  useEffect(() => {
    window.addEventListener("kauta:cambio", fn);
    return () => window.removeEventListener("kauta:cambio", fn);
  }, [fn]);
}
