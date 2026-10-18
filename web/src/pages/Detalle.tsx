import { useCallback, useState } from "react";
import { ArrowLeft, Ban, Banknote, Check, ChevronDown, CircleCheck, FileDown, KeyRound, PenLine, RefreshCw, ScanText, Send, ShieldCheck, Wallet } from "lucide-react";
import { api, avisarCambio, dinero, fecha, numero, puede, useApi, useCambios, type FacturaDetalle, type Regla, type Usuario } from "../api";
import {
  Aviso, Boton, Campo, Cargando, claseEntrada, cx, Dato, EstadoChip, Hash, LineaTiempo, Panel, resumenReglas, Sello, TiraReglas,
  useToast, Validaciones, Vacio,
} from "../ui";
import { CANALES } from "./Facturas";
import { ChipResultado, PagarModal } from "./Pagos";

export const METODO: Record<string, string> = {
  xml_fiscal: "XML fiscal, lectura exacta sin IA", referencia: "Extracción verificada (modo demo, sin IA)", ia: "IA con visión (Claude)",
  ocr: "OCR local (Tesseract), sin IA", texto_pdf: "Texto del PDF, sin IA", texto: "Texto del chat o correo, sin IA",
  simulador: "Carga de prueba (sin IA)", rechazado: "Archivo rechazado por seguridad",
};

export default function Detalle({ id, usuario }: { id: string; usuario: Usuario }) {
  const { datos: f, cargando, error, recargar } = useApi<FacturaDetalle>(`/facturas/${id}`, [id]);
  const rec = useCallback(() => recargar(), [recargar]);
  useCambios(rec);
  if (cargando && !f) return <Cargando filas={6} />;
  if (error || !f) return <Vacio titulo="No encontramos esa factura" texto={error ?? ""} accion={<a className="font-semibold text-azul" href="#/facturas">Volver a facturas</a>} />;
  const ext = f.extraccion ?? {};
  const C = CANALES[f.canal] ?? CANALES.pdf;
  const [primera, ...resto] = f.motivo.split(/(?<=\.)\s+(?=[A-ZÁÉÍÓÚ«])/);

  return (
    <div className="space-y-6">
      <div>
        <a href="#/facturas" className="inline-flex items-center gap-1.5 text-[13px] font-semibold text-pizarra hover:text-noche"><ArrowLeft className="h-4 w-4" /> Facturas</a>
        <div className="mt-3 flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="font-mono text-[13px] text-pizarra">{f.id} · {f.numero ?? "sin número"}</p>
            <h1 className="mt-1 text-[22px] font-semibold leading-tight tracking-tight sm:text-[24px]">{f.beneficiario}</h1>
            <p className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] text-pizarra">
              <span className="inline-flex items-center gap-1.5"><C.i className="h-4 w-4" />{C.t}</span>
              <span>Recibida {fecha(f.recibida_en)}</span>
              <span>{METODO[ext.metodo_lectura] ?? f.modelo}</span>
            </p>
          </div>
          <div className="text-left sm:text-right">
            <p className="text-[24px] font-semibold tracking-tight num">{dinero(f.monto, f.moneda ?? "USD")}</p>
            {f.moneda !== "USD" && f.monto_usd != null && <p className="text-[13px] text-pizarra num">≈ {dinero(f.monto_usd)}</p>}
            <EstadoChip estado={f.estado} className="mt-2" />
          </div>
        </div>
      </div>

      {/* El porqué, en una sola vista */}
      <section className={cx("rounded-lg border p-5 sm:p-6", f.decision === "pagar" ? "border-menta/40 bg-menta-s/60" : f.decision === "frenar" ? "border-coral/40 bg-coral-s/60" : "border-ambar/50 bg-ambar-s/70")}>
        <div className="flex flex-col gap-5 sm:flex-row sm:items-start">
          <Sello decision={f.estado === "rechazada" ? "frenar" : f.decision} className="self-start" />
          <div className="min-w-0 flex-1">
            <p className="text-[17px] font-semibold leading-snug">{primera}</p>
            {resto.length > 0 && <p className="mt-1.5 text-[14px] leading-relaxed text-noche/80">{resto.join(" ")}</p>}
            <div className="mt-4 flex flex-wrap items-center gap-3">
              <TiraReglas reglas={f.reglas} grande />
              <span className="text-[13px] text-pizarra">{resumenReglas(f.reglas)} · reglas v{f.version_reglas}</span>
            </div>
          </div>
        </div>
      </section>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,0.85fr)]">
        <div className="min-w-0 space-y-6">
          {f.estado === "pendiente" && <Decidir f={f} usuario={usuario} alTerminar={recargar} />}
          {f.estado === "aprobada" && <ListaParaPagar f={f} usuario={usuario} alTerminar={recargar} />}
          {f.pago_detalle && <PanelPago f={f} usuario={usuario} alCambiar={recargar} />}
          <PanelReglas reglas={f.reglas} />
          <Panel titulo="Validaciones del documento" subtitulo="Dígitos de verificación, identificadores fiscales y QR, sin IA">
            <Validaciones lista={ext.validaciones ?? []} />
          </Panel>
          <PanelDatos ext={ext} />
          {f.aprobaciones.length > 0 && (
            <Panel titulo="Decisiones humanas" subtitulo="Cada firma es HMAC-SHA256 sobre el monto, la cuenta y la huella del documento">
              <ul className="space-y-3">
                {f.aprobaciones.map((a, i) => (
                  <li key={i} className="flex gap-3">
                    <span className={cx("mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full", a.accion === "aprobar" ? "bg-menta-s text-menta-t" : "bg-coral-s text-coral-t")}>
                      {a.accion === "aprobar" ? <Check className="h-4 w-4" /> : <Ban className="h-4 w-4" />}
                    </span>
                    <div className="min-w-0 text-[14px]">
                      <p><strong>{a.usuario}</strong> {a.accion === "aprobar" ? `firmó la aprobación ${a.nivel}` : "rechazó"} · <span className="text-pizarra">{fecha(a.creada_en)}</span></p>
                      <p className="text-noche/80">«{a.comentario}»</p>
                      <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-pizarra">Firma <Hash valor={a.firma} />{a.con_mfa ? <span className="inline-flex items-center gap-1 text-menta-t"><ShieldCheck className="h-3.5 w-3.5" /> autorizada con token</span> : <span>sin token (versión anterior)</span>}
                        {Object.keys(a.correcciones ?? {}).length > 0 && <span>· corrigió {Object.entries(a.correcciones).map(([k, v]) => `${k} = ${v}`).join(", ")}</span>}</p>
                    </div>
                  </li>
                ))}
              </ul>
            </Panel>
          )}
          {f.motivo_inicial !== f.motivo && (
            <Panel titulo="Primera decisión de Kauta" subtitulo="Lo que decidió sola al llegar la factura (cuenta para medir autonomía)">
              <p className="text-[14px] text-noche/85">{f.motivo_inicial}</p>
              <TiraReglas reglas={f.reglas_iniciales} className="mt-3" />
            </Panel>
          )}
        </div>

        <div className="min-w-0 space-y-6">
          <Panel titulo="Documento" subtitulo={f.archivo} cuerpo="p-0">
            <VistaDocumento f={f} />
          </Panel>
          <PanelLectura f={f} />
          <Panel titulo="Huella y trazabilidad">
            <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <Dato etiqueta="Huella SHA-256 del documento"><Hash valor={f.hash_documento} /></Dato>
              <Dato etiqueta="Identificador fiscal único">{f.id_fiscal_unico ? <Hash valor={f.id_fiscal_unico} largo={16} /> : "—"}</Dato>
              <Dato etiqueta="Lectura">{f.modelo}</Dato>
              <Dato etiqueta="Cargada por">{f.cargada_por}</Dato>
              <Dato etiqueta="Periodo">{f.periodo}</Dato>
              <Dato etiqueta="Vence">{f.fecha_vencimiento ? fecha(f.fecha_vencimiento, false) : "—"}</Dato>
            </dl>
          </Panel>
        </div>
      </div>
    </div>
  );
}

type EnvioToken = { destino: string; minutos: number; autoriza: string; entrega: string; totp: boolean; codigo_demo?: string | null };

function Decidir({ f, usuario, alTerminar }: { f: FacturaDetalle; usuario: Usuario; alTerminar: () => void }) {
  const [comentario, setComentario] = useState("");
  const [codigo, setCodigo] = useState("");
  const [envio, setEnvio] = useState<EnvioToken | null>(null);
  const [pidiendo, setPidiendo] = useState(false);
  const [corregir, setCorregir] = useState(false);
  const [corr, setCorrBase] = useState<{ monto?: string; moneda?: string; numero_factura?: string; horas?: string }>({});
  const [enviando, setEnviando] = useState<"aprobar" | "rechazar" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const toast = useToast();
  const yaFirme = f.aprobaciones.some((a) => a.usuario === usuario.nombre && a.accion === "aprobar");
  const cargueYo = (f.cargada_por ?? "").split(":").pop()?.trim() === usuario.correo;
  const hechas = f.aprobaciones.filter((a) => a.accion === "aprobar").length;
  const ultima = hechas + 1 >= f.aprobaciones_requeridas;
  const puedeAprobar = puede(usuario, "facturas.aprobar");
  const alto = f.reglas.some((r) => r.id === "R10" && r.estado === "falla");
  const delCeo = alto && !puede(usuario, "facturas.firma_alta");
  const correcciones = () => corregir
    ? Object.fromEntries(Object.entries(corr).filter(([, v]) => v).map(([k, v]) => [k, ["monto", "horas"].includes(k) ? Number(v) : v]))
    : undefined;
  // El token queda ligado a los datos exactos: si cambia una corrección, hace falta uno nuevo
  const setCorr = (c: typeof corr) => { setCorrBase(c); if (envio) { setEnvio(null); setCodigo(""); } };

  const pedirToken = async () => {
    setPidiendo(true);
    setError(null);
    try {
      setEnvio(await api<EnvioToken>(`/facturas/${f.id}/token`, { cuerpo: { correcciones: correcciones() } }));
      setCodigo("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setPidiendo(false);
    }
  };

  const enviar = async (accion: "aprobar" | "rechazar") => {
    setEnviando(accion);
    setError(null);
    try {
      const r = await api<any>(`/facturas/${f.id}/${accion}`, { cuerpo: accion === "aprobar" ? { comentario, correcciones: correcciones(), token: codigo } : { comentario } });
      toast(accion === "rechazar" ? "Factura rechazada" : r.completa ? "Aprobada: queda lista para pagar en «Pagos»" : "Firma registrada: falta otra persona");
      avisarCambio();
      alTerminar();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setEnviando(null);
    }
  };

  return (
    <Panel titulo="Kauta te pregunta" subtitulo={alto ? "Supera el umbral: la aprueba el CEO y después Finanzas la paga" : "Responde para aprobarla; después Finanzas la paga en «Pagos»"}
      className="border-ambar/60 ring-4 ring-ambar-s">
      <ul className="space-y-3">
        {f.preguntas.map((p) => (
          <li key={p.regla} className="rounded-md bg-ambar-s/70 p-3.5">
            <p className="text-[13px] font-semibold text-ambar-t">{p.regla} · {p.titulo}</p>
            <p className="mt-1 text-[14.5px] font-semibold leading-snug">{p.pregunta}</p>
          </li>
        ))}
      </ul>
      {f.plazo && (
        <p className="mt-3 text-[13px] text-pizarra">
          Vence {fecha(f.plazo.vence, false)} ({f.plazo.dias >= 0 ? `en ${f.plazo.dias} días` : `hace ${-f.plazo.dias} días`}).
          {f.plazo.riel && ` El pago sale por ${f.plazo.riel}${f.plazo.dias_riel ? ` y tarda ${f.plazo.dias_riel} día${f.plazo.dias_riel > 1 ? "s" : ""}` : " y llega el mismo día"}.`}
        </p>
      )}
      {!puedeAprobar ? (
        <Aviso tono="info" className="mt-4">Su rol ({usuario.rol_nombre}) no aprueba pagos. Responden Finanzas o el CEO.</Aviso>
      ) : delCeo ? (
        <Aviso tono="info" className="mt-4">Esta factura supera el umbral de aprobación: la aprueba el CEO. Cuando la apruebe, usted la paga desde «Pagos» con su token.</Aviso>
      ) : cargueYo ? (
        <Aviso tono="info" className="mt-4">Usted cargó esta factura: por segregación de funciones, la aprueba otra persona.</Aviso>
      ) : yaFirme ? (
        <Aviso tono="info" className="mt-4">Ya aprobó esta factura.</Aviso>
      ) : (
        <div className="mt-5 space-y-4">
          <Campo etiqueta="Tu respuesta" ayuda="Queda en el registro de auditoría junto con tu firma.">
            <textarea className={claseEntrada + " min-h-[84px]"} value={comentario} onChange={(e) => setComentario(e.target.value)}
              placeholder="Ej.: Llamé al número registrado y el proveedor confirmó el trabajo adicional." />
          </Campo>
          <button type="button" onClick={() => setCorregir(!corregir)} className="inline-flex items-center gap-1.5 text-[13px] font-semibold text-azul">
            <PenLine className="h-4 w-4" /> Corregir un dato antes de aprobar <ChevronDown className={cx("h-4 w-4 transition-transform", corregir && "rotate-180")} />
          </button>
          {corregir && (
            <div className="grid grid-cols-2 gap-3 rounded-md bg-niebla p-3 sm:grid-cols-4">
              <Campo etiqueta="Monto"><input className={claseEntrada} inputMode="decimal" value={corr.monto ?? ""} placeholder={String(f.monto ?? "")} onChange={(e) => setCorr({ ...corr, monto: e.target.value })} /></Campo>
              <Campo etiqueta="Moneda"><input className={claseEntrada} maxLength={3} value={corr.moneda ?? ""} placeholder={f.moneda ?? ""} onChange={(e) => setCorr({ ...corr, moneda: e.target.value.toUpperCase() })} /></Campo>
              <Campo etiqueta="Número"><input className={claseEntrada} value={corr.numero_factura ?? ""} placeholder={f.numero ?? ""} onChange={(e) => setCorr({ ...corr, numero_factura: e.target.value })} /></Campo>
              <Campo etiqueta="Horas"><input className={claseEntrada} inputMode="decimal" value={corr.horas ?? ""} placeholder={String(f.extraccion?.horas ?? "")} onChange={(e) => setCorr({ ...corr, horas: e.target.value })} /></Campo>
            </div>
          )}
          {f.riel_pago_nombre && (
            <p className="flex flex-wrap items-center gap-2 text-[13.5px]"><Wallet className="h-4 w-4 text-azul" /> Forma de pago: <b>{f.riel_pago_nombre}</b>
              <span className="text-pizarra">· aprobar no paga: después Finanzas la paga con su token{(f as any).paypal_modo === "sandbox" ? " (sandbox de PayPal real)" : " (PayPal simulado)"}</span></p>
          )}
          <div className="rounded-md border border-bruma bg-niebla p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="flex items-center gap-2 text-[14px] font-semibold"><KeyRound className="h-4 w-4 text-azul" /> Token de autorización</p>
                <p className="mt-0.5 text-[13px] text-pizarra">
                  Cada aprobación se confirma con un código de 6 dígitos válido solo para esta factura, este monto y esta cuenta.
                  {usuario.mfa_activo && " También sirve el código de su app autenticadora."}
                </p>
              </div>
              <Boton icono={<Send className="h-4 w-4" />} cargando={pidiendo} onClick={pedirToken}>{envio ? "Enviar otro token" : "Enviar token a mi correo"}</Boton>
            </div>
            {envio && (
              <div className="mt-3 rounded-md border border-azul/20 bg-white px-3 py-2.5 text-[13px]">
                <p>Enviado a <b>{envio.destino}</b> · vence en {envio.minutos} minutos.</p>
                <p className="mt-0.5 text-pizarra">Autoriza: {envio.autoriza}</p>
                {envio.codigo_demo ? (
                  <p className="mt-1.5 rounded bg-menta-s px-2 py-1.5 text-menta-t">Cuenta de ejemplo de la demo, sin buzón real: su código es <b className="num font-mono text-[15px] tracking-[0.25em]">{envio.codigo_demo}</b>. Con una cuenta real llega solo a su correo.</p>
                ) : envio.entrega === "buzon" && (
                  <p className="mt-1 text-ambar-t">Entorno de demostración sin servidor de correo: el mensaje aparece en la terminal donde corre Kauta y en <span className="font-mono">var/correos</span>.</p>
                )}
              </div>
            )}
            {(envio || usuario.mfa_activo) && (
              <Campo etiqueta="Código de 6 dígitos" className="mt-3">
                <input className={claseEntrada + " max-w-[200px] text-center text-[16px] tracking-[0.35em] num"} inputMode="numeric" autoComplete="one-time-code"
                  maxLength={6} value={codigo} onChange={(e) => setCodigo(e.target.value.replace(/\D/g, ""))} aria-label="Token de autorización" />
              </Campo>
            )}
          </div>
          {error && <Aviso tono="error">{error}</Aviso>}
          <div className="flex flex-wrap gap-2">
            <Boton variante="exito" icono={<Check className="h-4 w-4" />} cargando={enviando === "aprobar"} disabled={!comentario.trim() || codigo.length !== 6 || !!enviando} onClick={() => enviar("aprobar")}>
              {ultima ? "Aprobar" : `Firmar aprobación ${hechas + 1} de ${f.aprobaciones_requeridas}`}
            </Boton>
            <Boton variante="peligro" icono={<Ban className="h-4 w-4" />} cargando={enviando === "rechazar"} disabled={!comentario.trim() || !!enviando} onClick={() => enviar("rechazar")}>Rechazar</Boton>
          </div>
          <p className="text-xs text-pizarra">Al aprobar y otra vez al pagar, Kauta revisa las reglas duras (saldo, duplicados, bloqueos y máximo por pago). Ninguna aprobación las salta.</p>
        </div>
      )}
    </Panel>
  );
}

function PanelReglas({ reglas }: { reglas: Regla[] }) {
  const [todas, setTodas] = useState(false);
  const orden = [...reglas].sort((a, b) => (a.estado === "falla" ? 0 : 1) - (b.estado === "falla" ? 0 : 1) || a.id.localeCompare(b.id));
  const mostradas = todas ? orden : orden.slice(0, Math.max(4, orden.filter((r) => r.estado === "falla").length));
  return (
    <Panel titulo="Las 13 reglas" subtitulo="Código determinista: misma factura y mismas reglas, misma decisión" cuerpo="p-0">
      <ul className="divide-y divide-bruma">
        {mostradas.map((r) => (
          <li key={r.id} className="flex gap-3 px-5 py-3">
            <span className={cx("mt-1 h-3 w-3 shrink-0 rounded-[3px]", r.estado === "cumple" ? "bg-menta" : r.estado === "no_aplica" ? "bg-bruma" : r.efecto === "frenar" ? "bg-coral" : "bg-ambar")} />
            <div className="min-w-0 text-[14px]">
              <p><span className="font-mono text-[12px] text-pizarra">{r.id}</span> <strong>{r.nombre}</strong>{" "}
                <span className={cx("text-xs font-semibold", r.estado === "cumple" ? "text-menta-t" : r.estado === "no_aplica" ? "text-pizarra" : r.efecto === "frenar" ? "text-coral-t" : "text-ambar-t")}>
                  {r.estado === "cumple" ? "cumple" : r.estado === "no_aplica" ? "no aplica" : r.efecto === "frenar" ? "falla · frena" : "falla · escala"}</span></p>
              <p className="text-[13px] text-noche/75">{r.detalle}</p>
            </div>
          </li>
        ))}
      </ul>
      {orden.length > mostradas.length || todas ? (
        <button onClick={() => setTodas(!todas)} className="w-full border-t border-bruma px-5 py-3 text-[13px] font-semibold text-azul hover:bg-niebla">
          {todas ? "Ver menos" : `Ver las ${orden.length} reglas`}
        </button>
      ) : null}
    </Panel>
  );
}

const TIPOS_DOC: Record<string, string> = {
  factura: "Factura", cuenta_cobro: "Cuenta de cobro", nota_credito: "Nota crédito (no es un cobro)", nota_debito: "Nota débito",
  recibo_pago: "Recibo o complemento de pago (no es un cobro)", documento_soporte: "Documento soporte",
  otro: "Otro comprobante (no es un cobro)", desconocido: "Tipo no reconocido",
};

function PanelDatos({ ext }: { ext: Record<string, any> }) {
  const conf = ext.confianza ?? {};
  const filas: [string, string, any][] = [
    ["beneficiario", "Beneficiario", ext.beneficiario?.nombre], ["id_fiscal", "Identificación fiscal", ext.beneficiario?.id_fiscal],
    ["numero_factura", "Número", ext.numero_factura], ["moneda", "Moneda", ext.moneda], ["monto", "Total a pagar", ext.monto != null ? dinero(ext.monto, ext.moneda ?? "USD") : null],
    ["fecha_vencimiento", "Vencimiento", ext.fecha_vencimiento],
  ];
  return (
    <Panel titulo="Datos leídos" subtitulo="Con la confianza de la lectura por campo (mínimo 0,85 para pagar sola)">
      <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {filas.map(([k, et, v]) => (
          <div key={k} className="min-w-0">
            <dt className="flex items-center justify-between text-xs text-pizarra"><span>{et}</span>{conf[k] != null && <span className={cx("num", conf[k] < 0.85 ? "font-semibold text-coral-t" : "")}>{Number(conf[k]).toFixed(2).replace(".", ",")}</span>}</dt>
            <dd className="mt-0.5 truncate text-[14px] font-semibold">{v ?? "—"}</dd>
            {conf[k] != null && <div className="mt-1 h-1 rounded-full bg-bruma"><div className={cx("h-full rounded-full", conf[k] < 0.85 ? "bg-coral" : "bg-menta")} style={{ width: `${conf[k] * 100}%` }} /></div>}
          </div>
        ))}
      </dl>
      {(ext.concepto || ext.cuenta_destino || ext.horas || ext.tipo_documento) && (
        <dl className="mt-4 grid grid-cols-1 gap-3 border-t border-bruma pt-4 sm:grid-cols-3">
          <Dato etiqueta="Concepto" className="sm:col-span-2">{ext.concepto ?? "—"}</Dato>
          <Dato etiqueta="Cuenta pedida en la factura">{ext.cuenta_destino ? `···${ext.cuenta_destino}` : "No indica"}</Dato>
          {ext.tipo_documento && <Dato etiqueta="Tipo de documento">{TIPOS_DOC[ext.tipo_documento] ?? ext.tipo_documento}</Dato>}
          {ext.horas != null && <Dato etiqueta="Horas">{ext.horas}</Dato>}
        </dl>
      )}
      {ext.lineas?.some((l: any) => l.precio_unitario != null) ? <Items ext={ext} /> : ext.impuestos?.length > 0 && (
        <p className="mt-4 text-[13px] text-pizarra">Impuestos del XML: {ext.impuestos.map((i: any) => `${i.tipo}${i.tasa != null ? ` ${i.tasa} %` : ""} ${dinero(i.monto, ext.moneda)}`).join(" · ")}</p>
      )}
    </Panel>
  );
}

/** Ítems de la factura con descuento, impuestos, retenciones y anticipo, tal como vienen en el documento. */
function Items({ ext }: { ext: Record<string, any> }) {
  const m = ext.moneda ?? "USD";
  const lineas: any[] = ext.lineas ?? [];
  const tras = (ext.impuestos ?? []).filter((i: any) => !i.retencion);
  const rets = (ext.impuestos ?? []).filter((i: any) => i.retencion);
  const suma = (l: any[]) => l.reduce((a, i) => a + (Number(i.monto) || 0), 0);
  const anticipo = Number(ext.anticipo) || 0;
  const descuento = ext.subtotal != null && ext.total != null ? ext.subtotal + suma(tras) - suma(rets) - anticipo - ext.total : 0;
  const filas: [string, number][] = [
    ["Subtotal", ext.subtotal],
    ...(descuento > 0.005 ? [["Descuento comercial", -descuento] as [string, number]] : []),
    ...tras.filter((i: any) => i.monto).map((i: any) => [`${i.tipo}${i.tasa != null ? ` ${String(i.tasa).replace(".", ",")} %` : ""}`, i.monto] as [string, number]),
    ...rets.map((i: any) => [`${i.tipo}${i.tasa != null ? ` ${String(i.tasa).replace(".", ",")} %` : ""}`, -i.monto] as [string, number]),
    ...(anticipo ? [["Anticipo aplicado", -anticipo] as [string, number]] : []),
  ];
  return (
    <div className="mt-4 border-t border-bruma pt-4">
      <p className="flex flex-wrap items-baseline justify-between gap-2 text-[13px] font-semibold text-noche">
        Ítems de la factura <span className="font-normal text-pizarra">{ext.orden_compra ? `Orden de compra ${ext.orden_compra}` : `${lineas.length} líneas`}</span>
      </p>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full min-w-[560px] text-[13px]">
          <thead><tr className="border-b border-bruma text-left text-[11.5px] uppercase tracking-wider text-pizarra">
            {["Código", "Descripción", "Cant.", "Precio unit.", "Importe"].map((t, i) => <th key={t} className={cx("py-1.5 pr-3 font-semibold", i >= 2 && "text-right")}>{t}</th>)}
          </tr></thead>
          <tbody className="divide-y divide-bruma num">
            {lineas.map((l, i) => (
              <tr key={i} className="align-top">
                <td className="whitespace-nowrap py-1.5 pr-3 font-mono text-[12px] text-pizarra">{l.codigo ?? "—"}</td>
                <td className="py-1.5 pr-3">{l.descripcion}</td>
                <td className="whitespace-nowrap py-1.5 pr-3 text-right">{numero(l.cantidad ?? 1, Number.isInteger(l.cantidad) ? 0 : 2)} {l.unidad && <span className="text-pizarra">{String(l.unidad).replace("_", " ")}</span>}</td>
                <td className="whitespace-nowrap py-1.5 pr-3 text-right">{l.precio_unitario != null ? dinero(l.precio_unitario, m) : "—"}</td>
                <td className="whitespace-nowrap py-1.5 text-right">{l.total != null ? dinero(l.total, m) : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {ext.subtotal != null && (
        <dl className="ml-auto mt-2 max-w-xs space-y-1 text-[13px] num">
          {filas.map(([k, v]) => <div key={k} className="flex justify-between gap-4"><dt className="text-pizarra">{k}</dt><dd>{dinero(v, m)}</dd></div>)}
          <div className="flex justify-between gap-4 border-t border-bruma pt-1 font-semibold"><dt>Total a pagar</dt><dd>{dinero(ext.total ?? ext.monto, m)}</dd></div>
        </dl>
      )}
    </div>
  );
}

function PanelPago({ f, usuario, alCambiar }: { f: FacturaDetalle; usuario: Usuario; alCambiar: () => void }) {
  const p = f.pago_detalle!;
  const [consultando, setConsultando] = useState(false);
  const toast = useToast();
  const consultar = async () => {
    setConsultando(true);
    try {
      const r = await api<any>(`/pagos/${p.id}/paypal`, { cuerpo: {} });
      toast(r.mensaje, r.pago.estado === "devuelto" ? "error" : "exito");
      avisarCambio();
      alCambiar();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setConsultando(false);
    }
  };
  return (
    <Panel titulo={<span className="flex flex-wrap items-center gap-2">Pago {p.id} <ChipResultado resultado={p.resultado} /></span>} subtitulo={`${p.riel_nombre} · ${p.liquidacion}`}
      accion={p.resultado !== "negado" && <a href={`/api/pagos/${p.id}/comprobante`} target="_blank" rel="noopener" className="inline-flex items-center gap-1.5 text-[13px] font-semibold text-azul hover:underline"><FileDown className="h-4 w-4" /> Comprobante</a>}>
      <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Dato etiqueta="Recibe el beneficiario">{dinero(p.monto_destino, p.moneda_destino)}</Dato>
        <Dato etiqueta="Cuenta">{p.cuenta}</Dato>
        <Dato etiqueta="Comisión + cambio">{dinero(p.comision_usd + p.costo_fx_usd)}</Dato>
        <Dato etiqueta="Costo total">{dinero(p.costo_total_usd)}</Dato>
      </dl>
      {p.moneda_destino !== "USD" && <p className="mt-3 text-[13px] text-pizarra">Tasa de referencia {p.tasa_referencia.toLocaleString("es-CO")} {p.moneda_destino}/USD; aplicada {p.tasa_aplicada.toLocaleString("es-CO", { maximumFractionDigits: 4 })} (incluye el diferencial cambiario).</p>}
      {p.paypal && (
        <div className="mt-4 flex flex-wrap items-center gap-3 rounded-md border border-bruma bg-niebla px-3 py-2.5 text-[13px]">
          <span className={cx("rounded-full px-2 py-0.5 text-xs font-semibold", p.paypal.modo === "sandbox" ? "bg-azul-s text-azul-t" : "bg-ambar-s text-ambar-t")}>
            {p.paypal.modo === "sandbox" ? "Sandbox de PayPal" : "PayPal simulado"}</span>
          <span className="min-w-0 flex-1 text-pizarra">{p.paypal.modo === "sandbox" ? `Lote ${p.referencia} · dinero de prueba, sin valor real.` : "Configure el sandbox de PayPal para enviarlo de verdad."}</span>
          {p.paypal.consultable && puede(usuario, "pagos.reintentar") && (
            <Boton icono={<RefreshCw className="h-4 w-4" />} cargando={consultando} onClick={consultar}>Consultar en PayPal</Boton>
          )}
        </div>
      )}
      <div className="mt-5"><LineaTiempo pasos={p.linea_tiempo} /></div>
      {p.motivo_devolucion && p.resultado === "negado" && <Aviso tono="alerta" className="mt-4" titulo="Kauta negó el pago">{p.motivo_devolucion}. No se movió dinero.</Aviso>}
      {p.motivo_devolucion && p.resultado !== "negado" && <Aviso tono="error" className="mt-4" titulo={p.riel === "PAYPAL" ? "PayPal no completó el pago" : "El banco devolvió el pago"}>{p.motivo_devolucion}. Los fondos volvieron a la sub-wallet y nada se pagó dos veces. Reintente desde <a href="#/pagos" className="font-semibold underline">Pagos</a>.</Aviso>}
    </Panel>
  );
}

function VistaDocumento({ f }: { f: FacturaDetalle }) {
  const [fallo, setFallo] = useState(false);
  if (f.tiene_vista && !fallo) {
    return <img src={`/api/facturas/${f.id}/vista`} alt={`Vista previa de ${f.archivo}`} className="block w-full rounded-b-lg" loading="lazy" onError={() => setFallo(true)} />;
  }
  return <pre className="max-h-[560px] overflow-auto whitespace-pre-wrap break-words p-5 font-mono text-[12px] leading-relaxed text-noche/85">{f.texto || "Sin vista previa."}</pre>;
}

/** Aprobada: lista para que Finanzas la pague con su token. */
function ListaParaPagar({ f, usuario, alTerminar }: { f: FacturaDetalle; usuario: Usuario; alTerminar: () => void }) {
  const [abierto, setAbierto] = useState(false);
  const aprobaron = f.aprobaciones.filter((a) => a.accion === "aprobar").map((a) => a.usuario);
  const paga = puede(usuario, "pagos.ejecutar");
  return (
    <Panel titulo="Lista para pagar" subtitulo="Aprobada: falta que Finanzas la pague con su token" className="border-azul/40 ring-4 ring-azul-s">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
        <div className="min-w-0 flex-1 text-[14px]">
          <p className="flex items-center gap-1.5 font-semibold text-menta-t"><CircleCheck className="h-4 w-4" /> Aprobada por {aprobaron.join(" y ") || "—"}</p>
          <p className="mt-1 text-pizarra">Sale por <b className="text-noche">{f.riel_pago_nombre}</b>{(f as any).paypal_modo === "sandbox" ? " al sandbox de PayPal (dinero de prueba, flujo real)" : " (simulado)"}. Antes de pagar, Kauta vuelve a revisar las reglas.</p>
        </div>
        {paga
          ? <Boton variante="primario" icono={<Banknote className="h-4 w-4" />} onClick={() => setAbierto(true)}>Pagar {dinero(f.monto_usd)}</Boton>
          : <span className="text-[13px] text-pizarra">La paga Finanzas desde <a href="#/pagos" className="font-semibold text-azul">Pagos</a>.</span>}
      </div>
      <PagarModal f={abierto ? { ...f, aprobada_por: aprobaron } : null} usuario={usuario}
        onCerrar={(cambio) => { setAbierto(false); if (cambio) alTerminar(); }} />
    </Panel>
  );
}

const CADENA = [
  { k: ["xml_fiscal"], t: "XML fiscal", d: "Lectura exacta del CFDI o la factura DIAN" },
  { k: ["texto_pdf"], t: "Texto del PDF", d: "El PDF trae su texto: se lee exacto" },
  { k: ["ocr"], t: "OCR local", d: "Foto o escaneo: Tesseract en el servidor" },
  { k: ["texto"], t: "Texto del chat o correo", d: "Se quita fecha, hora y mensajes propios" },
  { k: ["referencia", "simulador"], t: "Extracción de la demo", d: "Datos verificados del set de prueba" },
  { k: ["ia"], t: "IA", d: "Solo si hay clave y nada más pudo leerlo" },
];

/** Cómo leyó Kauta este documento: el canal, el lector que usó en la cadena y, si hubo OCR, qué tan seguro estuvo. */
function PanelLectura({ f }: { f: FacturaDetalle }) {
  const ext = f.extraccion ?? {};
  const C = CANALES[f.canal] ?? CANALES.pdf;
  const metodo = ext.metodo_lectura ?? f.metodo_lectura;
  const ocr = ext.ocr as { motor?: string; palabras?: number; confianza_media?: number | null; paginas?: number } | undefined;
  return (
    <Panel titulo="Cómo lo leyó Kauta" subtitulo="La cadena de lectura: el primer lector que sirve gana; la IA va al final"
      accion={<a href="#/lector" className="inline-flex items-center gap-1 text-[13px] font-semibold text-azul hover:underline"><ScanText className="h-4 w-4" /> Probar otro</a>}>
      <p className="flex items-center gap-2 text-[14px]"><C.i className="h-4 w-4 text-azul" /> Llegó por <b>{C.t}</b></p>
      <ol className="mt-3 space-y-1.5">
        {CADENA.map((x) => {
          const usado = x.k.includes(metodo);
          return (
            <li key={x.t} className={cx("flex items-start gap-2.5 rounded-md px-2.5 py-1.5 text-[13px]", usado ? "bg-azul-s" : "")}>
              <span className={cx("mt-0.5 grid h-4 w-4 shrink-0 place-items-center rounded-full", usado ? "bg-azul text-white" : "bg-bruma")}>{usado && <Check className="h-3 w-3" />}</span>
              <span className="min-w-0"><span className={cx("font-semibold", usado ? "text-azul-t" : "text-pizarra")}>{x.t}</span> <span className="text-pizarra">· {x.d}</span></span>
            </li>
          );
        })}
      </ol>
      {ocr?.palabras ? (
        <p className="mt-3 text-[13px] text-pizarra">OCR: {ocr.palabras} palabras{ocr.confianza_media != null && <>, confianza media {Math.round(ocr.confianza_media * 100)} %</>} · {ocr.motor}</p>
      ) : null}
    </Panel>
  );
}
