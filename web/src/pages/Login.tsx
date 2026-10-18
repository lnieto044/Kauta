import { useEffect, useId, useState, type ReactNode } from "react";
import {
  ArrowLeft, Check, Eye, EyeOff, KeyRound, Lock, LogIn, Mail, Send, ShieldCheck, TriangleAlert, UserPlus,
} from "lucide-react";
import { api, type Regla, type Usuario } from "../api";
import { Aviso, Boton, Campo, claseEntrada, cx, Logo, TiraReglas } from "../ui";

/** Enlaces que llegan por correo: #/restablecer/<token>, #/activar/<token> y #/olvide. */
export type Enlace = { tipo: "restablecer" | "activar"; token: string } | { tipo: "olvide" };
export function leerEnlace(): Enlace | null {
  const [ruta, token] = window.location.hash.replace(/^#\/?/, "").split("/");
  if ((ruta === "restablecer" || ruta === "activar") && token && /^[A-Za-z0-9_-]{20,100}$/.test(token)) return { tipo: ruta, token };
  if (ruta === "olvide") return { tipo: "olvide" };
  return null;
}

type Vista = "entrar" | "mfa" | "olvide" | "olvide_ok" | "solicitar" | "solicitar_ok" | "invitacion" | "invitacion_ok" | "enlace";
type Config = { modo: string; entrega_correo: string; acceso_demo: boolean; largo_minimo: number };

export default function Login({ enlace, alEntrar, alSalirDelEnlace }: {
  enlace: Enlace | null; alEntrar: (u: Usuario) => void; alSalirDelEnlace: () => void;
}) {
  const inicial: Vista = enlace?.tipo === "olvide" ? "olvide" : enlace ? "enlace" : "entrar";
  const [vista, setVistaBase] = useState<Vista>(inicial);
  const [config, setConfig] = useState<Config>({ modo: "demo", entrega_correo: "buzon", acceso_demo: false, largo_minimo: 15 });
  const [correo, setCorreo] = useState("");
  const [clave, setClave] = useState("");          // solo en memoria, y se borra al salir del segundo paso
  const [aviso, setAviso] = useState<string | null>(null);
  useEffect(() => { api<Config>("/auth/config").then(setConfig).catch(() => {}); }, []);
  useEffect(() => { setVistaBase(enlace?.tipo === "olvide" ? "olvide" : enlace ? "enlace" : "entrar"); }, [enlace]);
  const setVista = (v: Vista, mensaje: string | null = null) => {
    setAviso(mensaje);
    setVistaBase(v);
    if (v === "entrar" && window.location.hash.match(/^#\/(olvide|restablecer|activar)/)) {
      window.location.hash = "";
      alSalirDelEnlace();
    }
  };

  return (
    <div className="grid min-h-dvh grid-cols-1 bg-white lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <PanelMarca demo={config.modo !== "produccion"} />
      <section className="flex flex-col px-6 py-8 sm:px-10">
        <div className="lg:hidden"><Logo /></div>
        <div className="flex flex-1 items-center justify-center py-10">
          <div className="w-full max-w-[400px]">
            {vista === "entrar" && <Entrar correo={correo} setCorreo={setCorreo} clave={clave} setClave={setClave} aviso={aviso} config={config}
              alEntrar={alEntrar} alPedirCodigo={() => setVista("mfa")} ir={setVista} />}
            {vista === "mfa" && <SegundoPaso correo={correo} clave={clave} alEntrar={(u) => { setClave(""); alEntrar(u); }} volver={() => { setClave(""); setVista("entrar"); }} />}
            {vista === "olvide" && <Olvide correo={correo} setCorreo={setCorreo} alEnviar={() => setVista("olvide_ok")} volver={() => setVista("entrar")} />}
            {vista === "olvide_ok" && (
              <Hecho icono={<Mail className="h-5 w-5" />} titulo="Revise su correo" volver={() => setVista("entrar")} entrega={config.entrega_correo}>
                Si <b>{correo}</b> corresponde a una cuenta activa, en unos minutos recibirá un enlace para elegir una contraseña nueva.
                El enlace sirve una sola vez y vence en 60 minutos.
              </Hecho>
            )}
            {vista === "solicitar" && <Solicitar correo={correo} setCorreo={setCorreo} alEnviar={() => setVista("solicitar_ok")} volver={() => setVista("entrar")} />}
            {vista === "solicitar_ok" && (
              <Hecho icono={<Send className="h-5 w-5" />} titulo="Revise su correo" volver={() => setVista("entrar")} entrega={config.entrega_correo}>
                Su cuenta quedó creada con el rol <b>Finanzas</b> (paga las facturas aprobadas). Le llegará a <b>{correo}</b> un enlace
                para crear su contraseña y activar la cuenta.
              </Hecho>
            )}
            {vista === "invitacion" && <Invitacion correo={correo} setCorreo={setCorreo} largo={config.largo_minimo}
              alCrear={() => setVista("entrar", "Cuenta creada. Ya puede iniciar sesión con su correo y su contraseña.")} volver={() => setVista("entrar")} />}
            {vista === "enlace" && enlace && enlace.tipo !== "olvide" && (
              <NuevaContrasena token={enlace.token} tipo={enlace.tipo} largo={config.largo_minimo}
                alTerminar={(c) => { setCorreo(c); setVista("entrar", "Contraseña guardada. Ya puede iniciar sesión."); }}
                volver={() => setVista("entrar")} pedirOtro={() => setVista("olvide")} />
            )}
          </div>
        </div>
        <footer className="border-t border-bruma pt-4 text-center text-[12px] leading-relaxed text-pizarra">
          <p className="flex flex-wrap items-center justify-center gap-x-4 gap-y-1">
            <span className="inline-flex items-center gap-1.5"><Lock className="h-3.5 w-3.5" /> Conexión cifrada y sesiones protegidas</span>
            <span>Pagos por PayPal en modo de pruebas</span>
          </p>
          <p className="mt-1">© 2026 Kauta · Reto Blinka · Hackathon 30X · Equipo: Luis, Juan, Mauricio y Laura</p>
        </footer>
      </section>
    </div>
  );
}

// ---------------------------------------------------------------- panel de marca
// La factura F12 del set: 12 reglas cumplen y la de la cuenta registrada (R07) no
const MUESTRA: Regla[] = "cumple cumple cumple cumple cumple cumple falla cumple cumple cumple cumple cumple cumple".split(" ")
  .map((estado, i) => ({ id: `R${String(i + 1).padStart(2, "0")}`, nombre: "", efecto: "escalar", estado: estado as Regla["estado"], detalle: "" }));

function PanelMarca({ demo }: { demo: boolean }) {
  return (
    <aside className="trama relative hidden flex-col justify-between overflow-hidden px-12 py-10 text-white lg:flex xl:px-16">
      <div>
        <Logo claro />
        <p className="mt-0.5 pl-10 text-[13px] text-[#AAB6D3]">Autónoma, pero cauta.</p>
      </div>
      <div className="max-w-xl">
        <h1 className="text-[32px] font-bold leading-[1.12] tracking-[-0.025em] xl:text-[38px]">
          Kauta paga lo que cumple, frena lo que no y te pregunta el resto.
        </h1>
        <p className="mt-5 max-w-lg text-[15.5px] leading-relaxed text-[#C9D2E8]">
          Un agente de cuentas por pagar: lee facturas en cualquier formato, las revisa contra 13 reglas de la empresa y paga
          desde la wallet. La IA solo lee; las decisiones las toma código que se puede auditar.
        </p>
        <div className="mt-9 rounded-lg bg-noche-2 p-5 ring-1 ring-white/10">
          <div className="flex items-center justify-between gap-4">
            <div>
              <p className="text-[13px] text-[#AAB6D3]">F12 · Andrés Felipe Rojas · COP 4.800.000</p>
              <p className="mt-1 text-[15px] font-semibold">Pide pagar a otra cuenta: ···0093 en lugar de ···8152</p>
            </div>
            <span className="rounded-md border-2 border-ambar px-2.5 py-0.5 text-[12.5px] font-bold uppercase tracking-[0.08em] text-ambar">Escalar</span>
          </div>
          <TiraReglas reglas={MUESTRA} grande className="mt-4" />
          <p className="mt-3 text-[13px] text-[#AAB6D3]">12 reglas cumplen; la de la cuenta registrada (R07) no. Kauta no paga y le pregunta a una persona.</p>
        </div>
        <p className="mt-6 flex flex-wrap gap-x-5 gap-y-2 text-[13px] text-[#C9D2E8]">
          {["Token para aprobar y para pagar", "Lo alto lo aprueba el CEO", "Registro que nadie puede alterar"].map((t) => (
            <span key={t} className="inline-flex items-center gap-1.5"><Check className="h-4 w-4 text-[#AAB6D3]" />{t}</span>
          ))}
        </p>
      </div>
      <p className="text-xs text-[#8D9AC0]">
        {demo ? "Hackathon 30X · Reto Blinka · todos los datos son ficticios y ningún dinero real se mueve." : "Brisamar Labs Inc."}
      </p>
    </aside>
  );
}

// ---------------------------------------------------------------- piezas comunes
function Titulo({ titulo, texto }: { titulo: string; texto?: ReactNode }) {
  return (
    <div className="mb-7">
      <h2 className="text-[22px] font-semibold tracking-tight text-noche">{titulo}</h2>
      {texto && <p className="mt-1.5 text-[14px] leading-relaxed text-pizarra">{texto}</p>}
    </div>
  );
}

function Volver({ onClick, texto = "Volver a iniciar sesión" }: { onClick: () => void; texto?: string }) {
  return (
    <button type="button" onClick={onClick} className="mt-6 inline-flex items-center gap-1.5 text-[13.5px] font-medium text-azul hover:text-azul-t hover:underline">
      <ArrowLeft className="h-4 w-4" /> {texto}
    </button>
  );
}

function AvisoBuzon({ entrega }: { entrega: string }) {
  if (entrega !== "buzon") return null;
  return (
    <p className="mt-4 rounded-md border border-ambar/25 bg-ambar-s px-3 py-2 text-[12.5px] leading-relaxed text-ambar-t">
      Entorno de demostración sin servidor de correo: el mensaje aparece en la terminal donde corre Kauta y queda guardado en <span className="font-mono">var/correos</span>.
    </p>
  );
}

function Hecho({ icono, titulo, children, volver, entrega }: { icono: ReactNode; titulo: string; children: ReactNode; volver: () => void; entrega: string }) {
  return (
    <div>
      <span className="grid h-11 w-11 place-items-center rounded-full bg-azul-s text-azul">{icono}</span>
      <h2 className="mt-5 text-[22px] font-semibold tracking-tight">{titulo}</h2>
      <p className="mt-2 text-[14px] leading-relaxed text-noche-3">{children}</p>
      <AvisoBuzon entrega={entrega} />
      <Volver onClick={volver} />
    </div>
  );
}

/** Contraseña con botón para mostrarla y aviso de Bloq Mayús. */
function CampoClave({ etiqueta, valor, setValor, autoComplete, ayuda, accesorio, autoFocus }: {
  etiqueta: string; valor: string; setValor: (v: string) => void; autoComplete: string; ayuda?: ReactNode; accesorio?: ReactNode; autoFocus?: boolean;
}) {
  const [ver, setVer] = useState(false);
  const [mayus, setMayus] = useState(false);
  const id = useId();
  const revisar = (e: React.KeyboardEvent) => setMayus(e.getModifierState?.("CapsLock") ?? false);
  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between text-[13px] font-medium text-noche-3">
        <label htmlFor={id}>{etiqueta}</label>{accesorio}
      </div>
      <div className="relative">
        <input id={id} className={claseEntrada + " pr-11"} type={ver ? "text" : "password"} autoComplete={autoComplete} value={valor} required
          autoFocus={autoFocus} onChange={(e) => setValor(e.target.value)} onKeyUp={revisar} onKeyDown={revisar} maxLength={200} />
        <button type="button" onClick={() => setVer(!ver)} className="absolute inset-y-0 right-0 grid w-10 place-items-center text-pizarra hover:text-noche"
          aria-label={ver ? "Ocultar contraseña" : "Mostrar contraseña"} title={ver ? "Ocultar" : "Mostrar"}>
          {ver ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
        </button>
      </div>
      {mayus && <p className="mt-1 flex items-center gap-1 text-xs font-medium text-ambar-t"><TriangleAlert className="h-3.5 w-3.5" /> Bloq Mayús está activado</p>}
      {ayuda && <div className="mt-1 text-xs text-pizarra">{ayuda}</div>}
    </div>
  );
}

/** Contraseña nueva + confirmación, con la política a la vista (NIST: largo mínimo, sin reglas raras). */
function ClaveNueva({ clave, setClave, clave2, setClave2, largo }: { clave: string; setClave: (v: string) => void; clave2: string; setClave2: (v: string) => void; largo: number }) {
  const faltan = Math.max(0, largo - clave.length);
  return (
    <>
      <CampoClave etiqueta="Contraseña nueva" valor={clave} setValor={setClave} autoComplete="new-password"
        ayuda={<span className="flex items-center justify-between gap-2"><span>Mínimo {largo} caracteres. Una frase propia es más segura y fácil de recordar.</span>
          <span className={cx("shrink-0 num", faltan ? "text-pizarra" : "font-medium text-menta-t")}>{clave.length}/{largo}</span></span>} />
      <div className="h-1 overflow-hidden rounded-full bg-bruma" aria-hidden="true">
        <div className={cx("h-full rounded-full transition-[width]", faltan ? "bg-ambar" : "bg-menta")} style={{ width: `${Math.min(100, (clave.length / largo) * 100)}%` }} />
      </div>
      <CampoClave etiqueta="Repetir contraseña" valor={clave2} setValor={setClave2} autoComplete="new-password"
        ayuda={clave2 && clave !== clave2 ? <span className="text-coral-t">Las dos contraseñas no coinciden.</span> : undefined} />
    </>
  );
}

function useEnvio() {
  const [enviando, setEnviando] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const correr = async (fn: () => Promise<void>) => {
    setEnviando(true);
    setError(null);
    try { await fn(); } catch (e) { setError((e as Error).message); } finally { setEnviando(false); }
  };
  return { enviando, error, correr };
}

// ---------------------------------------------------------------- iniciar sesión
function Entrar({ correo, setCorreo, clave, setClave, aviso, config, alEntrar, alPedirCodigo, ir }: {
  correo: string; setCorreo: (v: string) => void; clave: string; setClave: (v: string) => void; aviso: string | null; config: Config;
  alEntrar: (u: Usuario) => void; alPedirCodigo: () => void; ir: (v: Vista) => void;
}) {
  const { enviando, error, correr } = useEnvio();
  const entrar = () => correr(async () => {
    const r = await api<any>("/auth/login", { cuerpo: { correo, contrasena: clave } });
    if (r.mfa_requerido) {
      alPedirCodigo();
      return;
    }
    setClave("");
    alEntrar(r.usuario);
  });
  return (
    <div>
      <Titulo titulo="Iniciar sesión" texto="Ingrese con su cuenta de la empresa." />
      {aviso && <Aviso tono="exito" className="mb-5">{aviso}</Aviso>}
      <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); entrar(); }}>
        <Campo etiqueta="Correo">
          <input className={claseEntrada} type="email" autoComplete="username" value={correo} onChange={(e) => setCorreo(e.target.value)}
            placeholder="nombre@empresa.com" required autoFocus maxLength={160} />
        </Campo>
        <CampoClave etiqueta="Contraseña" valor={clave} setValor={setClave} autoComplete="current-password"
          accesorio={<button type="button" onClick={() => ir("olvide")} className="text-[13px] font-medium text-azul hover:text-azul-t hover:underline">¿Olvidó su contraseña?</button>} />
        {error && <Aviso tono="error">{error}</Aviso>}
        <Boton variante="primario" type="submit" cargando={enviando} icono={<LogIn className="h-4 w-4" />} className="min-h-10 w-full">Iniciar sesión</Boton>
      </form>

      <div className="mt-8 border-t border-bruma pt-6">
        <p className="text-[13.5px] font-medium text-noche">¿Aún no tiene acceso?</p>
        <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
          <Boton icono={<UserPlus className="h-4 w-4" />} onClick={() => ir("solicitar")}>Crear mi cuenta</Boton>
          <Boton icono={<KeyRound className="h-4 w-4" />} onClick={() => ir("invitacion")}>Tengo un código</Boton>
        </div>
      </div>
      {config.acceso_demo && <CuentasDemo alElegir={(c, p) => { setCorreo(c); setClave(p); }} />}
    </div>
  );
}

/** Solo si el servidor corre con KAUTA_ACCESO_DEMO=1: rellena el formulario, no entra solo. */
function CuentasDemo({ alElegir }: { alElegir: (correo: string, clave: string) => void }) {
  const [demo, setDemo] = useState<{ contrasena: string; usuarios: any[] } | null>(null);
  useEffect(() => { api("/auth/demo").then(setDemo).catch(() => setDemo(null)); }, []);
  if (!demo) return null;
  return (
    <details className="mt-6 rounded-md border border-bruma">
      <summary className="cursor-pointer px-4 py-2.5 text-[13px] font-medium text-noche-3">Cuentas de demostración</summary>
      <ul className="divide-y divide-bruma border-t border-bruma">
        {demo.usuarios.map((u) => (
          <li key={u.correo}>
            <button type="button" onClick={() => alElegir(u.correo, demo.contrasena)} className="flex w-full items-center justify-between gap-3 px-4 py-2 text-left hover:bg-niebla">
              <span className="min-w-0"><span className="block truncate text-[13px] font-medium">{u.nombre}</span><span className="block truncate text-xs text-pizarra">{u.correo}</span></span>
              <span className="shrink-0 rounded bg-niebla px-1.5 py-0.5 text-[11px] font-medium text-noche-3">{u.rol_nombre}</span>
            </button>
          </li>
        ))}
      </ul>
    </details>
  );
}

function SegundoPaso({ correo, clave, alEntrar, volver }: { correo: string; clave: string; alEntrar: (u: Usuario) => void; volver: () => void }) {
  const [codigo, setCodigo] = useState("");
  const { enviando, error, correr } = useEnvio();
  const verificar = () => correr(async () => {
    const r = await api<any>("/auth/login", { cuerpo: { correo, contrasena: clave, codigo } });
    alEntrar(r.usuario);
  });
  return (
    <div>
      <span className="grid h-11 w-11 place-items-center rounded-full bg-azul-s text-azul"><ShieldCheck className="h-5 w-5" /></span>
      <div className="mt-5"><Titulo titulo="Verificación en dos pasos" texto="Escriba el código de 6 dígitos de su app de autenticación." /></div>
      <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); verificar(); }}>
        <input className={claseEntrada + " text-center text-[20px] tracking-[0.45em] num"} inputMode="numeric" autoComplete="one-time-code" maxLength={6}
          value={codigo} onChange={(e) => setCodigo(e.target.value.replace(/\D/g, ""))} autoFocus aria-label="Código de verificación" />
        {error && <Aviso tono="error">{error}</Aviso>}
        <Boton variante="primario" type="submit" cargando={enviando} disabled={codigo.length !== 6} className="min-h-10 w-full">Verificar</Boton>
      </form>
      <Volver onClick={volver} />
    </div>
  );
}

// ---------------------------------------------------------------- recuperar la contraseña
function Olvide({ correo, setCorreo, alEnviar, volver }: { correo: string; setCorreo: (v: string) => void; alEnviar: () => void; volver: () => void }) {
  const { enviando, error, correr } = useEnvio();
  const enviar = () => correr(async () => { await api("/auth/olvide", { cuerpo: { correo } }); alEnviar(); });
  return (
    <div>
      <Titulo titulo="Restablecer la contraseña" texto="Escriba el correo de su cuenta y le enviaremos un enlace para elegir una contraseña nueva." />
      <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); enviar(); }}>
        <Campo etiqueta="Correo">
          <input className={claseEntrada} type="email" autoComplete="username" value={correo} onChange={(e) => setCorreo(e.target.value)}
            placeholder="nombre@empresa.com" required autoFocus maxLength={160} />
        </Campo>
        {error && <Aviso tono="error">{error}</Aviso>}
        <Boton variante="primario" type="submit" cargando={enviando} icono={<Mail className="h-4 w-4" />} className="min-h-10 w-full">Enviar enlace</Boton>
      </form>
      <Volver onClick={volver} />
    </div>
  );
}

function NuevaContrasena({ token, tipo, largo, alTerminar, volver, pedirOtro }: {
  token: string; tipo: "restablecer" | "activar"; largo: number; alTerminar: (correo: string) => void; volver: () => void; pedirOtro: () => void;
}) {
  const [info, setInfo] = useState<{ nombre: string; correo: string; rol_nombre: string } | null>(null);
  const [invalido, setInvalido] = useState<string | null>(null);
  const [clave, setClave] = useState("");
  const [clave2, setClave2] = useState("");
  const { enviando, error, correr } = useEnvio();
  useEffect(() => {
    api<any>("/auth/enlace", { cuerpo: { token } }).then(setInfo).catch((e) => setInvalido((e as Error).message));
  }, [token]);
  const guardar = () => correr(async () => {
    const r = await api<any>("/auth/restablecer", { cuerpo: { token, contrasena: clave } });
    alTerminar(r.correo);
  });
  if (invalido) {
    return (
      <div>
        <span className="grid h-11 w-11 place-items-center rounded-full bg-coral-s text-coral-t"><TriangleAlert className="h-5 w-5" /></span>
        <h2 className="mt-5 text-[22px] font-semibold tracking-tight">El enlace ya no sirve</h2>
        <p className="mt-2 text-[14px] leading-relaxed text-noche-3">{invalido} Los enlaces vencen y se usan una sola vez por seguridad.</p>
        <Boton variante="primario" className="mt-6 w-full" onClick={pedirOtro}>Pedir un enlace nuevo</Boton>
        <Volver onClick={volver} />
      </div>
    );
  }
  const activar = tipo === "activar";
  return (
    <div>
      <Titulo titulo={activar ? "Active su cuenta" : "Elija una contraseña nueva"}
        texto={info ? (activar
          ? <>Hola, {info.nombre}. Su acceso fue aprobado con el rol <b>{info.rol_nombre}</b>. Cree su contraseña para entrar.</>
          : <>Cuenta <b>{info.correo}</b>. Al guardar se cerrarán todas sus sesiones abiertas.</>) : "Comprobando el enlace…"} />
      <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); guardar(); }}>
        <input type="email" autoComplete="username" value={info?.correo ?? ""} readOnly hidden />
        <ClaveNueva clave={clave} setClave={setClave} clave2={clave2} setClave2={setClave2} largo={largo} />
        {error && <Aviso tono="error">{error}</Aviso>}
        <Boton variante="primario" type="submit" cargando={enviando} disabled={!info || clave.length < largo || clave !== clave2}
          icono={<Lock className="h-4 w-4" />} className="min-h-10 w-full">{activar ? "Activar mi cuenta" : "Guardar contraseña"}</Boton>
      </form>
      <Volver onClick={volver} />
    </div>
  );
}

// ---------------------------------------------------------------- alta: solicitud o invitación
function Solicitar({ correo, setCorreo, alEnviar, volver }: { correo: string; setCorreo: (v: string) => void; alEnviar: () => void; volver: () => void }) {
  const [nombre, setNombre] = useState("");
  const [cargo, setCargo] = useState("");
  const [mensaje, setMensaje] = useState("");
  const { enviando, error, correr } = useEnvio();
  const enviar = () => correr(async () => { await api("/personas/solicitar", { cuerpo: { nombre, correo, cargo, mensaje } }); alEnviar(); });
  return (
    <div>
      <Titulo titulo="Crear mi cuenta" texto="Entra con el rol Finanzas, el que paga las facturas, sin esperar aprobación. Le llegará a su correo un enlace para crear su contraseña; administración puede cambiar el rol después." />
      <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); enviar(); }}>
        <Campo etiqueta="Nombre y apellido">
          <input className={claseEntrada} autoComplete="name" value={nombre} onChange={(e) => setNombre(e.target.value)} required minLength={3} maxLength={120} autoFocus />
        </Campo>
        <Campo etiqueta="Correo de la empresa">
          <input className={claseEntrada} type="email" autoComplete="email" value={correo} onChange={(e) => setCorreo(e.target.value)} placeholder="nombre@empresa.com" required maxLength={160} />
        </Campo>
        <Campo etiqueta="Cargo">
          <input className={claseEntrada} autoComplete="organization-title" value={cargo} onChange={(e) => setCargo(e.target.value)} placeholder="Ej.: Analista de cuentas por pagar" maxLength={120} />
        </Campo>
        <Campo etiqueta="Mensaje para administración (opcional)">
          <textarea className={claseEntrada + " min-h-[72px]"} value={mensaje} onChange={(e) => setMensaje(e.target.value)} maxLength={500}
            placeholder="Área, jefe directo o para qué necesita el acceso." />
        </Campo>
        {error && <Aviso tono="error">{error}</Aviso>}
        <Boton variante="primario" type="submit" cargando={enviando} icono={<Send className="h-4 w-4" />} className="min-h-10 w-full">Crear mi cuenta</Boton>
      </form>
      <Volver onClick={volver} />
    </div>
  );
}

function Invitacion({ correo, setCorreo, largo, alCrear, volver }: { correo: string; setCorreo: (v: string) => void; largo: number; alCrear: () => void; volver: () => void }) {
  const [codigo, setCodigo] = useState("");
  const [clave, setClave] = useState("");
  const [clave2, setClave2] = useState("");
  const { enviando, error, correr } = useEnvio();
  const crear = () => correr(async () => {
    await api("/personas/registro", { cuerpo: { correo, codigo: codigo.trim().toUpperCase(), contrasena: clave } });
    alCrear();
  });
  return (
    <div>
      <Titulo titulo="Crear cuenta con invitación" texto="Use el código de un solo uso que le entregó administración. El código ya trae su rol." />
      <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); crear(); }}>
        <Campo etiqueta="Correo de la empresa">
          <input className={claseEntrada} type="email" autoComplete="username" value={correo} onChange={(e) => setCorreo(e.target.value)} required maxLength={160} autoFocus />
        </Campo>
        <Campo etiqueta="Código de invitación" ayuda="Tiene la forma KAUX-XXXX-XXXX, sirve una vez y vence a los 7 días.">
          <input className={claseEntrada + " font-mono uppercase tracking-[0.12em]"} value={codigo} maxLength={20} autoComplete="off"
            onChange={(e) => setCodigo(e.target.value.toUpperCase())} placeholder="KAUX-XXXX-XXXX" required />
        </Campo>
        <ClaveNueva clave={clave} setClave={setClave} clave2={clave2} setClave2={setClave2} largo={largo} />
        {error && <Aviso tono="error">{error}</Aviso>}
        <Boton variante="primario" type="submit" cargando={enviando} disabled={clave.length < largo || clave !== clave2}
          icono={<UserPlus className="h-4 w-4" />} className="min-h-10 w-full">Crear mi cuenta</Boton>
      </form>
      <Volver onClick={volver} />
    </div>
  );
}
