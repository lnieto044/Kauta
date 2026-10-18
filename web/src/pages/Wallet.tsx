import { useCallback, useState } from "react";
import { ArrowRight, CircleCheck, CircleX, FileSpreadsheet, Landmark, PlugZap, Plus, RotateCcw, Send } from "lucide-react";
import { api, avisarCambio, dinero, fecha, PERIODO, puede, useApi, useCambios, type Pago, type Usuario } from "../api";
import { Aviso, BarraPresupuesto, Boton, Campo, Cargando, claseEntrada, cx, Encabezado, Modal, Panel, useToast } from "../ui";

const FLUJO = [
  { c: "operativa", t: "Cuenta operativa", d: "Dólares de la empresa" },
  { c: "cxp", t: "Sub-wallet de pagos", d: "Presupuesto del periodo" },
  { c: "reservas", t: "Reservado", d: "Pagos aprobados por salir" },
  { c: "transito", t: "En tránsito", d: "Enviados al riel" },
  { c: "proveedores", t: "Pagado", d: "Llegó al beneficiario" },
];

export default function WalletPagina({ usuario }: { usuario: Usuario }) {
  const w = useApi<any>("/wallet");
  const pagos = useApi<Pago[]>("/pagos");
  const rieles = useApi<any[]>("/rieles");
  const rec = useCallback(() => { w.recargar(); pagos.recargar(); }, [w.recargar, pagos.recargar]);
  useCambios(rec);
  const [fondear, setFondear] = useState(false);
  const [monto, setMonto] = useState("25000");
  const toast = useToast();
  if (!w.datos) return <Cargando filas={5} />;
  const d = w.datos;
  const saldo = (c: string) => d.cuentas.find((x: any) => x.codigo === c)?.saldo ?? 0;

  const hacerFondeo = async () => {
    try {
      await api("/wallet/fondear", { cuerpo: { monto: Number(monto) } });
      toast(`Depósito simulado de ${dinero(Number(monto))} a la cuenta operativa`);
      setFondear(false);
      avisarCambio();
      rec();
    } catch (e) { toast((e as Error).message, "error"); }
  };
  const reintentar = async (id: string) => {
    try {
      const p = await api<Pago>(`/pagos/${id}/reintentar`, { cuerpo: {} });
      toast(`Reintento ${p.id}: ${p.estado}`);
      avisarCambio();
      rec();
    } catch (e) { toast((e as Error).message, "error"); }
  };

  return (
    <div className="space-y-6">
      <Encabezado titulo="Wallet y conciliación"
        texto={<>La cuenta en dólares desde la que se paga a proveedores por PayPal. Cada movimiento es un asiento de doble partida: nada aparece ni desaparece. Para pagar una factura aprobada, vaya a <a href="#/pagos" className="font-semibold text-azul">Pagos</a>.</>}
        accion={<>
          {puede(usuario, "reportes.ver") && (
            <a href="/api/conciliacion" download className="inline-flex min-h-9 items-center justify-center gap-2 rounded-md bg-white px-3.5 py-1.5 text-[13.5px] font-medium text-noche shadow-sm ring-1 ring-pizarra/25 hover:bg-niebla">
              <FileSpreadsheet className="h-4 w-4" /> Descargar conciliación (Excel)
            </a>
          )}
          {puede(usuario, "wallet.fondear") && <Boton icono={<Plus className="h-4 w-4" />} onClick={() => setFondear(true)}>Depositar en la cuenta operativa</Boton>}
        </>} />

      {/* El recorrido del dinero */}
      <section className="rounded-lg bg-noche p-5 text-white sm:p-6">
        <div className="flex flex-col gap-3 md:flex-row md:items-stretch">
          {FLUJO.map((x, i) => (
            <div key={x.c} className="flex items-center gap-3 md:flex-1 md:flex-col md:items-stretch">
              <div className={cx("flex-1 rounded-lg p-4", x.c === "cxp" ? "bg-white text-noche" : "bg-noche-2")}>
                <p className={cx("text-[13px] font-semibold", x.c === "cxp" ? "text-pizarra" : "text-[#AAB6D3]")}>{x.t}</p>
                <p className="mt-1 text-[20px] font-semibold tracking-tight num">{dinero(saldo(x.c), "USD", 0)}</p>
                <p className={cx("text-xs", x.c === "cxp" ? "text-pizarra" : "text-[#8D9AC0]")}>{x.d}</p>
              </div>
              {i < FLUJO.length - 1 && <ArrowRight className="hidden h-5 w-5 shrink-0 self-center text-[#5D6F9E] md:block md:rotate-0" />}
            </div>
          ))}
        </div>
        <p className="mt-4 flex items-center gap-2 text-[13px] text-[#C9D2E8]">
          {d.libro.ok ? <CircleCheck className="h-4 w-4 text-menta" /> : <CircleX className="h-4 w-4 text-coral" />} {d.libro.mensaje}
          <span className="hidden sm:inline">· Comisiones y cambio pagados: {dinero(d.costos)}</span>
        </p>
      </section>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)]">
        <Panel titulo="Presupuesto por periodo" subtitulo="La sub-wallet se fondea una vez por mes; es el saldo que vigila la regla R12">
          <ul className="space-y-5">
            {d.periodos.map((p: any) => (
              <li key={p.periodo}>
                <div className="flex items-baseline justify-between gap-3 text-[14px]">
                  <span className="font-semibold first-letter:uppercase">{PERIODO(p.periodo)}</span>
                  <span className="num text-pizarra">{dinero(p.pagado, "USD", 0)} de {dinero(p.presupuesto, "USD", 0)}</span>
                </div>
                <BarraPresupuesto usado={p.pagado} total={p.presupuesto} className="mt-2" />
                <p className="mt-1 text-xs text-pizarra num">Disponible: {dinero(p.disponible)}</p>
              </li>
            ))}
          </ul>
        </Panel>
        <Panel titulo="Pagos" subtitulo="Cada orden va firmada y con clave de idempotencia" cuerpo="p-0">
          {!pagos.datos ? <div className="p-5"><Cargando /></div> : (
            <ul className="divide-y divide-bruma">
              {pagos.datos.slice(0, 14).map((p) => (
                <li key={p.id} className="flex items-center gap-3 px-5 py-3">
                  <span className={cx("flex h-8 w-8 shrink-0 items-center justify-center rounded-full", p.estado === "devuelto" ? "bg-coral-s text-coral-t" : p.estado === "negado" ? "bg-bruma text-noche" : p.estado === "enviado" ? "bg-ambar-s text-ambar-t" : "bg-menta-s text-menta-t")}>
                    {p.estado === "devuelto" ? <RotateCcw className="h-4 w-4" /> : <Landmark className="h-4 w-4" />}
                  </span>
                  <a href={`#/facturas/${p.factura_id}`} className="min-w-0 flex-1">
                    <span className="block truncate text-[14px] font-semibold">{p.beneficiario}</span>
                    <span className="block truncate text-xs text-pizarra">{p.id} · {p.riel_nombre} · {fecha(p.creado_en)}</span>
                  </a>
                  <span className="text-right">
                    <span className="block text-[14px] font-semibold num">{dinero(p.monto_destino, p.moneda_destino)}</span>
                    {p.estado === "devuelto" && puede(usuario, "pagos.reintentar")
                      ? <button onClick={() => reintentar(p.id)} className="text-xs font-semibold text-azul hover:underline">Reintentar</button>
                      : <span className={cx("block text-xs", p.estado === "devuelto" ? "text-coral-t font-semibold" : "text-pizarra")}>{({ liquidado: "Exitoso", devuelto: "Fallido", negado: "Negado", enviado: "En proceso", reservado: "En proceso" } as Record<string, string>)[p.estado] ?? p.estado}</span>}
                  </span>
                </li>
              ))}
              {pagos.datos.length === 0 && <li className="px-5 py-8 text-center text-[14px] text-pizarra">Aún no hay pagos.</li>}
            </ul>
          )}
        </Panel>
      </div>

      <Panel titulo="Libro mayor" subtitulo="Últimos asientos: débitos a la izquierda, créditos a la derecha, siempre iguales" cuerpo="p-0">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-[13px]">
            <thead className="bg-niebla/60 text-left text-xs text-pizarra">
              <tr><th className="px-5 py-2.5 font-semibold">#</th><th className="px-2 py-2.5 font-semibold">Asiento</th><th className="px-2 py-2.5 font-semibold">Débito</th><th className="px-2 py-2.5 font-semibold">Crédito</th><th className="px-5 py-2.5 text-right font-semibold">Monto</th></tr>
            </thead>
            <tbody className="divide-y divide-bruma">
              {d.asientos.slice(0, 18).map((a: any) => {
                const deb = a.movimientos.find((m: any) => m.debito > 0);
                const cre = a.movimientos.find((m: any) => m.credito > 0);
                return (
                  <tr key={a.id}>
                    <td className="px-5 py-2.5 font-mono text-pizarra">{a.id}</td>
                    <td className="max-w-[380px] px-2 py-2.5"><span className="block truncate">{a.descripcion}</span><span className="text-xs text-pizarra">{a.tipo} · {fecha(a.fecha)}</span></td>
                    <td className="px-2 py-2.5 font-medium">{deb?.cuenta}</td>
                    <td className="px-2 py-2.5 font-medium">{cre?.cuenta}</td>
                    <td className="px-5 py-2.5 text-right font-semibold num">{dinero(deb?.debito ?? 0)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Panel>

      <PanelPayPal rieles={rieles.datos} usuario={usuario} />

      <Modal abierto={fondear} titulo="Depositar en la cuenta operativa" onCerrar={() => setFondear(false)}>
        <Aviso tono="info" className="mb-4">Es un depósito simulado: solo crea un asiento en el libro mayor.</Aviso>
        <Campo etiqueta="Monto en USD"><input className={claseEntrada + " num"} inputMode="decimal" value={monto} onChange={(e) => setMonto(e.target.value)} /></Campo>
        <div className="mt-5 flex justify-end gap-2"><Boton onClick={() => setFondear(false)}>Cancelar</Boton><Boton variante="primario" onClick={hacerFondeo}>Depositar</Boton></div>
      </Modal>
    </div>
  );
}

/** Qué pasa con un pago por PayPal en este servidor: sandbox de verdad o simulado. */
export function AvisoPayPal({ riel }: { riel?: { modo?: string; receptor?: string | null } }) {
  if (riel?.modo === "sandbox") {
    return <span className="mt-1 block text-xs text-menta-t">Sandbox de PayPal conectado: el pago de prueba llega a la cuenta {riel.receptor}.</span>;
  }
  return <span className="mt-1 block text-xs text-ambar-t">PayPal sin conectar: los pagos se registran simulados hasta agregar las credenciales del sandbox.</span>;
}

type EstadoPayPal = {
  modo: string; client_id: boolean; secret: boolean; receptor: boolean; receptor_valido: boolean;
  receptor_enmascarado: string | null; archivo_env: boolean;
};

function PanelPayPal({ rieles, usuario }: { rieles: any[] | null; usuario: Usuario }) {
  const est = useApi<EstadoPayPal>("/paypal/estado");
  const [probando, setProbando] = useState(false);
  const [resultado, setResultado] = useState<{ ok: boolean; mensaje: string } | null>(null);
  const pp = rieles?.find((r) => r.codigo === "PAYPAL");
  const e = est.datos;
  if (!pp || !e) return <Panel titulo="Forma de pago: PayPal"><Cargando filas={2} /></Panel>;
  const conectado = pp.modo === "sandbox";
  const receptorBusiness = !!e.receptor_enmascarado?.toLowerCase().endsWith("@business.example.com");
  const probar = async () => {
    setProbando(true);
    try {
      const r = await api<{ ok: boolean; mensaje: string }>("/paypal/probar", { cuerpo: {} });
      setResultado({ ok: r.ok, mensaje: r.mensaje });
      est.recargar();
    } catch (err) {
      setResultado({ ok: false, mensaje: (err as Error).message });
    } finally {
      setProbando(false);
    }
  };
  const pasos: { ok: boolean | null; titulo: string; detalle: string }[] = [
    { ok: e.archivo_env, titulo: "Archivo .env en la carpeta del proyecto", detalle: "Copie .env.example como .env (nunca se sube ni entra en el zip)." },
    { ok: e.client_id, titulo: "Client ID de la app del sandbox", detalle: "KAUTA_PAYPAL_CLIENT_ID · developer.paypal.com → Apps & Credentials → Sandbox → su app." },
    { ok: e.secret, titulo: "Secret de la misma app", detalle: "KAUTA_PAYPAL_SECRET · se guarda solo en .env; Kauta nunca lo muestra." },
    { ok: e.receptor ? e.receptor_valido && !receptorBusiness : false,
      titulo: e.receptor ? `Receptor: ${e.receptor_enmascarado}` : "Receptor: correo de la cuenta Personal del sandbox",
      detalle: receptorBusiness ? "Ese correo es de la cuenta Business (la que envía). Use la Personal: Testing Tools → Sandbox Accounts → sb-…@personal.example.com."
        : "KAUTA_PAYPAL_RECEPTOR · Testing Tools → Sandbox Accounts → la cuenta de tipo Personal (sb-…@personal.example.com)." },
    { ok: resultado ? resultado.ok : null, titulo: "Conexión probada", detalle: "Reinicie Kauta después de editar .env y pulse «Probar conexión»: no crea pagos." },
  ];
  return (
    <Panel titulo="Forma de pago: PayPal" subtitulo="Finanzas paga las facturas aprobadas con la ventana de PayPal (Checkout) o con el pago directo (Payouts), en modo de pruebas: dinero de prueba, flujo real"
      accion={<span className={cx("rounded-full px-2.5 py-1 text-xs font-semibold", conectado ? "bg-menta-s text-menta-t" : "bg-ambar-s text-ambar-t")}>{conectado ? "Sandbox conectado" : "Sin conectar · pagos simulados"}</span>}>
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
        <div>
          <p className="text-[13.5px] font-semibold text-noche">Qué falta para pagar en el sandbox</p>
          <ol className="mt-3 space-y-2.5">
            {pasos.map((p, i) => (
              <li key={p.titulo} className="flex gap-3">
                <span className={cx("grid h-6 w-6 shrink-0 place-items-center rounded-full text-[12px] font-semibold",
                  p.ok === true ? "bg-menta-s text-menta-t" : p.ok === false ? "bg-ambar-s text-ambar-t" : "bg-niebla text-pizarra")}>
                  {p.ok === true ? <CircleCheck className="h-4 w-4" /> : i + 1}
                </span>
                <span className="min-w-0 text-[13px]">
                  <span className={cx("block font-medium", p.ok === true ? "text-noche" : "text-noche")}>{p.titulo}</span>
                  <span className="block leading-snug text-pizarra">{p.detalle}</span>
                </span>
              </li>
            ))}
          </ol>
          {puede(usuario, "integraciones.probar") && (
            <div className="mt-4 flex flex-wrap items-center gap-3">
              <Boton variante="primario" icono={<PlugZap className="h-4 w-4" />} cargando={probando} onClick={probar}>Probar conexión</Boton>
              <span className="text-[12.5px] text-pizarra">Pide un token al sandbox; no mueve dinero.</span>
            </div>
          )}
          {resultado && <Aviso tono={resultado.ok ? "exito" : "alerta"} className="mt-3">{resultado.mensaje}</Aviso>}
        </div>
        <div className="space-y-4 rounded-lg bg-niebla p-4 text-[13px]">
          <div>
            <p className="flex items-center gap-2 font-semibold text-noche"><Send className="h-4 w-4 text-azul" /> Cómo sale cada pago</p>
            <p className="mt-1 text-pizarra">Aprobada la factura, Finanzas la paga en «Pagos» con su token. <b className="text-noche">Ventana de PayPal:</b> Kauta reserva el dinero, abre PayPal, usted aprueba o rechaza y al volver Kauta cobra la orden. <b className="text-noche">Pago directo:</b> Kauta envía el lote por Payouts desde la cuenta Business. Si PayPal lo rechaza, el dinero vuelve a la wallet.</p>
          </div>
          <div>
            <p className="font-semibold text-noche">Dónde llega y cómo verlo</p>
            <p className="mt-1 text-pizarra">{conectado ? <>A la cuenta personal de pruebas <b className="text-noche">{pp.receptor}</b>. Entre a sandbox.paypal.com con esa cuenta para ver el dinero llegar.</> : "A la cuenta Personal del sandbox. Con su contraseña entra a sandbox.paypal.com y ve cada pago recibido."}</p>
          </div>
          <div>
            <p className="font-semibold text-noche">Costo estimado</p>
            <p className="mt-1 text-pizarra">2 % del pago con tope de USD 20 (estimación; el sandbox no cobra). Se registra como comisión en el libro mayor.</p>
          </div>
        </div>
      </div>
    </Panel>
  );
}
