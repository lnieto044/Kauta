import { useState } from "react";
import { Ban, Check, CircleCheck, Copy, KeyRound, LockOpen, Mail, ShieldCheck, UserPlus, Users, X } from "lucide-react";
import { api, fecha, puede, useApi, type Usuario } from "../api";
import { Aviso, Boton, Campo, Cargando, claseEntrada, cx, Dato, Encabezado, Hash, Modal, Panel, useToast, Vacio } from "../ui";

type Persona = {
  id: number; correo: string; nombre: string; cargo: string; rol: string; rol_nombre: string; rol_descripcion: string;
  activo: boolean; mfa_activo: boolean; creado_en: string | null; ultimo_acceso: string | null; bloqueado: boolean;
  intentos_fallidos: number; facturas_cargadas: number; firmas: number; sesiones_abiertas: number;
};
type Invitacion = {
  id: number; correo: string; nombre: string; cargo: string; rol: string; rol_nombre: string; prefijo: string;
  estado: "pendiente" | "usada" | "revocada" | "vencida"; creada_por: string; creada_en: string | null;
  expira_en: string | null; usada_en: string | null; intentos: number;
};
type Rol = { id: string; nombre: string; descripcion: string; permisos: string[]; claves: string[]; personas: number };
type Solicitud = {
  id: number; correo: string; nombre: string; cargo: string; mensaje: string; estado: "pendiente" | "aprobada" | "rechazada";
  creada_en: string | null; resuelta_en: string | null; resuelta_por: string | null; rol_nombre: string | null; motivo: string | null;
};
type Datos = { usuarios: Persona[]; invitaciones: Invitacion[]; solicitudes: Solicitud[]; roles: Rol[]; dias_invitacion: number;
  entrega_correo: string; politica_contrasena: { largo_minimo: number; texto: string } };
const NOTA_BUZON = " (demo sin servidor de correo: el mensaje aparece en la terminal del servidor y en var/correos)";

const COLOR_ROL: Record<string, string> = {
  admin: "bg-noche text-white", ceo: "bg-azul-s text-azul-t", finanzas: "bg-bruma text-noche",
};
const ESTADO_INV: Record<string, [string, string]> = {
  pendiente: ["Pendiente", "bg-ambar-s text-ambar-t"], usada: ["Usada", "bg-menta-s text-menta-t"],
  revocada: ["Revocada", "bg-niebla text-pizarra"], vencida: ["Vencida", "bg-coral-s text-coral-t"],
};

const LEMA: Record<string, string> = { finanzas: "Opera y paga", ceo: "Decide y aprueba lo alto", admin: "Gestiona la plataforma" };
const ordenRoles = (roles: Rol[]) => ["finanzas", "ceo", "admin"].map((id) => roles.find((r) => r.id === id)).filter(Boolean) as Rol[];

/** Qué puede hacer cada rol: la diferencia entre los tres, de un vistazo. */
const CAPACIDADES: [string, string, string][] = [
  ["Operación", "facturas.cargar", "Cargar facturas (correo, chat, PDF, foto, XML)"],
  ["Operación", "facturas.aprobar", "Aprobar o rechazar facturas con token (hasta el umbral)"],
  ["Operación", "pagos.ejecutar", "Pagar las facturas aprobadas con token (ventana de PayPal)"],
  ["Operación", "cuentas.verificar", "Verificar cambios de cuenta de proveedores"],
  ["Operación", "wallet.fondear", "Fondear la wallet"],
  ["Operación", "pagos.reintentar", "Reintentar pagos fallidos y consultar PayPal"],
  ["Decisión", "facturas.firma_alta", "Aprobar los montos sobre el umbral"],
  ["Decisión", "rutas.aprobar", "Aprobar rutas de pago (negociaciones y moneda)"],
  ["Decisión", "reglas.editar", "Cambiar las reglas de pago"],
  ["Supervisión", "reportes.ver", "Ver resumen, rendimiento, costos y rutas"],
  ["Supervisión", "auditoria.exportar", "Ver y exportar la auditoría"],
  ["Plataforma", "usuarios.gestionar", "Invitar personas, asignar roles y aprobar accesos"],
  ["Plataforma", "integraciones.probar", "Probar la conexión con PayPal"],
];

function MatrizRoles({ roles }: { roles: Rol[] }) {
  return (
    <Panel titulo="Qué puede hacer cada rol" cuerpo="p-0"
      subtitulo="Finanzas opera y paga, el CEO aprueba lo alto y el Administrador gestiona la plataforma. Aprobar y pagar son pasos distintos, y quien da los accesos no mueve dinero.">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[560px] text-[13.5px]">
          <thead>
            <tr className="border-b border-bruma text-left">
              <th className="px-5 py-2.5 text-[12px] font-semibold uppercase tracking-wider text-pizarra">Capacidad</th>
              {roles.map((r) => <th key={r.id} className="px-4 py-2.5 text-center"><Etiqueta texto={r.nombre} clase={COLOR_ROL[r.id] ?? "bg-niebla text-pizarra"} /></th>)}
            </tr>
          </thead>
          <tbody className="divide-y divide-bruma">
            {CAPACIDADES.map(([grupo, clave, texto], i) => (
              <tr key={clave} className={cx(i > 0 && CAPACIDADES[i - 1][0] !== grupo && "border-t-2 border-t-bruma")}>
                <td className="px-5 py-2.5"><span className="mr-2 text-[11.5px] font-semibold uppercase tracking-wider text-pizarra">{grupo}</span>{texto}</td>
                {roles.map((r) => {
                  const si = r.claves.includes(clave);
                  return (
                    <td key={r.id} className="px-4 py-2.5 text-center">
                      {si ? <CircleCheck className="mx-auto h-[18px] w-[18px] text-menta-t" aria-label="Sí" />
                          : <X className="mx-auto h-4 w-4 text-pizarra/50" aria-label="No" />}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="border-t border-bruma px-5 py-3 text-[12.5px] text-pizarra">Para todos: quien carga una factura no la aprueba; sobre el umbral la aprueba el CEO y la paga Finanzas, y aprobar y pagar piden cada uno su propio token.</p>
    </Panel>
  );
}

export function Etiqueta({ texto, clase }: { texto: string; clase: string }) {
  return <span className={cx("inline-flex shrink-0 items-center rounded px-2 py-0.5 text-[12px] font-medium", clase)}>{texto}</span>;
}

export default function Personas({ usuario }: { usuario: Usuario }) {
  const d = useApi<Datos>("/personas");
  const toast = useToast();
  const gestiona = puede(usuario, "usuarios.gestionar");
  const [invitando, setInvitando] = useState(false);
  const [codigo, setCodigo] = useState<{ inv: Invitacion; codigo: string } | null>(null);

  const accion = async (ruta: string, metodo: string, cuerpo?: unknown, mensaje?: string) => {
    try {
      const r = await api<any>(ruta, { metodo, cuerpo });
      toast((r?.mensaje ?? mensaje ?? "Listo") + (r?.entrega === "buzon" ? NOTA_BUZON : ""));
      d.recargar();
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };

  if (!d.datos) return <Cargando filas={6} />;
  const pendientes = d.datos.invitaciones.filter((i) => i.estado === "pendiente");

  return (
    <div className="space-y-6">
      <Encabezado titulo="Personas y roles"
        texto="Quién entra a Kauta, con qué rol y qué puede hacer. Las cuentas se crean por invitación o por registro: quien se registra entra como Finanzas y aquí se le puede cambiar el rol."
        accion={gestiona && <Boton variante="primario" icono={<UserPlus className="h-4 w-4" />} onClick={() => setInvitando(true)}>Invitar persona</Boton>} />

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {ordenRoles(d.datos.roles).map((r) => (
          <div key={r.id} className="flex flex-col rounded-lg border border-bruma bg-white p-5">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <Etiqueta texto={r.nombre} clase={COLOR_ROL[r.id] ?? "bg-niebla text-pizarra"} />
                <p className="mt-2 text-[15px] font-semibold text-noche">{LEMA[r.id] ?? ""}</p>
              </div>
              <div className="shrink-0 text-right">
                <p className="text-[26px] font-semibold leading-none tracking-tight text-noche num">{r.personas}</p>
                <p className="mt-1 text-xs text-pizarra">{r.personas === 1 ? "persona" : "personas"}</p>
              </div>
            </div>
            <p className="mt-3 border-t border-bruma pt-3 text-[13px] leading-relaxed text-pizarra">{r.descripcion}</p>
          </div>
        ))}
      </div>

      <MatrizRoles roles={ordenRoles(d.datos.roles)} />

      <Panel titulo={`Cuentas (${d.datos.usuarios.length})`} subtitulo="Rol, estado y actividad de cada persona" cuerpo="p-0">
        <ul className="divide-y divide-bruma">
          {d.datos.usuarios.map((u) => (
            <li key={u.id} className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:gap-4">
              <div className="flex min-w-0 flex-1 items-start gap-3">
                <span className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-azul-s text-[13px] font-semibold text-azul-t">
                  {u.nombre.split(" ").slice(0, 2).map((x) => x[0]).join("")}
                </span>
                <div className="min-w-0">
                  <p className="truncate text-[15px] font-semibold">
                    {u.nombre}
                    {u.id === usuario.id && <span className="ml-2 text-[12px] font-normal text-pizarra">(usted)</span>}
                  </p>
                  <p className="truncate text-[13px] text-pizarra">{u.cargo} · {u.correo}</p>
                  <p className="mt-1 text-[12px] text-pizarra/90">
                    {u.ultimo_acceso ? `Último acceso ${fecha(u.ultimo_acceso)}` : "Nunca ha entrado"}
                    {u.sesiones_abiertas > 0 && ` · ${u.sesiones_abiertas} sesión${u.sesiones_abiertas > 1 ? "es" : ""} abierta${u.sesiones_abiertas > 1 ? "s" : ""}`}
                    {u.facturas_cargadas > 0 && ` · ${u.facturas_cargadas} facturas cargadas`}
                    {u.firmas > 0 && ` · ${u.firmas} firmas`}
                  </p>
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {u.mfa_activo && <Etiqueta texto="2FA" clase="bg-menta-s text-menta-t" />}
                {u.bloqueado && <Etiqueta texto="Bloqueada" clase="bg-coral-s text-coral-t" />}
                {!u.activo && <Etiqueta texto="Inactiva" clase="bg-niebla text-pizarra" />}
                {gestiona && u.id !== usuario.id ? (
                  <select className={claseEntrada.replace("w-full", "w-44") + " h-9 min-h-9 py-1 text-[13px]"} value={u.rol} aria-label={`Rol de ${u.nombre}`}
                    onChange={(e) => accion(`/personas/${u.id}/rol`, "PUT", { rol: e.target.value }, `${u.nombre}: rol actualizado`)}>
                    {d.datos!.roles.map((r) => <option key={r.id} value={r.id}>{r.nombre}</option>)}
                  </select>
                ) : <Etiqueta texto={u.rol_nombre} clase={COLOR_ROL[u.rol] ?? "bg-niebla text-pizarra"} />}
                {gestiona && u.activo && (
                  <Boton icono={<Mail className="h-4 w-4" />} title="Enviar un enlace para restablecer la contraseña"
                    onClick={() => accion(`/personas/${u.id}/restablecer`, "POST", {}, "Enlace enviado")}>Restablecer clave</Boton>
                )}
                {gestiona && u.bloqueado && (
                  <Boton icono={<LockOpen className="h-4 w-4" />} onClick={() => accion(`/personas/${u.id}/desbloquear`, "POST", {}, "Cuenta desbloqueada")}>Desbloquear</Boton>
                )}
                {gestiona && u.id !== usuario.id && (
                  <Boton icono={u.activo ? <Ban className="h-4 w-4" /> : <CircleCheck className="h-4 w-4" />}
                    onClick={() => accion(`/personas/${u.id}/activo`, "PUT", { activo: !u.activo },
                      u.activo ? `${u.nombre}: cuenta desactivada y sesiones cerradas` : `${u.nombre}: cuenta activada`)}>
                    {u.activo ? "Desactivar" : "Activar"}
                  </Boton>
                )}
              </div>
            </li>
          ))}
        </ul>
      </Panel>

      {gestiona && <Solicitudes lista={d.datos.solicitudes} roles={d.datos.roles} accion={accion} />}

      <Panel titulo="Invitaciones" subtitulo={`El código sirve una sola vez y caduca a los ${d.datos.dias_invitacion} días`} cuerpo="p-0">
        {d.datos.invitaciones.length === 0 ? (
          <div className="p-5"><Vacio titulo="Todavía no hay invitaciones" texto="Cuando invite a alguien, aquí verá el estado de su código." /></div>
        ) : (
          <ul className="divide-y divide-bruma">
            {d.datos.invitaciones.map((i) => (
              <li key={i.id} className="flex flex-col gap-2 p-4 sm:flex-row sm:items-center sm:gap-4">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[14px] font-semibold">{i.nombre} · {i.correo}</p>
                  <p className="text-[13px] text-pizarra">
                    {i.rol_nombre} · código {i.prefijo}··· · invitó {i.creada_por}
                    {i.estado === "pendiente" && i.expira_en && ` · vence ${fecha(i.expira_en, false)}`}
                    {i.estado === "usada" && i.usada_en && ` · usada ${fecha(i.usada_en)}`}
                    {i.intentos > 0 && ` · ${i.intentos} intentos fallidos`}
                  </p>
                </div>
                <Etiqueta texto={ESTADO_INV[i.estado][0]} clase={ESTADO_INV[i.estado][1]} />
                {gestiona && i.estado === "pendiente" && (
                  <Boton onClick={() => accion(`/personas/invitaciones/${i.id}`, "DELETE", undefined, "Invitación revocada")}>Revocar</Boton>
                )}
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <Panel titulo="Cómo entra una persona nueva" subtitulo="Dos caminos: por invitación con el rol que usted defina, o por registro con el rol Finanzas">
        <ol className="space-y-3 text-[14px] leading-relaxed">
          {[["Por invitación", "Administración define correo, nombre, cargo y rol; Kauta genera un código de un solo uso que se entrega por otro canal (llamada o chat interno)."],
            ["Por registro", "La persona crea su cuenta desde la pantalla de inicio y entra con el rol Finanzas sin esperar aprobación. Usted recibe un aviso y aquí le cambia el rol o la desactiva si no corresponde."],
            ["Activa su cuenta", `Con el código o con el enlace que le llega al correo, elige su contraseña (mínimo ${d.datos.politica_contrasena.largo_minimo} caracteres).`],
            ["Entra con su rol", "Si olvida la contraseña, la restablece con un enlace de un solo uso. Puede activar el segundo factor desde «Seguridad». Todo queda en la auditoría."]].map(([t, x], n) => (
            <li key={t} className="flex gap-3">
              <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-azul-s text-[12px] font-semibold text-azul-t ring-1 ring-azul/20">{n + 1}</span>
              <span><b>{t}.</b> {x}</span>
            </li>
          ))}
        </ol>
        <p className="mt-4 flex gap-2 text-[13px] text-pizarra"><ShieldCheck className="h-4 w-4 shrink-0 text-menta-t" />{d.datos.politica_contrasena.texto} Del código solo se guarda su hash, igual que de una contraseña.</p>
      </Panel>

      {pendientes.length > 0 && gestiona && (
        <Aviso tono="info"><b>{pendientes.length} invitación{pendientes.length > 1 ? "es" : ""} sin usar.</b> Si alguien no la necesita, revóquela: una invitación abierta es una puerta abierta.</Aviso>
      )}

      <Invitar abierto={invitando} roles={d.datos.roles} onCerrar={() => setInvitando(false)}
        alCrear={(r) => { setInvitando(false); setCodigo(r); d.recargar(); }} />
      <Modal abierto={!!codigo} titulo="Código de invitación" onCerrar={() => setCodigo(null)}>
        {codigo && (
          <div className="space-y-4">
            <p className="text-[14px] leading-relaxed">
              Entréguele este código a <b>{codigo.inv.nombre}</b> ({codigo.inv.correo}). Entrará con el rol <b>{codigo.inv.rol_nombre}</b>.
            </p>
            <div className="rounded-md border border-bruma bg-niebla p-4 text-center">
              <p className="font-mono text-[22px] font-semibold tracking-[0.14em] text-noche">{codigo.codigo}</p>
              <button type="button" className="mt-2 inline-flex items-center gap-1.5 text-[13px] font-semibold text-azul"
                onClick={() => { navigator.clipboard?.writeText(codigo.codigo); toast("Código copiado", "info"); }}>
                <Copy className="h-3.5 w-3.5" />Copiar
              </button>
            </div>
            <Aviso tono="alerta">No se vuelve a mostrar: de aquí en adelante solo queda guardado su hash. Si se pierde, revoque la invitación y haga otra.</Aviso>
            <Boton variante="primario" className="w-full" onClick={() => setCodigo(null)}>Entendido</Boton>
          </div>
        )}
      </Modal>
    </div>
  );
}

function Invitar({ abierto, roles, onCerrar, alCrear }: {
  abierto: boolean; roles: Rol[]; onCerrar: () => void; alCrear: (r: { inv: Invitacion; codigo: string }) => void;
}) {
  const [correo, setCorreo] = useState("");
  const [nombre, setNombre] = useState("");
  const [cargo, setCargo] = useState("");
  const [rol, setRol] = useState("finanzas");
  const [error, setError] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);
  const elegido = roles.find((r) => r.id === rol);

  const enviar = async () => {
    setEnviando(true);
    setError(null);
    try {
      const r = await api<any>("/personas/invitar", { cuerpo: { correo, nombre, cargo, rol } });
      alCrear({ inv: r.invitacion, codigo: r.codigo });
      setCorreo(""); setNombre(""); setCargo(""); setRol("finanzas");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setEnviando(false);
    }
  };

  return (
    <Modal abierto={abierto} titulo="Invitar a una persona" onCerrar={onCerrar}>
      <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); enviar(); }}>
        <Campo etiqueta="Nombre y apellido">
          <input className={claseEntrada} value={nombre} onChange={(e) => setNombre(e.target.value)} required />
        </Campo>
        <Campo etiqueta="Correo de la empresa">
          <input className={claseEntrada} type="email" value={correo} onChange={(e) => setCorreo(e.target.value)} required />
        </Campo>
        <Campo etiqueta="Cargo">
          <input className={claseEntrada} value={cargo} onChange={(e) => setCargo(e.target.value)} placeholder="Analista de cuentas por pagar" />
        </Campo>
        <Campo etiqueta="Rol" ayuda={elegido?.descripcion}>
          <select className={claseEntrada} value={rol} onChange={(e) => setRol(e.target.value)}>
            {roles.map((r) => <option key={r.id} value={r.id}>{r.nombre}</option>)}
          </select>
        </Campo>
        {elegido && (
          <div className="rounded-md bg-niebla p-3 text-[13px] text-pizarra">
            <p className="flex gap-2"><Users className="h-4 w-4 shrink-0" />Podrá: {elegido.permisos.join(" · ").toLowerCase()}</p>
          </div>
        )}
        {error && <Aviso tono="error">{error}</Aviso>}
        <div className="flex flex-col gap-2 sm:flex-row sm:justify-end">
          <Boton type="button" onClick={onCerrar}>Cancelar</Boton>
          <Boton variante="primario" type="submit" cargando={enviando} icono={<KeyRound className="h-4 w-4" />}>Generar código</Boton>
        </div>
      </form>
    </Modal>
  );
}

/** Solicitudes de acceso: administración aprueba (y asigna el rol) o rechaza. */
function Solicitudes({ lista, roles, accion }: {
  lista: Solicitud[]; roles: Rol[]; accion: (ruta: string, metodo: string, cuerpo?: unknown, mensaje?: string) => Promise<void>;
}) {
  const [rolDe, setRolDe] = useState<Record<number, string>>({});
  const pendientes = lista.filter((s) => s.estado === "pendiente");
  const resueltas = lista.filter((s) => s.estado !== "pendiente").slice(0, 6);
  return (
    <Panel titulo={`Registros y solicitudes${pendientes.length ? ` (${pendientes.length} pendientes)` : ""}`}
      subtitulo="Registros (entran como Finanzas) y solicitudes pendientes: confirme por otro canal que la persona trabaja en la empresa" cuerpo="p-0">
      {lista.length === 0 ? (
        <p className="px-5 py-6 text-[13.5px] text-pizarra">No hay registros ni solicitudes. Quien no tenga invitación puede crear su cuenta desde la pantalla de inicio (entra como Finanzas).</p>
      ) : (
        <ul className="divide-y divide-bruma">
          {pendientes.map((s) => (
            <li key={s.id} className="flex flex-col gap-3 p-4 lg:flex-row lg:items-center lg:gap-4">
              <div className="min-w-0 flex-1">
                <p className="truncate text-[14px] font-semibold">{s.nombre} <span className="font-normal text-pizarra">· {s.correo}</span></p>
                <p className="text-[13px] text-pizarra">{s.cargo} · pedida {fecha(s.creada_en)}</p>
                {s.mensaje && <p className="mt-1 text-[13px] text-noche-3">«{s.mensaje}»</p>}
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <select className={claseEntrada.replace("w-full", "w-44") + " h-9 min-h-9 py-1 text-[13px]"} aria-label={`Rol para ${s.nombre}`}
                  value={rolDe[s.id] ?? "finanzas"} onChange={(e) => setRolDe({ ...rolDe, [s.id]: e.target.value })}>
                  {roles.map((r) => <option key={r.id} value={r.id}>{r.nombre}</option>)}
                </select>
                <Boton variante="primario" icono={<Check className="h-4 w-4" />}
                  onClick={() => accion(`/personas/solicitudes/${s.id}/aprobar`, "POST", { rol: rolDe[s.id] ?? "finanzas" })}>Aprobar</Boton>
                <Boton variante="peligro" icono={<X className="h-4 w-4" />}
                  onClick={() => accion(`/personas/solicitudes/${s.id}/rechazar`, "POST", { motivo: "" }, "Solicitud rechazada")}>Rechazar</Boton>
              </div>
            </li>
          ))}
          {resueltas.map((s) => (
            <li key={s.id} className="flex flex-col gap-1 px-4 py-3 sm:flex-row sm:items-center sm:gap-4">
              <p className="min-w-0 flex-1 truncate text-[13.5px]">{s.nombre} · <span className="text-pizarra">{s.correo}</span></p>
              <p className="text-[12.5px] text-pizarra">{s.estado === "aprobada" ? `Aprobada como ${s.rol_nombre}` : "Rechazada"} · {s.resuelta_por}</p>
              <Etiqueta texto={s.estado === "aprobada" ? "Aprobada" : "Rechazada"} clase={s.estado === "aprobada" ? "bg-menta-s text-menta-t" : "bg-niebla text-pizarra"} />
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
