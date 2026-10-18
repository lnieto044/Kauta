import { useCallback, useEffect, useState } from "react";
import { Eye, Save } from "lucide-react";
import { api, avisarCambio, dinero, fecha, puede, useApi, useCambios, type Usuario } from "../api";
import { Aviso, Boton, Campo, Cargando, claseEntrada, cx, Encabezado, Panel, useToast } from "../ui";

const CAMPOS: { k: string; t: string; ayuda: string; regla: string; tipo?: "pct" | "conf" }[] = [
  { k: "presupuesto_periodo_usd", t: "Presupuesto del periodo (USD)", ayuda: "Lo máximo que sale en un mes. La sub-wallet se ajusta al guardar.", regla: "R12" },
  { k: "umbral_aprobacion_usd", t: "Umbral de aprobación humana (USD)", ayuda: "Por encima, se necesitan dos personas.", regla: "R10" },
  { k: "limite_maximo_pago_usd", t: "Máximo por pago (USD)", ayuda: "Nunca se paga más que esto, ni con aprobación.", regla: "R09" },
  { k: "limite_beneficiario_periodo_usd", t: "Límite por beneficiario en el periodo (USD)", ayuda: "Frena el fraccionamiento de facturas.", regla: "R11" },
  { k: "tolerancia_contrato_pct", t: "Tolerancia frente al contrato (%)", ayuda: "Diferencia aceptada contra lo acordado.", regla: "R08", tipo: "pct" },
  { k: "confianza_minima", t: "Confianza mínima de lectura", ayuda: "Por debajo, Kauta pregunta en vez de adivinar.", regla: "R01", tipo: "conf" },
];
const MONEDAS = ["USD", "COP", "MXN", "EUR", "ARS", "BRL"];

export default function Reglas({ usuario }: { usuario: Usuario }) {
  const { datos, recargar } = useApi<any>("/reglas");
  const rec = useCallback(() => recargar(), [recargar]);
  useCambios(rec);
  const [form, setForm] = useState<Record<string, any> | null>(null);
  const [motivo, setMotivo] = useState("");
  const [vista, setVista] = useState<any[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [guardando, setGuardando] = useState(false);
  const toast = useToast();
  useEffect(() => { if (datos) setForm({ ...datos.vigente }); }, [datos]);
  if (!datos || !form) return <Cargando filas={5} />;
  const editable = puede(usuario, "reglas.editar");
  const cuerpo = () => ({
    ...Object.fromEntries(CAMPOS.map((c) => [c.k, Number(form[c.k])])), monedas_permitidas: form.monedas_permitidas, motivo: motivo || "Simulación",
  });
  const cambiado = CAMPOS.some((c) => Number(form[c.k]) !== Number(datos.vigente[c.k])) || form.monedas_permitidas.join() !== datos.vigente.monedas_permitidas.join();

  const simular = async () => {
    setError(null);
    try { setVista(await api<any[]>("/reglas/simular", { cuerpo: cuerpo() })); } catch (e) { setError((e as Error).message); }
  };
  const guardar = async () => {
    setGuardando(true);
    setError(null);
    try {
      const r = await api<any>("/reglas", { metodo: "PUT", cuerpo: cuerpo() });
      toast(`Reglas v${r.version} vigentes${r.reevaluadas.length ? ` · cambiaron ${r.reevaluadas.join(", ")}` : ""}`);
      setMotivo("");
      setVista(null);
      avisarCambio();
      recargar();
    } catch (e) { setError((e as Error).message); } finally { setGuardando(false); }
  };

  return (
    <div className="space-y-6">
      <Encabezado titulo="Reglas" texto={`Versión ${datos.vigente.version} vigente. Cambiarlas crea una versión nueva y Kauta reevalúa, en orden, las facturas frenadas y pendientes; las pagadas no se tocan.`} />
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)]">
        <Panel titulo="Política de pagos" subtitulo={editable ? "Prueba un cambio con «Ver qué cambiaría» antes de guardarlo" : "Solo lectura para tu rol"}>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {CAMPOS.map((c) => (
              <Campo key={c.k} etiqueta={c.t} ayuda={<><span className="font-mono">{c.regla}</span> · {c.ayuda}</>}>
                <input className={cx(claseEntrada, "num", Number(form[c.k]) !== Number(datos.vigente[c.k]) && "border-azul bg-azul-s/40")} inputMode="decimal" disabled={!editable}
                  value={form[c.k]} onChange={(e) => { setForm({ ...form, [c.k]: e.target.value }); setVista(null); }} />
              </Campo>
            ))}
          </div>
          <fieldset className="mt-5">
            <legend className="mb-2 text-[13px] font-semibold">Monedas permitidas <span className="font-mono font-normal text-pizarra">R02</span></legend>
            <div className="flex flex-wrap gap-2">
              {MONEDAS.map((m) => {
                const on = form.monedas_permitidas.includes(m);
                return (
                  <button key={m} type="button" disabled={!editable} aria-pressed={on}
                    onClick={() => { setForm({ ...form, monedas_permitidas: on ? form.monedas_permitidas.filter((x: string) => x !== m) : [...form.monedas_permitidas, m] }); setVista(null); }}
                    className={cx("rounded-full px-3.5 py-1.5 text-[13px] font-semibold ring-1", on ? "bg-noche text-white ring-noche" : "bg-white text-pizarra ring-bruma")}>{m}</button>
                );
              })}
            </div>
          </fieldset>
          {editable && (
            <div className="mt-6 space-y-3 border-t border-bruma pt-5">
              <Campo etiqueta="Motivo del cambio" ayuda="Queda en la versión y en la auditoría.">
                <input className={claseEntrada} value={motivo} onChange={(e) => setMotivo(e.target.value)} placeholder="Ej.: Aprobado aumento de presupuesto para el cierre de octubre" />
              </Campo>
              {error && <Aviso tono="error">{error}</Aviso>}
              <div className="flex flex-wrap gap-2">
                <Boton icono={<Eye className="h-4 w-4" />} disabled={!cambiado} onClick={simular}>Ver qué cambiaría</Boton>
                <Boton variante="primario" icono={<Save className="h-4 w-4" />} disabled={!cambiado || motivo.trim().length < 3} cargando={guardando} onClick={guardar}>Guardar como versión {datos.vigente.version + 1}</Boton>
              </div>
            </div>
          )}
          {vista && (
            <div className="mt-5 rounded-md bg-niebla p-4">
              <p className="text-[14px] font-semibold">Con estos valores, {vista.filter((v) => v.antes !== v.despues).length} de {vista.length} facturas abiertas cambiarían:</p>
              <ul className="mt-2 space-y-1.5 text-[13px]">
                {vista.filter((v) => v.antes !== v.despues).map((v) => (
                  <li key={v.id}><span className="font-mono">{v.id}</span> {v.beneficiario}: <strong>{v.antes}</strong> → <strong className={v.despues === "pagar" ? "text-menta-t" : v.despues === "frenar" ? "text-coral-t" : "text-ambar-t"}>{v.despues}</strong></li>
                ))}
                {vista.every((v) => v.antes === v.despues) && <li className="text-pizarra">Ninguna decisión cambiaría.</li>}
              </ul>
            </div>
          )}
        </Panel>

        <div className="space-y-6">
          <Panel titulo="Las 13 reglas" subtitulo="Frenar domina sobre escalar, y escalar sobre pagar" cuerpo="p-0">
            <ul className="divide-y divide-bruma">
              {datos.catalogo.map((r: any) => (
                <li key={r.id} className="flex items-center gap-3 px-5 py-2.5 text-[13.5px]">
                  <span className={cx("h-3 w-3 shrink-0 rounded-[3px]", r.efecto === "frenar" ? "bg-coral" : "bg-ambar")} />
                  <span className="w-9 shrink-0 font-mono text-xs text-pizarra">{r.id}</span>
                  <span className="min-w-0 flex-1 font-medium">{r.nombre}</span>
                  <span className={cx("text-xs font-semibold", r.efecto === "frenar" ? "text-coral-t" : "text-ambar-t")}>{r.efecto === "frenar" ? "frena" : "escala"}</span>
                </li>
              ))}
            </ul>
          </Panel>
          <Panel titulo="Versiones" cuerpo="p-0">
            <ul className="divide-y divide-bruma">
              {datos.versiones.map((v: any) => (
                <li key={v.version} className="px-5 py-3 text-[13.5px]">
                  <p><strong>v{v.version}</strong> · {v.creada_por} · <span className="text-pizarra">{fecha(v.creada_en)}</span></p>
                  <p className="text-pizarra">{v.motivo}</p>
                  {Object.keys(v.cambios ?? {}).length > 0 && <p className="mt-0.5 text-xs">{Object.entries<any>(v.cambios).map(([k, c]) => `${k.replace(/_/g, " ")}: ${typeof c.antes === "number" && k.includes("usd") ? dinero(c.antes, "USD", 0) : c.antes} → ${typeof c.despues === "number" && k.includes("usd") ? dinero(c.despues, "USD", 0) : c.despues}`).join(" · ")}</p>}
                </li>
              ))}
            </ul>
          </Panel>
        </div>
      </div>
    </div>
  );
}
