import { useCallback, useEffect, useState } from "react";
import { ArrowRight, Ban, Banknote, CircleCheck, CircleX, Clock, ExternalLink, FileDown, KeyRound, RefreshCw, RotateCcw, Send, ShieldCheck, Zap } from "lucide-react";
import { api, avisarCambio, dinero, fecha, ir, puede, useApi, useCambios, useRuta, type FacturaResumen, type Pago, type Resultado, type Usuario } from "../api";
import { Aviso, Boton, Campo, Cargando, claseEntrada, cx, Encabezado, LineaTiempo, Modal, useToast, Vacio } from "../ui";

type PorPagar = FacturaResumen & { aprobada_por: string[]; riel_nombre: string; aprueba: string };
type PagoFila = Pago & { factura_numero: string | null; factura_estado: string | null; automatico: boolean };
type Negada = FacturaResumen & { negada_por: string };
type Cifra = { pagos: number; usd: number };
type Tablero = {
  umbral_usd: number;
  paypal: { modo: string; receptor: string | null };
  por_pagar: PorPagar[];
  esperan_aprobacion: { facturas: number; usd: number; del_ceo: number };
  resumen: Record<"por_pagar" | Resultado, Cifra> & { facturas_negadas: { facturas: number; usd: number } };
  pagos: PagoFila[];
  facturas_negadas: Negada[];
};
type Pestana = "por_pagar" | Resultado;

/** Cómo terminó un pago, en palabras de negocio. */
export const RESULTADOS: Record<Resultado, { t: string; titulo: string; d: string; i: typeof CircleCheck; c: string; s: string }> = {
  exitoso: { t: "Exitoso", titulo: "Pago exitoso", d: "El dinero llegó al beneficiario", i: CircleCheck, c: "text-menta-t", s: "bg-menta-s" },
  en_proceso: { t: "En proceso", titulo: "Pago en proceso", d: "PayPal lo recibió y lo está procesando", i: Clock, c: "text-ambar-t", s: "bg-ambar-s" },
  fallido: { t: "Fallido", titulo: "Pago fallido", d: "El riel no lo completó y el dinero volvió a la wallet", i: CircleX, c: "text-coral-t", s: "bg-coral-s" },
  negado: { t: "Negado", titulo: "Pago negado", d: "Kauta no movió el dinero: una regla ya no se cumplía", i: Ban, c: "text-noche", s: "bg-bruma" },
};

export function ChipResultado({ resultado, className }: { resultado: Resultado; className?: string }) {
  const r = RESULTADOS[resultado] ?? RESULTADOS.negado;
  return (
    <span className={cx("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold whitespace-nowrap", r.s, r.c, className)}>
      <r.i className="h-3.5 w-3.5" /> {r.t}
    </span>
  );
}

export default function Pagos({ usuario }: { usuario: Usuario }) {
  const t = useApi<Tablero>("/tablero/pagos");
  const rec = useCallback(() => t.recargar(), [t.recargar]);
  useCambios(rec);
  const [pestana, setPestana] = useState<Pestana>("por_pagar");
  const [pagando, setPagando] = useState<PorPagar | null>(null);
  const [partes] = useRuta();
  const toast = useToast();
  if (!t.datos) return t.error ? <Aviso tono="error">{t.error}</Aviso> : <Cargando filas={6} />;
  const d = t.datos;
  const paga = puede(usuario, "pagos.ejecutar");
  const gestiona = puede(usuario, "pagos.reintentar");

  const reintentar = async (p: PagoFila) => {
    try {
      const n = await api<Pago>(`/pagos/${p.id}/reintentar`, { cuerpo: {} });
      toast(`${n.id}: ${RESULTADOS[n.resultado]?.titulo ?? n.estado}`, n.resultado === "exitoso" ? "exito" : n.resultado === "en_proceso" ? "info" : "error");
      avisarCambio();
      rec();
    } catch (e) { toast((e as Error).message, "error"); }
  };
  const cancelar = async (p: PagoFila) => {
    try {
      const r = await api<any>(`/pagos/${p.id}/checkout/cancelar`, { cuerpo: {} });
      toast(r.mensaje, "info");
      avisarCambio();
      rec();
    } catch (e) { toast((e as Error).message, "error"); }
  };
  const consultar = async (p: PagoFila) => {
    try {
      const r = await api<any>(`/pagos/${p.id}/paypal`, { cuerpo: {} });
      toast(r.mensaje, r.pago.estado === "devuelto" ? "error" : "exito");
      avisarCambio();
      rec();
    } catch (e) { toast((e as Error).message, "error"); }
  };

  const tarjetas: { k: Pestana; t: string; d: string; n: number; usd: number; i: typeof CircleCheck; c: string; s: string }[] = [
    { k: "por_pagar", t: "Por pagar", d: "Aprobadas, esperan a Finanzas", n: d.resumen.por_pagar.pagos, usd: d.resumen.por_pagar.usd, i: Banknote, c: "text-azul-t", s: "bg-azul-s" },
    ...(["exitoso", "en_proceso", "fallido", "negado"] as Resultado[]).map((k) => ({
      k, t: RESULTADOS[k].t, d: RESULTADOS[k].d, i: RESULTADOS[k].i, c: RESULTADOS[k].c, s: RESULTADOS[k].s,
      n: d.resumen[k].pagos + (k === "negado" ? d.resumen.facturas_negadas.facturas : 0),
      usd: d.resumen[k].usd + (k === "negado" ? d.resumen.facturas_negadas.usd : 0),
    })),
  ];
  const lista = d.pagos.filter((p) => p.resultado === pestana);

  return (
    <div className="space-y-6">
      <Encabezado titulo="Pagos"
        texto={<>Aprobar y pagar son dos pasos. Aprueba Finanzas hasta {dinero(d.umbral_usd, "USD", 0)} y el CEO por encima; después <b className="text-noche">Finanzas paga con su token</b> y aquí ve cómo terminó cada pago: exitoso, en proceso, fallido o negado.</>} />

      {/* Cómo se paga */}
      <ol className="grid grid-cols-1 gap-2 rounded-lg border border-bruma bg-white p-4 text-[13px] sm:grid-cols-2 lg:grid-cols-4">
        {[
          { n: 1, t: "Llega la factura", d: "Kauta la lee y revisa las 13 reglas. Lo que cumple, lo paga sola." },
          { n: 2, t: "Se aprueba con token", d: `Finanzas hasta ${dinero(d.umbral_usd, "USD", 0)}; el CEO por encima. Queda «por pagar».` },
          { n: 3, t: "Finanzas paga con token", d: "Kauta vuelve a revisar saldo, duplicados y bloqueos, y envía por PayPal." },
          { n: 4, t: "Resultado", d: "Exitoso, en proceso, fallido (el dinero vuelve) o negado (no se movió)." },
        ].map((p, i) => (
          <li key={p.n} className="flex gap-3 rounded-md p-2">
            <span className={cx("grid h-7 w-7 shrink-0 place-items-center rounded-full text-[12px] font-bold", i === 2 ? "bg-azul text-white" : "bg-niebla text-noche")}>{p.n}</span>
            <span className="min-w-0"><span className="block font-semibold text-noche">{p.t}</span><span className="block leading-snug text-pizarra">{p.d}</span></span>
          </li>
        ))}
      </ol>

      {/* Cifras por resultado (también son las pestañas) */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5" role="tablist" aria-label="Pagos por resultado">
        {tarjetas.map((x) => (
          <button key={x.k} role="tab" aria-selected={pestana === x.k} onClick={() => setPestana(x.k)}
            className={cx("rounded-lg border bg-white p-4 text-left transition-shadow hover:shadow-sm", pestana === x.k ? "border-noche ring-2 ring-noche/10" : "border-bruma")}>
            <span className="flex items-center justify-between gap-2">
              <span className="text-[13px] font-semibold text-pizarra">{x.t}</span>
              <span className={cx("grid h-7 w-7 place-items-center rounded-full", x.s, x.c)}><x.i className="h-4 w-4" /></span>
            </span>
            <span className="mt-1 block text-[26px] font-semibold leading-tight tracking-tight num">{x.n}</span>
            <span className="block text-[13px] text-noche num">{dinero(x.usd, "USD", 0)}</span>
            <span className="mt-1 block text-xs leading-snug text-pizarra">{x.d}</span>
          </button>
        ))}
      </div>

      <p className={cx("flex flex-wrap items-center gap-2 rounded-md px-3.5 py-2.5 text-[13px]", d.paypal.modo === "sandbox" ? "bg-azul-s text-azul-t" : "bg-ambar-s text-ambar-t")}>
        <ShieldCheck className="h-4 w-4 shrink-0" />
        {d.paypal.modo === "sandbox"
          ? <>PayPal conectado en modo de pruebas (sandbox): cada pago sale de verdad, con dinero de prueba, a la cuenta {d.paypal.receptor}. Si PayPal responde «sin saldo», cargue saldo de prueba a la cuenta Business del sandbox.</>
          : <>PayPal sin conectar: los pagos se registran simulados. Configure el sandbox en «Wallet y conciliación».</>}
      </p>

      {pestana === "por_pagar" ? (
        <section className="space-y-3">
          {d.por_pagar.length === 0 ? (
            <div className="rounded-lg border border-bruma bg-white">
              <Vacio titulo="No hay facturas listas para pagar" texto="Cuando Finanzas o el CEO aprueban una factura en «Kauta pregunta», aparece aquí para pagarla." />
            </div>
          ) : (
            <ul className="divide-y divide-bruma overflow-hidden rounded-lg border border-bruma bg-white">
              {d.por_pagar.map((f) => (
                <li key={f.id} className="flex flex-col gap-3 px-4 py-4 sm:flex-row sm:items-center sm:px-5">
                  <a href={`#/facturas/${f.id}`} className="min-w-0 flex-1">
                    <span className="block text-[15px] font-semibold text-noche">{f.beneficiario}</span>
                    <span className="block text-[13px] text-pizarra"><span className="font-mono">{f.id}</span> · {f.numero ?? "sin número"} · {f.riel_nombre}{f.fecha_vencimiento && ` · vence ${fecha(f.fecha_vencimiento, false)}`}</span>
                    <span className="mt-1 inline-flex items-center gap-1 text-xs font-medium text-menta-t"><CircleCheck className="h-3.5 w-3.5" /> Aprobada por {f.aprobada_por.join(" y ") || "—"}</span>
                  </a>
                  <span className="text-left sm:text-right">
                    <span className="block text-[17px] font-semibold num">{dinero(f.monto_usd)}</span>
                    {f.moneda && f.moneda !== "USD" && <span className="block text-xs text-pizarra num">{dinero(f.monto, f.moneda)}</span>}
                  </span>
                  {paga
                    ? <Boton variante="primario" icono={<Banknote className="h-4 w-4" />} onClick={() => setPagando(f)} className="sm:w-auto">Pagar</Boton>
                    : <span className="text-xs text-pizarra sm:w-28 sm:text-right">La paga Finanzas con su token</span>}
                </li>
              ))}
            </ul>
          )}
          {d.esperan_aprobacion.facturas > 0 && (
            <Aviso tono="info">
              {d.esperan_aprobacion.facturas} factura{d.esperan_aprobacion.facturas > 1 ? "s" : ""} ({dinero(d.esperan_aprobacion.usd, "USD", 0)}) esperan aprobación en <a href="#/pregunta" className="font-semibold underline">Kauta pregunta</a>
              {d.esperan_aprobacion.del_ceo > 0 && <>; {d.esperan_aprobacion.del_ceo} superan el umbral y las aprueba el CEO</>}. Primero se aprueban; después aparecen aquí para pagarlas.
            </Aviso>
          )}
        </section>
      ) : pestana === "negado" ? (
        <section className="space-y-5">
          <ListaPagos lista={lista} vacio="Ningún pago fue negado al momento de pagar." titulo="Negados al pagar (Kauta revisó otra vez y no movió el dinero)" gestiona={false} />
          <div className="overflow-hidden rounded-lg border border-bruma bg-white">
            <p className="border-b border-bruma px-5 py-3 text-[13.5px] font-semibold">Facturas que no se pagan · {d.facturas_negadas.length}</p>
            <ul className="divide-y divide-bruma">
              {d.facturas_negadas.map((f) => (
                <li key={f.id}>
                  <a href={`#/facturas/${f.id}`} className="flex flex-col gap-1 px-5 py-3 hover:bg-niebla sm:flex-row sm:items-center sm:gap-4">
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[14px] font-semibold">{f.beneficiario}</span>
                      <span className="block truncate text-xs text-pizarra">{f.motivo.split(/(?<=\.)\s/)[0]}</span>
                    </span>
                    <span className="text-xs text-pizarra">{f.estado === "frenada" ? "Frenada por" : "Rechazada por"} <b className="text-noche">{f.negada_por}</b></span>
                    <span className="text-[14px] font-semibold num sm:w-28 sm:text-right">{dinero(f.monto_usd)}</span>
                  </a>
                </li>
              ))}
            </ul>
          </div>
        </section>
      ) : (
        <ListaPagos lista={lista} gestiona={gestiona} paga={paga} onReintentar={reintentar} onConsultar={consultar} onCancelar={cancelar}
          vacio={pestana === "exitoso" ? "Aún no hay pagos exitosos." : pestana === "en_proceso" ? "No hay pagos en proceso." : "Ningún pago ha fallado."} />
      )}

      <PagarModal f={pagando} usuario={usuario} onCerrar={(cambio) => { setPagando(null); if (cambio) rec(); }} />
      {partes[1] === "paypal-simulado" && partes[2] && <PayPalSimulado pid={partes[2]} usuario={usuario} onCerrar={() => { ir("pagos"); rec(); }} />}
      {partes[1]?.startsWith("PAG-") && <ResultadoDeRuta pid={partes[1]} usuario={usuario} onCerrar={() => { ir("pagos"); rec(); }} />}
    </div>
  );
}

/** Al volver de PayPal, Kauta abre aquí el resultado del pago (#/pagos/PAG-…). */
function ResultadoDeRuta({ pid, usuario, onCerrar }: { pid: string; usuario: Usuario; onCerrar: () => void }) {
  const [r, setR] = useState<RespuestaPago | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api<Pago>(`/pagos/${pid}`).then((p) => setR({ resultado: p.resultado, mensaje: RESULTADOS[p.resultado]?.d ?? p.estado, pago: p }))
      .catch((e) => setError((e as Error).message));
  }, [pid]);
  return (
    <Modal abierto titulo="Resultado del pago" onCerrar={onCerrar} ancho="max-w-xl">
      {error ? <Aviso tono="error">{error}</Aviso> : !r ? <Cargando filas={3} /> :
        <ResultadoPago r={r} usuario={usuario} onCerrar={onCerrar} onActualizar={setR} />}
    </Modal>
  );
}

/** Sin credenciales del sandbox, la ventana de PayPal se simula dentro de Kauta para poder probar el flujo completo. */
function PayPalSimulado({ pid, usuario, onCerrar }: { pid: string; usuario: Usuario; onCerrar: () => void }) {
  const [p, setP] = useState<Pago | null>(null);
  const [res, setRes] = useState<RespuestaPago | null>(null);
  const [enviando, setEnviando] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api<Pago>(`/pagos/${pid}`).then(setP).catch((e) => setError((e as Error).message)); }, [pid]);
  const decidir = async (aprobar: boolean) => {
    setEnviando(true);
    try {
      setRes(await api<RespuestaPago>(`/pagos/${pid}/checkout/simulado`, { cuerpo: { aprobar } }));
      avisarCambio();
    } catch (e) { setError((e as Error).message); } finally { setEnviando(false); }
  };
  return (
    <Modal abierto titulo={res ? "Resultado del pago" : "PayPal (simulado)"} onCerrar={onCerrar} ancho="max-w-md">
      {res ? <ResultadoPago r={res} usuario={usuario} onCerrar={onCerrar} onActualizar={setRes} /> : error ? <Aviso tono="error">{error}</Aviso> : !p ? <Cargando filas={3} /> : (
        <div className="space-y-4 text-center">
          <Aviso tono="info" className="text-left">El servidor no tiene credenciales del sandbox de PayPal: esta ventana hace las veces de PayPal para probar el flujo.</Aviso>
          <p className="text-[13px] text-pizarra">Pago a</p>
          <p className="text-[16px] font-semibold">{p.beneficiario}</p>
          <p className="text-[30px] font-semibold tracking-tight num">{dinero(p.monto_destino, p.moneda_destino)}</p>
          <p className="font-mono text-xs text-pizarra">Orden {p.referencia}</p>
          <div className="flex flex-col gap-2">
            <Boton variante="exito" cargando={enviando} onClick={() => decidir(true)}>Aprobar el pago</Boton>
            <Boton variante="peligro" disabled={enviando} onClick={() => decidir(false)}>Rechazar</Boton>
          </div>
        </div>
      )}
    </Modal>
  );
}

function ListaPagos({ lista, vacio, titulo, gestiona, paga = false, onReintentar, onConsultar, onCancelar }: {
  lista: PagoFila[]; vacio: string; titulo?: string; gestiona: boolean; paga?: boolean; onReintentar?: (p: PagoFila) => void;
  onConsultar?: (p: PagoFila) => void; onCancelar?: (p: PagoFila) => void;
}) {
  return (
    <div className="overflow-hidden rounded-lg border border-bruma bg-white">
      {titulo && <p className="border-b border-bruma px-5 py-3 text-[13.5px] font-semibold">{titulo} · {lista.length}</p>}
      {lista.length === 0 ? <Vacio titulo={vacio} /> : (
        <ul className="divide-y divide-bruma">
          {lista.map((p) => (
            <li key={p.id} className="flex flex-col gap-2 px-4 py-3.5 sm:px-5 lg:flex-row lg:items-center lg:gap-4">
              <a href={`#/facturas/${p.factura_id}`} className="min-w-0 flex-1">
                <span className="flex flex-wrap items-center gap-2">
                  <span className="truncate text-[14px] font-semibold">{p.beneficiario}</span>
                  <ChipResultado resultado={p.resultado} />
                </span>
                <span className="block truncate text-xs text-pizarra">
                  <span className="font-mono">{p.id}</span> · factura <span className="font-mono">{p.factura_id}</span> · {p.riel_nombre}
                  {p.paypal && <> · {p.paypal.modo === "sandbox" ? "sandbox real" : "simulado"}</>} · {fecha(p.creado_en)} · {p.automatico ? "lo pagó Kauta sola" : "con aprobación"}
                </span>
                {p.referencia && p.referencia !== "—" && <span className="block truncate text-xs text-pizarra">Referencia {p.referencia}</span>}
                {p.motivo_devolucion && <span className="mt-0.5 block text-xs text-coral-t">{p.motivo_devolucion}</span>}
              </a>
              <span className="flex items-center gap-3 lg:justify-end">
                <span className="text-[14px] font-semibold num">{dinero(p.monto_destino, p.moneda_destino)}</span>
                {p.estado === "reservado" && p.paypal?.enlace && paga && (
                  <a href={p.paypal.enlace} className="inline-flex min-h-9 items-center gap-1.5 rounded-md bg-azul px-3 py-1.5 text-[13px] font-semibold text-white hover:bg-azul/90">
                    <ExternalLink className="h-4 w-4" /> Abrir PayPal
                  </a>
                )}
                {p.estado === "reservado" && paga && <Boton onClick={() => onCancelar?.(p)}>Cancelar</Boton>}
                {p.resultado === "en_proceso" && p.paypal?.consultable && gestiona && (
                  <Boton icono={<RefreshCw className="h-4 w-4" />} onClick={() => onConsultar?.(p)}>Consultar en PayPal</Boton>
                )}
                {p.resultado === "fallido" && p.factura_estado === "devuelta" && gestiona && (
                  <Boton icono={<RotateCcw className="h-4 w-4" />} onClick={() => onReintentar?.(p)}>Reintentar</Boton>
                )}
                {p.resultado !== "negado" && (
                  <a href={`/api/pagos/${p.id}/comprobante`} target="_blank" rel="noopener" className="inline-flex items-center gap-1 text-[13px] font-semibold text-azul hover:underline">
                    <FileDown className="h-4 w-4" /> Comprobante
                  </a>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

type EnvioToken = { destino: string; minutos: number; autoriza: string; entrega: string; totp: boolean; codigo_demo?: string | null };
type RespuestaPago = { resultado: Resultado; mensaje: string; pago: Pago; aprobar_en_paypal?: string | null };
export type FacturaAPagar = { id: string; beneficiario: string; monto: number | null; moneda: string | null; monto_usd: number | null; aprobada_por?: string[]; riel_nombre?: string | null };

/** Pagar una factura aprobada: token de pago al correo, código y el resultado del pago en la misma ventana. */
export function PagarModal({ f, usuario, onCerrar }: { f: FacturaAPagar | null; usuario: Usuario; onCerrar: (cambio: boolean) => void }) {
  const [envio, setEnvio] = useState<EnvioToken | null>(null);
  const [codigo, setCodigo] = useState("");
  const [pidiendo, setPidiendo] = useState(false);
  const [pagando, setPagando] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [res, setRes] = useState<RespuestaPago | null>(null);
  const [metodo, setMetodo] = useState<"ventana" | "directo">("ventana");
  const [abriendo, setAbriendo] = useState(false);
  const cerrar = () => {
    const cambio = !!res;
    setEnvio(null); setCodigo(""); setError(null); setRes(null); setAbriendo(false);
    onCerrar(cambio);
  };
  if (!f) return null;

  const pedir = async () => {
    setPidiendo(true); setError(null);
    try {
      setEnvio(await api<EnvioToken>(`/facturas/${f.id}/pago/token`, { cuerpo: {} }));
      setCodigo("");
    } catch (e) { setError((e as Error).message); } finally { setPidiendo(false); }
  };
  const pagar = async () => {
    setPagando(true); setError(null);
    try {
      const r = await api<RespuestaPago>(`/facturas/${f.id}/pagar`, { cuerpo: { token: codigo, metodo } });
      avisarCambio();
      if (r.aprobar_en_paypal) {
        setAbriendo(true);
        if (r.aprobar_en_paypal.startsWith("/#/")) {     // PayPal simulado: la ventana se abre dentro de Kauta
          onCerrar(true);
          ir(r.aprobar_en_paypal.slice(3));
        } else {
          window.location.href = r.aprobar_en_paypal;   // la ventana real de PayPal (sandbox); al terminar vuelve a Kauta
        }
        return;
      }
      setRes(r);
    } catch (e) { setError((e as Error).message); } finally { setPagando(false); }
  };

  return (
    <Modal abierto={!!f} titulo={res ? "Resultado del pago" : `Pagar ${f.id}`} onCerrar={cerrar} ancho="max-w-xl">
      {res ? <ResultadoPago r={res} onCerrar={cerrar} usuario={usuario} onActualizar={(r) => setRes(r)} /> : (
        <div className="space-y-4">
          <dl className="grid grid-cols-2 gap-3 rounded-md bg-niebla p-4 text-[13.5px]">
            <div className="col-span-2"><dt className="text-xs text-pizarra">Beneficiario</dt><dd className="font-semibold">{f.beneficiario}</dd></div>
            <div><dt className="text-xs text-pizarra">Monto</dt><dd className="text-[17px] font-semibold num">{dinero(f.monto_usd)}</dd>
              {f.moneda && f.moneda !== "USD" && <dd className="text-xs text-pizarra num">Factura: {dinero(f.monto, f.moneda)}</dd>}</div>
            <div><dt className="text-xs text-pizarra">Sale por</dt><dd className="font-semibold">{f.riel_nombre ?? "PayPal"}</dd></div>
            {f.aprobada_por && f.aprobada_por.length > 0 && <div className="col-span-2"><dt className="text-xs text-pizarra">Aprobada por</dt><dd>{f.aprobada_por.join(" y ")}</dd></div>}
          </dl>
          <fieldset className="space-y-2">
            <legend className="mb-1 text-[13px] font-semibold text-noche">Cómo pagar</legend>
            {([
              ["ventana", ExternalLink, "Con la ventana de PayPal", "Kauta abre PayPal: usted entra con la cuenta de pruebas y aprueba o rechaza el pago. Al terminar vuelve aquí con el resultado."],
              ["directo", Zap, "Pago directo (PayPal Payouts)", "Kauta envía el dinero desde la cuenta Business de la empresa, sin abrir PayPal."],
            ] as const).map(([v, I, t, d]) => (
              <label key={v} className={cx("flex cursor-pointer gap-3 rounded-md border p-3", metodo === v ? "border-azul bg-azul-s/50" : "border-bruma")}>
                <input type="radio" name="metodo" className="mt-1" checked={metodo === v} onChange={() => setMetodo(v)} />
                <span className="min-w-0 text-[13px]"><span className="flex items-center gap-1.5 font-semibold text-noche"><I className="h-4 w-4 text-azul" /> {t}</span>
                  <span className="block leading-snug text-pizarra">{d}</span></span>
              </label>
            ))}
          </fieldset>
          <p className="text-[13px] text-pizarra">Antes de mover el dinero, Kauta vuelve a revisar las 13 reglas con los datos de este momento: saldo del periodo, duplicados, proveedor bloqueado y máximo por pago. Si alguna ya no se cumple, el pago queda <b className="text-noche">negado</b> y no se mueve un dólar.</p>
          <div className="rounded-md border border-bruma p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <p className="min-w-0 text-[13px] text-pizarra"><span className="flex items-center gap-2 text-[14px] font-semibold text-noche"><KeyRound className="h-4 w-4 text-azul" /> Token de pago</span>
                Un código de 6 dígitos que autoriza solo este pago: este monto, este riel y este destino.</p>
              <Boton icono={<Send className="h-4 w-4" />} cargando={pidiendo} onClick={pedir}>{envio ? "Enviar otro" : "Enviar token a mi correo"}</Boton>
            </div>
            {envio && (
              <div className="mt-3 rounded-md border border-azul/20 bg-white px-3 py-2.5 text-[13px]">
                <p>Enviado a <b>{envio.destino}</b> · vence en {envio.minutos} minutos.</p>
                <p className="mt-0.5 text-pizarra">Autoriza: {envio.autoriza}</p>
                {envio.codigo_demo ? <p className="mt-1.5 rounded bg-menta-s px-2 py-1.5 text-menta-t">Cuenta de ejemplo de la demo, sin buzón real: su código es <b className="num font-mono text-[15px] tracking-[0.25em]">{envio.codigo_demo}</b>. Con una cuenta real llega solo a su correo.</p>
                  : envio.entrega === "buzon" && <p className="mt-1 text-ambar-t">Demostración sin servidor de correo: el mensaje aparece en la terminal donde corre Kauta y en <span className="font-mono">var/correos</span>.</p>}
              </div>
            )}
            {(envio || usuario.mfa_activo) && (
              <Campo etiqueta="Código de 6 dígitos" className="mt-3">
                <input className={claseEntrada + " max-w-[200px] text-center text-[16px] tracking-[0.35em] num"} inputMode="numeric" autoComplete="one-time-code"
                  maxLength={6} value={codigo} onChange={(e) => setCodigo(e.target.value.replace(/\D/g, ""))} aria-label="Token de pago" />
              </Campo>
            )}
          </div>
          {error && <Aviso tono="error">{error}</Aviso>}
          {abriendo && <Aviso tono="info">Abriendo PayPal… al aprobar o rechazar, PayPal lo devuelve a Kauta con el resultado.</Aviso>}
          <div className="flex flex-wrap justify-end gap-2">
            <Boton onClick={cerrar}>Cancelar</Boton>
            <Boton variante="exito" icono={metodo === "ventana" ? <ExternalLink className="h-4 w-4" /> : <Banknote className="h-4 w-4" />}
              cargando={pagando || abriendo} disabled={codigo.length !== 6 || pagando || abriendo} onClick={pagar}>
              {metodo === "ventana" ? `Ir a PayPal a pagar ${dinero(f.monto_usd)}` : `Pagar ${dinero(f.monto_usd)}`}
            </Boton>
          </div>
        </div>
      )}
    </Modal>
  );
}

/** «Pago exitoso: PayPal confirmó…» bajo el título «Pago exitoso» repetiría lo mismo: se deja solo la explicación. */
const sinTitulo = (m: string) => {
  const t = m.replace(/^Pago (exitoso|en proceso|fallido|negado)[:.]\s*/i, "");
  return t.charAt(0).toUpperCase() + t.slice(1);
};

/** El resultado del pago, grande y claro: qué pasó, por qué y qué sigue. */
export function ResultadoPago({ r, onCerrar, usuario, onActualizar }: { r: RespuestaPago; onCerrar: () => void; usuario: Usuario; onActualizar: (r: RespuestaPago) => void }) {
  const info = RESULTADOS[r.resultado] ?? RESULTADOS.negado;
  const p = r.pago;
  const [consultando, setConsultando] = useState(false);
  const toast = useToast();
  const consultar = async () => {
    setConsultando(true);
    try {
      const x = await api<{ mensaje: string; pago: Pago }>(`/pagos/${p.id}/paypal`, { cuerpo: {} });
      onActualizar({ resultado: x.pago.resultado, mensaje: x.mensaje, pago: x.pago });
      avisarCambio();
    } catch (e) { toast((e as Error).message, "error"); } finally { setConsultando(false); }
  };
  return (
    <div className="space-y-4">
      <div className={cx("flex items-start gap-4 rounded-lg p-4", info.s)}>
        <span className={cx("grid h-12 w-12 shrink-0 place-items-center rounded-full bg-white", info.c)}><info.i className="h-7 w-7" /></span>
        <div className="min-w-0">
          <p className={cx("text-[18px] font-semibold", info.c)}>{info.titulo}</p>
          <p className="text-[13.5px] text-noche/85">{sinTitulo(r.mensaje)}</p>
        </div>
      </div>
      <dl className="grid grid-cols-2 gap-3 text-[13px] sm:grid-cols-4">
        <div><dt className="text-xs text-pizarra">Pago</dt><dd className="font-mono font-semibold">{p.id}</dd></div>
        <div><dt className="text-xs text-pizarra">Monto</dt><dd className="font-semibold num">{dinero(p.monto_destino, p.moneda_destino)}</dd></div>
        <div><dt className="text-xs text-pizarra">Riel</dt><dd>{p.riel_nombre}{p.paypal && <span className="block text-xs text-pizarra">{p.paypal.modo === "sandbox" ? "sandbox real" : "simulado"}</span>}</dd></div>
        <div className="min-w-0"><dt className="text-xs text-pizarra">Referencia</dt><dd className="truncate font-mono">{p.referencia}</dd></div>
      </dl>
      <LineaTiempo pasos={p.linea_tiempo} />
      {r.resultado === "fallido" && <Aviso tono="error" titulo="El dinero volvió a la wallet">Nada se pagó dos veces. Resuelva la causa (por ejemplo, saldo en la cuenta Business del sandbox) y use «Reintentar» en Pagos.</Aviso>}
      {r.resultado === "negado" && <Aviso tono="alerta" titulo="No se movió un dólar">Kauta revisó las reglas otra vez justo antes de pagar y una ya no se cumplía.</Aviso>}
      <div className="flex flex-wrap justify-end gap-2">
        {r.resultado === "en_proceso" && p.paypal?.consultable && puede(usuario, "pagos.reintentar") &&
          <Boton icono={<RefreshCw className="h-4 w-4" />} cargando={consultando} onClick={consultar}>Consultar en PayPal</Boton>}
        <Boton icono={<ArrowRight className="h-4 w-4" />} onClick={() => { onCerrar(); ir(`facturas/${p.factura_id}`); }}>Ver la factura</Boton>
        <Boton variante="primario" onClick={onCerrar}>Listo</Boton>
      </div>
    </div>
  );
}
