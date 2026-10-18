import { useEffect, useRef, useState } from "react";
import { Ban, CircleCheck, CircleDashed, FileCode, FileText, Image, Mail, MessageSquare, ScanText, TriangleAlert, Upload } from "lucide-react";
import { api, avisarCambio, dinero, ir, puede, useApi, type Decision, type FacturaResumen, type Regla, type Usuario } from "../api";
import { Aviso, Boton, cx, Encabezado, Panel, Sello, TiraReglas, resumenReglas, useToast } from "../ui";

type Paso = { paso: string; titulo: string; estado: "usado" | "no_aplica" | "fallo" | "dudoso"; detalle: string };
type Palabra = { texto: string; conf: number; linea: string };
type Lectura = {
  nombre: string; canal: string; bytes: number; pasos: Paso[]; como: string | null; texto: string; palabras: Palabra[];
  extraccion: Record<string, any> | null; en_demo: boolean; confianza_minima: number;
  decision: { decision: Decision; motivo: string; beneficiario: string | null; monto_usd: number | null; reglas: Regla[] } | null;
};
type Ejemplo = { nombre: string; canal: string; titulo: string };

const ICONO: Record<string, typeof FileText> = { pdf: FileText, imagen: Image, correo: Mail, chat: MessageSquare, xml: FileCode };
const ESTADO_PASO = {
  usado: { i: CircleCheck, c: "text-menta-t bg-menta-s", t: "Se usó" },
  no_aplica: { i: CircleDashed, c: "text-pizarra bg-niebla", t: "No aplica" },
  fallo: { i: Ban, c: "text-coral-t bg-coral-s", t: "No se pudo" },
  dudoso: { i: TriangleAlert, c: "text-ambar-t bg-ambar-s", t: "Con dudas" },
};
const CAMPOS: [string, string][] = [
  ["beneficiario", "Proveedor"], ["id_fiscal", "Identificación fiscal"], ["numero_factura", "Número"], ["moneda", "Moneda"],
  ["monto", "Total a pagar"], ["fecha_vencimiento", "Vencimiento"],
];

export default function Lector({ usuario }: { usuario: Usuario }) {
  const ejemplos = useApi<Ejemplo[]>("/lectura/ejemplos");
  const [archivo, setArchivo] = useState<File | null>(null);
  const [vista, setVista] = useState<string | null>(null);
  const [leyendo, setLeyendo] = useState(false);
  const [cargando, setCargando] = useState(false);
  const [arrastre, setArrastre] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [r, setR] = useState<Lectura | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const toast = useToast();
  useEffect(() => () => { if (vista) URL.revokeObjectURL(vista); }, [vista]);

  const leer = async (f: File) => {
    setArchivo(f); setR(null); setError(null); setLeyendo(true);
    setVista(f.type.startsWith("image/") ? URL.createObjectURL(f) : null);
    try {
      const fd = new FormData();
      fd.append("archivo", f);
      setR(await api<Lectura>("/lectura/probar", { formulario: fd }));
    } catch (e) { setError((e as Error).message); } finally { setLeyendo(false); }
  };
  const ejemplo = async (e: Ejemplo) => {
    try {
      const res = await fetch(`/api/lectura/ejemplos/${encodeURIComponent(e.nombre)}`, { credentials: "same-origin" });
      if (!res.ok) throw new Error("No se pudo traer el ejemplo.");
      const b = await res.blob();
      leer(new File([b], e.nombre, { type: b.type }));
    } catch (err) { setError((err as Error).message); }
  };
  const cargar = async () => {
    if (!archivo) return;
    setCargando(true);
    try {
      const fd = new FormData();
      fd.append("archivo", archivo);
      const f = await api<FacturaResumen>("/facturas/cargar", { formulario: fd });
      toast(`${f.id} cargada: ${f.estado}`, f.estado === "frenada" ? "error" : "exito");
      avisarCambio();
      ir(`facturas/${f.id}`);
    } catch (e) { toast((e as Error).message, "error"); } finally { setCargando(false); }
  };

  const ext = r?.extraccion;
  const conf = (ext?.confianza ?? {}) as Record<string, number>;
  const minimo = r?.confianza_minima ?? 0.85;
  const valor = (k: string) => {
    if (!ext) return null;
    if (k === "beneficiario") return ext.beneficiario?.nombre;
    if (k === "id_fiscal") return ext.beneficiario?.id_fiscal;
    if (k === "monto") return ext.monto != null ? dinero(ext.monto, ext.moneda ?? "USD") : null;
    return ext[k];
  };
  const confDe = (k: string) => (k === "id_fiscal" ? conf.id_fiscal : conf[k]);
  const lineas = r?.palabras.length ? Object.values(r.palabras.reduce<Record<string, Palabra[]>>((acc, p) => ((acc[p.linea] ??= []).push(p), acc), {})) : [];

  return (
    <div className="space-y-6">
      <Encabezado titulo="Probar la lectura (OCR)"
        texto="Suba una factura tal como llegó (foto, PDF, chat de WhatsApp, correo o XML) y vea paso a paso cómo la lee Kauta y qué haría con ella. No crea la factura ni mueve dinero." />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {[
          { t: "¿Qué es el OCR?", d: "Leer las letras de una foto o de un PDF escaneado. Kauta lo hace en su propio servidor con Tesseract: el documento no sale a internet ni a una IA." },
          { t: "La cadena de lectura", d: "XML fiscal (exacto) → texto que el PDF ya trae → OCR de la imagen → texto del chat o del correo. El primero que sirve gana; la IA, solo si hay clave y nada más pudo leerlo." },
          { t: "Confianza por dato", d: `Cada dato trae una confianza de 0 a 1. Si un dato crítico queda por debajo de ${String(minimo).replace(".", ",")}, Kauta no adivina: le pregunta a una persona (regla R01).` },
        ].map((x) => (
          <div key={x.t} className="rounded-lg border border-bruma bg-white p-4">
            <p className="text-[14px] font-semibold text-noche">{x.t}</p>
            <p className="mt-1 text-[13px] leading-relaxed text-pizarra">{x.d}</p>
          </div>
        ))}
      </div>

      <div onDragOver={(e) => { e.preventDefault(); setArrastre(true); }} onDragLeave={() => setArrastre(false)}
        onDrop={(e) => { e.preventDefault(); setArrastre(false); const f = e.dataTransfer.files?.[0]; if (f) leer(f); }}
        className={cx("flex flex-col items-center gap-3 rounded-lg border-2 border-dashed px-5 py-8 text-center", arrastre ? "border-azul bg-azul-s" : "border-bruma bg-white")}>
        <ScanText className="h-8 w-8 text-azul" />
        <p className="text-[15px] font-semibold">Arrastre aquí una factura o elíjala</p>
        <p className="max-w-xl text-[13px] text-pizarra">PDF, foto (.jpg, .png), chat exportado de WhatsApp (.txt), correo (.eml) o XML fiscal. Máximo 10 MB. Kauta verifica el tipo real por su contenido.</p>
        <Boton variante="primario" icono={<Upload className="h-4 w-4" />} cargando={leyendo} onClick={() => input.current?.click()}>Elegir archivo</Boton>
        <input ref={input} type="file" className="hidden" accept=".pdf,.png,.jpg,.jpeg,.webp,.eml,.txt,.xml"
          onChange={(e) => { const f = e.target.files?.[0]; if (f) leer(f); e.target.value = ""; }} />
        {ejemplos.datos && ejemplos.datos.length > 0 && (
          <div className="mt-2 flex flex-wrap justify-center gap-2">
            <span className="w-full text-xs font-semibold uppercase tracking-wider text-pizarra">O pruebe con un ejemplo</span>
            {ejemplos.datos.map((e) => {
              const I = ICONO[e.canal] ?? FileText;
              return (
                <button key={e.nombre} onClick={() => ejemplo(e)} className="inline-flex items-center gap-1.5 rounded-full bg-niebla px-3 py-1.5 text-[13px] font-medium text-noche ring-1 ring-bruma hover:bg-white">
                  <I className="h-4 w-4 text-azul" /> {e.titulo}
                </button>
              );
            })}
          </div>
        )}
      </div>

      {error && <Aviso tono="error" titulo="No se pudo leer">{error}</Aviso>}
      {leyendo && <Aviso tono="info">Leyendo {archivo?.name}… una foto tarda unos segundos (el OCR corre en el servidor).</Aviso>}

      {r && (
        <>
          <Panel titulo={r.nombre} subtitulo={`${(r.bytes / 1024).toFixed(0)} KB · ${r.como ?? "No se pudo leer sin IA"}`}>
            <ol className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-3">
              {r.pasos.map((p) => {
                const e = ESTADO_PASO[p.estado] ?? ESTADO_PASO.no_aplica;
                return (
                  <li key={p.paso} className={cx("flex gap-3 rounded-md border p-3", p.estado === "usado" ? "border-menta/40" : p.estado === "dudoso" ? "border-ambar/50" : p.estado === "fallo" ? "border-coral/40" : "border-bruma")}>
                    <span className={cx("grid h-7 w-7 shrink-0 place-items-center rounded-full", e.c)}><e.i className="h-4 w-4" /></span>
                    <span className="min-w-0 text-[13px]">
                      <span className="block font-semibold text-noche">{p.titulo} <span className="font-normal text-pizarra">· {e.t}</span></span>
                      <span className="block leading-snug text-pizarra">{p.detalle}</span>
                    </span>
                  </li>
                );
              })}
            </ol>
            {r.en_demo && <Aviso tono="info" className="mt-4">Este archivo es de la demo: si lo carga como factura, Kauta lo reconoce como un cobro que ya llegó (regla R03, duplicado).</Aviso>}
          </Panel>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <Panel titulo="Datos leídos" subtitulo={`Con su confianza de 0 a 1 · la línea marca el mínimo para decidir sola (${String(minimo).replace(".", ",")})`}>
              {!ext ? <p className="text-[14px] text-pizarra">No se pudo leer ningún dato sin IA.</p> : (
                <dl className="space-y-3">
                  {CAMPOS.map(([k, t]) => {
                    const c = confDe(k);
                    const v = valor(k);
                    return (
                      <div key={k}>
                        <dt className="flex items-center justify-between text-xs text-pizarra"><span>{t}</span>
                          {c != null && <span className={cx("num font-semibold", c < minimo ? "text-coral-t" : "text-menta-t")}>{c.toFixed(2).replace(".", ",")}</span>}</dt>
                        <dd className="mt-0.5 truncate text-[14px] font-semibold">{v ?? <span className="font-normal text-pizarra">No se encontró</span>}</dd>
                        {c != null && (
                          <div className="relative mt-1 h-1.5 rounded-full bg-bruma">
                            <div className={cx("h-full rounded-full", c < minimo ? "bg-coral" : "bg-menta")} style={{ width: `${Math.min(1, c) * 100}%` }} />
                            <span className="absolute -top-0.5 h-2.5 w-0.5 bg-noche" style={{ left: `${minimo * 100}%` }} aria-hidden="true" />
                          </div>
                        )}
                      </div>
                    );
                  })}
                  {ext.cuenta_destino && <p className="text-[13px] text-pizarra">Cuenta pedida en el documento: <b className="text-noche">···{ext.cuenta_destino}</b></p>}
                </dl>
              )}
            </Panel>

            <Panel titulo="Qué haría Kauta" subtitulo="Las 13 reglas con los datos leídos y el estado actual de la empresa">
              {!r.decision ? <p className="text-[14px] text-pizarra">Sin datos no hay decisión: Kauta no paga lo que no pudo leer.</p> : (
                <div className="space-y-3">
                  <div className="flex flex-wrap items-center gap-3">
                    <Sello decision={r.decision.decision} />
                    <span className="text-[13px] text-pizarra">{r.decision.beneficiario ?? "Proveedor no registrado"}{r.decision.monto_usd != null && ` · ${dinero(r.decision.monto_usd)}`}</span>
                  </div>
                  <p className="text-[14px] leading-relaxed">{r.decision.motivo}</p>
                  <div className="flex flex-wrap items-center gap-3"><TiraReglas reglas={r.decision.reglas} /><span className="text-xs text-pizarra">{resumenReglas(r.decision.reglas)}</span></div>
                  {puede(usuario, "facturas.cargar")
                    ? <Boton variante="primario" cargando={cargando} icono={<Upload className="h-4 w-4" />} onClick={cargar}>Cargar como factura</Boton>
                    : <p className="text-xs text-pizarra">Cargar facturas le corresponde a Finanzas.</p>}
                </div>
              )}
            </Panel>
          </div>

          <div className={cx("grid grid-cols-1 gap-6", vista && "lg:grid-cols-2")}>
            {vista && (
              <Panel titulo="La imagen" cuerpo="p-0"><img src={vista} alt={`Imagen de ${r.nombre}`} className="block w-full rounded-b-lg" /></Panel>
            )}
            <Panel titulo="Texto reconocido" subtitulo={lineas.length ? "Cada palabra con su confianza: en ámbar las dudosas, en rojo las muy dudosas" : "El texto que Kauta leyó"}>
              {lineas.length ? (
                <>
                  <div className="max-h-[520px] space-y-1 overflow-auto font-mono text-[12.5px] leading-relaxed">
                    {lineas.map((l, i) => (
                      <p key={i}>{l.map((p, j) => (
                        <span key={j} title={`Confianza ${p.conf.toFixed(2)}`}
                          className={cx("mr-1 rounded px-0.5", p.conf < 0.6 ? "bg-coral-s text-coral-t" : p.conf < minimo ? "bg-ambar-s text-ambar-t" : "")}>{p.texto}</span>
                      ))}</p>
                    ))}
                  </div>
                  <p className="mt-3 flex flex-wrap gap-3 text-xs text-pizarra">
                    <span><span className="rounded bg-ambar-s px-1 text-ambar-t">palabra</span> confianza menor a {String(minimo).replace(".", ",")}</span>
                    <span><span className="rounded bg-coral-s px-1 text-coral-t">palabra</span> menor a 0,6</span>
                  </p>
                </>
              ) : <pre className="max-h-[520px] overflow-auto whitespace-pre-wrap break-words font-mono text-[12.5px] leading-relaxed text-noche/85">{r.texto || "Sin texto."}</pre>}
            </Panel>
          </div>
        </>
      )}
    </div>
  );
}
