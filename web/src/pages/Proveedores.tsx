import { useCallback, useState } from "react";
import { BadgeCheck, Ban, CircleHelp, PhoneCall, ShieldAlert } from "lucide-react";
import { api, avisarCambio, dinero, fecha, puede, useApi, useCambios, type CambioCuenta, type Usuario } from "../api";
import { Aviso, Boton, Campo, Cargando, claseEntrada, cx, Encabezado, Modal, Panel, useToast } from "../ui";

const PAISES: Record<string, string> = { CO: "Colombia", MX: "México", AR: "Argentina", US: "EE. UU.", BR: "Brasil" };

export default function Proveedores({ usuario }: { usuario: Usuario }) {
  const p = useApi<any[]>("/proveedores");
  const c = useApi<CambioCuenta[]>("/cambios-cuenta");
  const rec = useCallback(() => { p.recargar(); c.recargar(); }, [p.recargar, c.recargar]);
  useCambios(rec);
  const [verificando, setVerificando] = useState<CambioCuenta | null>(null);
  const pendientes = (c.datos ?? []).filter((x) => x.estado === "pendiente");

  return (
    <div className="space-y-6">
      <Encabezado titulo="Proveedores"
        texto="Los beneficiarios permitidos, con su contrato y la cuenta a la que Kauta les paga. Una cuenta nueva nunca se acepta porque lo diga una factura." />
      {pendientes.length > 0 && (
        <Panel titulo="Cambios de cuenta por verificar" subtitulo="El fraude más común en cuentas por pagar: «cambié de banco, págame aquí»" className="border-coral/40">
          <ul className="space-y-3">
            {pendientes.map((x) => (
              <li key={x.id} className="flex flex-col gap-3 rounded-md bg-coral-s/50 p-4 sm:flex-row sm:items-center">
                <ShieldAlert className="h-6 w-6 shrink-0 text-coral-t" />
                <div className="min-w-0 flex-1 text-[14px]">
                  <p className="font-semibold">{x.beneficiario}: de {x.cuenta_actual} a {x.cuenta_nueva} · {x.banco_nuevo}</p>
                  <p className="text-[13px] text-pizarra">{x.origen} · {x.solicitada_por} · {fecha(x.creada_en)}</p>
                </div>
                {puede(usuario, "cuentas.verificar") ? <Boton icono={<PhoneCall className="h-4 w-4" />} onClick={() => setVerificando(x)}>Verificar</Boton>
                  : <span className="text-[13px] text-pizarra">Verifica Finanzas</span>}
              </li>
            ))}
          </ul>
        </Panel>
      )}

      <Panel titulo={`Beneficiarios (${p.datos?.length ?? "…"})`} cuerpo="p-0">
        {!p.datos ? <div className="p-5"><Cargando /></div> : (
          <ul className="divide-y divide-bruma">
            {p.datos.map((b) => (
              <li key={b.id} className="grid grid-cols-1 gap-3 px-5 py-4 md:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)_minmax(0,1fr)_auto] md:items-center">
                <div className="min-w-0">
                  <p className="flex items-center gap-2 text-[14px] font-semibold">
                    <span className="truncate">{b.nombre}</span>
                    {b.estado === "bloqueado" && <span className="inline-flex items-center gap-1 rounded-full bg-coral-s px-2 py-0.5 text-xs font-semibold text-coral-t"><Ban className="h-3 w-3" />Bloqueado</span>}
                  </p>
                  <p className="flex items-center gap-1.5 text-[13px] text-pizarra">
                    {b.id_valido === true ? <BadgeCheck className="h-4 w-4 text-menta-t" /> : b.id_valido === false ? <ShieldAlert className="h-4 w-4 text-coral-t" /> : <CircleHelp className="h-4 w-4" />}
                    <span title={b.id_valido === true ? "Dígito de verificación correcto" : b.id_valido === null ? "Este tipo de identificación no tiene dígito de verificación" : "Dígito inválido"}>{b.id_fiscal}</span>
                    · {PAISES[b.pais] ?? b.pais}
                  </p>
                </div>
                <div className="text-[13px]">
                  <p className="font-medium">{b.categoria}</p>
                  <p className="text-pizarra">{!b.contrato ? "Sin contrato vigente" : b.contrato.tipo === "fijo_mensual" ? `Fijo mensual ${dinero(b.contrato.monto, b.contrato.moneda)}`
                    : b.contrato.tipo === "orden_compra" ? `Orden de compra ${b.contrato.referencia ?? ""} · ${dinero(b.contrato.monto, b.contrato.moneda)}`
                    : `Por horas ${dinero(b.contrato.tarifa_hora, b.contrato.moneda)}/h`}</p>
                </div>
                <div className="text-[13px]">
                  <p className="font-medium">{b.riel_nombre} · recibe {b.moneda_recepcion}</p>
                  <p className="truncate text-pizarra" title={b.banco}>Cuenta {b.cuenta} · {b.banco.split(" · ")[0]}</p>
                </div>
                <div className="text-left text-[13px] md:text-right">
                  <p className="font-semibold num">{dinero(b.pagado_usd)}</p>
                  <p className="text-pizarra">{b.facturas} factura{b.facturas === 1 ? "" : "s"}</p>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Panel>

      {(c.datos ?? []).some((x) => x.estado !== "pendiente") && (
        <Panel titulo="Historial de cambios de cuenta" cuerpo="p-0">
          <ul className="divide-y divide-bruma">
            {(c.datos ?? []).filter((x) => x.estado !== "pendiente").map((x) => (
              <li key={x.id} className="px-5 py-3 text-[13.5px]">
                <span className={cx("font-semibold", x.estado === "aprobado" ? "text-menta-t" : "text-coral-t")}>{x.estado === "aprobado" ? "Aplicado" : "Rechazado"}</span>
                {" · "}{x.beneficiario}: {x.cuenta_nueva} · verificó {x.verificada_por} ({x.metodo_verificacion}) · {fecha(x.resuelta_en)}
              </li>
            ))}
          </ul>
        </Panel>
      )}
      <Verificar cambio={verificando} onCerrar={() => setVerificando(null)} alTerminar={rec} />
    </div>
  );
}

function Verificar({ cambio, onCerrar, alTerminar }: { cambio: CambioCuenta | null; onCerrar: () => void; alTerminar: () => void }) {
  const [metodo, setMetodo] = useState("Llamada al número registrado del proveedor (no al que viene en el mensaje)");
  const [comentario, setComentario] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);
  const toast = useToast();
  if (!cambio) return null;
  const enviar = async (aprobar: boolean) => {
    setEnviando(true);
    setError(null);
    try {
      const r = await api<any>(`/cambios-cuenta/${cambio.id}/verificar`, { cuerpo: { aprobar, metodo, comentario } });
      toast(r.mensaje + (r.reevaluadas?.length ? ` · Reevaluadas: ${r.reevaluadas.join(", ")}` : ""));
      avisarCambio();
      alTerminar();
      onCerrar();
    } catch (e) { setError((e as Error).message); } finally { setEnviando(false); }
  };
  return (
    <Modal abierto titulo={`Verificar el cambio de cuenta de ${cambio.beneficiario}`} onCerrar={onCerrar}>
      <Aviso tono="alerta" className="mb-4" titulo="Verifica por un canal independiente">Llama al teléfono que ya estaba registrado. Nunca uses el número, correo o enlace que trae la solicitud de cambio.</Aviso>
      <dl className="mb-4 grid grid-cols-2 gap-3 text-[14px]">
        <div><dt className="text-xs text-pizarra">Cuenta actual</dt><dd className="font-semibold">{cambio.cuenta_actual}</dd></div>
        <div><dt className="text-xs text-pizarra">Cuenta pedida</dt><dd className="font-semibold text-coral-t">{cambio.cuenta_nueva}</dd></div>
      </dl>
      <div className="space-y-4">
        <Campo etiqueta="Cómo lo verificaste"><input className={claseEntrada} value={metodo} onChange={(e) => setMetodo(e.target.value)} /></Campo>
        <Campo etiqueta="Comentario (opcional)"><textarea className={claseEntrada} value={comentario} onChange={(e) => setComentario(e.target.value)} /></Campo>
        {error && <Aviso tono="error">{error}</Aviso>}
        <div className="flex flex-wrap justify-end gap-2">
          <Boton variante="peligro" cargando={enviando} onClick={() => enviar(false)}>El proveedor no lo pidió: rechazar</Boton>
          <Boton variante="exito" cargando={enviando} onClick={() => enviar(true)}>Confirmado: aplicar cuenta nueva</Boton>
        </div>
      </div>
    </Modal>
  );
}
