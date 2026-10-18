import { useCallback } from "react";
import { ArrowRight, Clock, Users } from "lucide-react";
import { dinero, fecha, useApi, useCambios, type FacturaResumen, type Plazo, type Pregunta as P, type Usuario } from "../api";
import { Cargando, cx, Encabezado, EstadoChip, TiraReglas, Vacio } from "../ui";

type Item = FacturaResumen & { preguntas: P[]; plazo: Plazo | null; ya_aprobe: boolean; cargue_yo: boolean; aprobadores: string[] };

export default function Pregunta({ usuario }: { usuario: Usuario }) {
  const { datos, cargando, recargar } = useApi<Item[]>("/aprobaciones");
  const rec = useCallback(() => recargar(), [recargar]);
  useCambios(rec);
  return (
    <div>
      <Encabezado titulo="Kauta pregunta"
        texto="Lo que se salió de las reglas blandas. Kauta no paga ni rechaza por su cuenta: te dice qué vio y qué necesita saber." />
      {cargando && !datos ? <Cargando /> : !datos?.length ? (
        <div className="rounded-lg border border-bruma bg-white">
          <Vacio titulo="No hay nada esperando una respuesta" texto="Cuando una factura se salga de las reglas, aparecerá aquí con una pregunta concreta y el token para aprobarla." />
        </div>
      ) : (
        <ul className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          {datos.map((f) => {
            const urgente = f.plazo && f.plazo.dias - f.plazo.dias_riel <= 2;
            return (
              <li key={f.id}>
                <a href={`#/facturas/${f.id}`} className="group block h-full rounded-lg border border-bruma bg-white p-5 transition-colors hover:border-ambar">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="font-mono text-xs text-pizarra">{f.id} · {f.numero ?? "sin número"}</p>
                      <p className="mt-0.5 truncate text-[16px] font-semibold">{f.beneficiario}</p>
                    </div>
                    <p className="shrink-0 text-right text-[16px] font-semibold num">{dinero(f.monto, f.moneda ?? "USD")}</p>
                  </div>
                  <div className="mt-3 space-y-2">
                    {f.preguntas.map((p) => (
                      <p key={p.regla} className="rounded-md bg-ambar-s/70 px-3 py-2 text-[14px] leading-snug">
                        <span className="mr-1.5 font-mono text-xs font-semibold text-ambar-t">{p.regla}</span>{p.pregunta}
                      </p>
                    ))}
                  </div>
                  <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2 text-[13px] text-pizarra">
                    <TiraReglas reglas={(f as any).reglas ?? []} />
                    {f.plazo && (
                      <span className={cx("inline-flex items-center gap-1.5", urgente && "font-semibold text-coral-t")}>
                        <Clock className="h-4 w-4" />Vence {fecha(f.plazo.vence, false)}{f.plazo.dias_riel > 0 && ` · ${f.plazo.riel} tarda ${f.plazo.dias_riel} d`}
                      </span>
                    )}
                    {((f as any).reglas ?? []).some((r: any) => r.id === "R10" && r.estado === "falla") && (
                      <span className="inline-flex items-center gap-1.5 font-semibold text-ambar-t">
                        <Users className="h-4 w-4" />Supera el umbral: la aprueba el CEO y la paga Finanzas
                      </span>
                    )}
                    <span className="ml-auto inline-flex items-center gap-1 font-semibold text-azul">
                      {f.ya_aprobe ? "Ya la aprobaste" : f.cargue_yo ? "Otra persona aprueba" : "Responder"} <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
                    </span>
                  </div>
                </a>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
