import { useCallback, useState } from "react";
import { CircleCheck, CircleX, Download, RefreshCw } from "lucide-react";
import { fecha, puede, useApi, useCambios, type Usuario } from "../api";
import { Boton, Cargando, cx, Encabezado, Hash, Panel } from "../ui";

const FILTROS = [
  ["", "Todo"], ["factura", "Decisiones"], ["aprobacion", "Aprobaciones"], ["pago", "Pagos"], ["reglas", "Reglas"],
  ["cuenta", "Cuentas"], ["seguridad", "Seguridad"], ["wallet", "Wallet"],
];

export default function Auditoria({ usuario }: { usuario: Usuario }) {
  const [tipo, setTipo] = useState("");
  const { datos, cargando, recargar } = useApi<any>(`/auditoria?limite=300${tipo ? `&tipo=${tipo}` : ""}`, [tipo]);
  const rec = useCallback(() => recargar(), [recargar]);
  useCambios(rec);
  if (!puede(usuario, "auditoria.ver")) return <Encabezado titulo="Auditoría" texto="Tu rol no consulta el registro de auditoría." />;
  const v = datos?.verificacion;
  return (
    <div className="space-y-6">
      <Encabezado titulo="Auditoría"
        texto="Cada decisión, aprobación, pago y cambio de reglas queda encadenado con HMAC-SHA256: si alguien edita o borra un evento, la cadena se rompe en ese punto."
        accion={puede(usuario, "auditoria.exportar") && <>
          <a href="/api/auditoria/exportar?formato=csv"><Boton icono={<Download className="h-4 w-4" />}>CSV</Boton></a>
          <a href="/api/auditoria/exportar?formato=jsonl"><Boton icono={<Download className="h-4 w-4" />}>JSONL</Boton></a>
        </>} />
      {v && (
        <section className={cx("flex flex-col gap-4 rounded-lg p-5 sm:flex-row sm:items-center", v.ok ? "bg-menta-s" : "bg-coral-s")}>
          {v.ok ? <CircleCheck className="h-9 w-9 shrink-0 text-menta-t" /> : <CircleX className="h-9 w-9 shrink-0 text-coral-t" />}
          <div className="min-w-0 flex-1">
            <p className="text-[17px] font-semibold">{v.mensaje}</p>
            <p className="mt-1 flex flex-wrap items-center gap-2 text-[13px] text-noche/75">Cabeza de la cadena (para anclar fuera del sistema): <Hash valor={v.cabeza} largo={24} /></p>
          </div>
          <Boton icono={<RefreshCw className="h-4 w-4" />} onClick={() => recargar()}>Verificar de nuevo</Boton>
        </section>
      )}
      <div className="-mx-1 flex gap-1 overflow-x-auto px-1 pb-1">
        {FILTROS.map(([k, t]) => (
          <button key={k} onClick={() => setTipo(k)} aria-pressed={tipo === k}
            className={cx("shrink-0 rounded-full px-3.5 py-1.5 text-[13px] font-semibold", tipo === k ? "bg-noche text-white" : "bg-white text-pizarra ring-1 ring-bruma")}>{t}</button>
        ))}
      </div>
      <Panel cuerpo="p-0">
        {cargando && !datos ? <div className="p-5"><Cargando /></div> : (
          <ol className="divide-y divide-bruma">
            {datos.eventos.map((e: any) => (
              <li key={e.id} className="grid grid-cols-1 gap-1 px-5 py-3 sm:grid-cols-[3.5rem_9.5rem_minmax(0,1fr)_auto] sm:items-start sm:gap-4">
                <span className="font-mono text-xs text-pizarra">#{e.id}</span>
                <span className="text-xs text-pizarra">{fecha(e.ts)}<span className="block font-medium text-noche/80">{e.tipo}</span></span>
                <span className="min-w-0 text-[13.5px]"><strong>{e.actor}</strong>{e.entidad_id && <span className="text-pizarra"> · {e.entidad} {e.entidad_id}</span>}<span className="block text-noche/80">{e.resumen}</span></span>
                <Hash valor={e.hash} largo={10} />
              </li>
            ))}
          </ol>
        )}
      </Panel>
    </div>
  );
}
