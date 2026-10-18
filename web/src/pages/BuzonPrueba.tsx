import { useMemo, useState } from "react";
import { ArrowRight, Inbox } from "lucide-react";
import { api, avisarCambio, useApi, type FacturaResumen } from "../api";
import { Aviso, Boton, Cargando, cx, EstadoChip, Modal, useToast } from "../ui";
import { CANALES } from "./Facturas";

type Fila = {
  archivo: string; canal: string; factura_excel: string; emisor: string; moneda: string; total: string; que_trae: string;
  decision_kauta?: string; regla?: string; factura: string | null; estado: FacturaResumen["estado"] | null;
};

/**
 * Las 50 facturas de facturas_de_prueba/ (hechas con el Excel del reto). «Recibir» la hace llegar por el correo de la
 * empresa, como si la enviara el proveedor: así quien prueba la puede aprobar y Kauta le avisa por correo.
 */
export default function BuzonPrueba({ abierto, onCerrar }: { abierto: boolean; onCerrar: () => void }) {
  const lista = useApi<Fila[]>(abierto ? "/buzon/pruebas" : null, [abierto]);
  const [canal, setCanal] = useState("");
  const [recibiendo, setRecibiendo] = useState<string | null>(null);
  const toast = useToast();
  const filas = useMemo(() => (lista.datos ?? []).filter((x) => !canal || x.canal === canal), [lista.datos, canal]);
  const canales = useMemo(() => [...new Set((lista.datos ?? []).map((x) => x.canal))], [lista.datos]);

  const recibir = async (x: Fila) => {
    setRecibiendo(x.archivo);
    try {
      const f = await api<FacturaResumen>(`/buzon/pruebas/${encodeURIComponent(x.archivo)}/recibir`, { cuerpo: {} });
      toast(`${f.id} llegó por ${CANALES[f.canal]?.t ?? f.canal}: ${f.estado === "pagada" ? "Kauta la pagó" : f.estado === "pendiente" ? "Kauta pregunta" : f.estado}`,
        f.estado === "frenada" ? "error" : "exito");
      avisarCambio();
      lista.recargar();
    } catch (e) { toast((e as Error).message, "error"); } finally { setRecibiendo(null); }
  };

  return (
    <Modal abierto={abierto} titulo="Buzón de prueba · 50 facturas del Excel del reto" onCerrar={onCerrar} ancho="max-w-4xl">
      <div className="space-y-4">
        <Aviso tono="info">
          Cada factura llega por el correo de la empresa, como si la enviara el proveedor, por el canal de su archivo (PDF, foto,
          correo, chat o XML). Kauta la lee sin IA, decide y le avisa a quien la revisa con el documento adjunto. Como no la cargó
          usted, la puede aprobar y pagar.
        </Aviso>
        <div className="-mx-1 flex gap-1.5 overflow-x-auto px-1 pb-1">
          {["", ...canales].map((c) => {
            const C = c ? CANALES[c] : null;
            return (
              <button key={c || "todos"} onClick={() => setCanal(c)}
                className={cx("inline-flex shrink-0 items-center gap-1.5 rounded-md px-2.5 py-1 text-[13px] font-medium ring-1",
                  canal === c ? "bg-azul-s text-azul-t ring-azul/40" : "bg-white text-pizarra ring-bruma hover:text-noche")}>
                {C && <C.i className="h-3.5 w-3.5" />}{C ? C.t : "Todos"}
              </button>
            );
          })}
        </div>
        {!lista.datos ? (lista.error ? <Aviso tono="error">{lista.error}</Aviso> : <Cargando filas={5} />) : lista.datos.length === 0 ? (
          <Aviso tono="alerta">No está la carpeta facturas_de_prueba en el servidor. Genérela con: python scripts/generar_pruebas.py</Aviso>
        ) : (
          <ul className="max-h-[60vh] divide-y divide-bruma overflow-y-auto rounded-lg border border-bruma">
            {filas.map((x) => {
              const C = CANALES[x.canal] ?? CANALES.pdf;
              return (
                <li key={x.archivo} className="flex flex-col gap-2 px-4 py-3 sm:flex-row sm:items-center sm:gap-4">
                  <span className="flex min-w-0 flex-1 gap-3">
                    <span className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-full bg-niebla text-azul"><C.i className="h-4 w-4" /></span>
                    <span className="min-w-0">
                      <span className="block truncate text-[14px] font-semibold">{x.archivo.slice(0, 3)} · {x.emisor}</span>
                      <span className="block truncate text-xs text-pizarra">{C.t} · {x.moneda} {Number(x.total).toLocaleString("es-CO", { maximumFractionDigits: 2 })} · {x.factura_excel}</span>
                      <span className="block text-xs text-pizarra">{x.que_trae}</span>
                    </span>
                  </span>
                  {x.factura ? (
                    <a href={`#/facturas/${x.factura}`} onClick={onCerrar} className="inline-flex items-center gap-2 text-[13px] font-semibold text-azul">
                      {x.estado && <EstadoChip estado={x.estado} />} {x.factura} <ArrowRight className="h-3.5 w-3.5" />
                    </a>
                  ) : (
                    <Boton icono={<Inbox className="h-4 w-4" />} cargando={recibiendo === x.archivo} disabled={!!recibiendo} onClick={() => recibir(x)}>Recibir</Boton>
                  )}
                </li>
              );
            })}
          </ul>
        )}
        <p className="text-xs text-pizarra">Montos y datos tal cual del Excel; las fechas van en noviembre de 2026. El detalle de cada una está en facturas_de_prueba/LEEME.md e INDICE.csv.</p>
      </div>
    </Modal>
  );
}
