import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { CalendarDays, ChevronDown, Clapperboard, Ellipsis, Eye, Lock, LogOut, PanelLeftClose, PanelLeftOpen, ShieldCheck } from "lucide-react";
import Introduccion, { debeMostrarIntro, olvidarSesionIntro } from "./Introduccion";
import { alPerderSesion, api, avisarCambio, fijarCsrf, ir, PERIODO, useCambios, useRuta, type Usuario } from "./api";
import { Boton, Cargando, cx, Isotipo, Logo, Modal, useToast } from "./ui";
import { enMenu, menuDe, S, soloConsulta } from "./menus";
import Login, { leerEnlace, type Enlace } from "./pages/Login";
import Resumen from "./pages/Resumen";
import Rendimiento from "./pages/Rendimiento";
import RutasPago from "./pages/RutasPago";
import Facturas from "./pages/Facturas";
import Detalle from "./pages/Detalle";
import Pregunta from "./pages/Pregunta";
import WalletPagina from "./pages/Wallet";
import Proveedores from "./pages/Proveedores";
import Reglas from "./pages/Reglas";
import Auditoria from "./pages/Auditoria";
import Seguridad from "./pages/Seguridad";
import Personas from "./pages/Personas";
import Pagos from "./pages/Pagos";
import Lector from "./pages/Lector";

export default function App() {
  const [usuario, setUsuario] = useState<Usuario | null>(null);
  const [modo, setModo] = useState("demo");
  const [listo, setListo] = useState(false);
  const [enlace, setEnlace] = useState<Enlace | null>(leerEnlace);
  const cargarYo = useCallback(async () => {
    try {
      const r = await api<{ usuario: Usuario; modo: string }>("/auth/yo");
      fijarCsrf(r.usuario.csrf);
      setUsuario(r.usuario);
      setModo(r.modo);
    } catch {
      setUsuario(null);
    } finally {
      setListo(true);
    }
  }, []);
  useEffect(() => {
    alPerderSesion(() => setUsuario(null));
    cargarYo();
    const f = () => setEnlace(leerEnlace());
    window.addEventListener("hashchange", f);
    return () => window.removeEventListener("hashchange", f);
  }, [cargarYo]);

  if (!listo) return <div className="mx-auto max-w-md p-10"><Cargando filas={3} /></div>;
  // Los enlaces que llegan por correo (restablecer o activar) se atienden aunque haya una sesión abierta
  if (!usuario || (enlace && enlace.tipo !== "olvide")) {
    return <Login enlace={enlace} alEntrar={(u) => { fijarCsrf(u.csrf); setUsuario(u); setEnlace(null); window.location.hash = "/resumen"; avisarCambio(); }}
      alSalirDelEnlace={() => { setEnlace(null); setUsuario(null); fijarCsrf(null); }} />;
  }
  return <Marco usuario={usuario} modo={modo} setUsuario={setUsuario} recargarUsuario={cargarYo} />;
}

function Iniciales({ nombre, className }: { nombre: string; className?: string }) {
  return (
    <span className={cx("grid shrink-0 place-items-center rounded-full bg-noche font-bold text-white", className)}>
      {nombre.split(" ").filter(Boolean).map((p) => p[0]).slice(0, 2).join("").toUpperCase()}
    </span>
  );
}

function Marco({ usuario, modo, setUsuario, recargarUsuario }: { usuario: Usuario; modo: string; setUsuario: (u: Usuario | null) => void; recargarUsuario: () => void }) {
  const [partes] = useRuta();
  const grupos = menuDe(usuario.rol);
  const todas = grupos.flatMap((g) => g.secciones);
  const moviles = todas.slice(0, 4);
  const [pendientes, setPendientes] = useState(0);
  const [periodo, setPeriodo] = useState("2026-10");
  const [mas, setMas] = useState(false);
  const [intro, setIntro] = useState(() => debeMostrarIntro(usuario));   // al entrar, hasta «No volver a mostrarlo»
  const [contraida, setContraida] = useState<boolean>(() => {
    try {
      const v = localStorage.getItem("kauta.menu");
      if (v) return v === "contraido";
    } catch { /* almacenamiento no disponible */ }
    return typeof window !== "undefined" && window.innerWidth < 1280;   // en pantallas medianas arranca contraída
  });
  const alternar = () => setContraida((c) => {
    try { localStorage.setItem("kauta.menu", c ? "expandido" : "contraido"); } catch { /* sin almacenamiento */ }
    return !c;
  });
  const toast = useToast();
  const contar = useCallback(() => {
    api<any[]>("/aprobaciones").then((l) => setPendientes(l.length)).catch(() => {});
    api<any>("/reglas").then((r) => setPeriodo(r.vigente.periodo_actual)).catch(() => {});
  }, []);
  useEffect(contar, [contar, partes.join("/")]);
  useCambios(contar);

  const salir = async () => {
    olvidarSesionIntro(usuario);
    await api("/auth/logout", { metodo: "POST", cuerpo: {} }).catch(() => {});
    fijarCsrf(null);
    setUsuario(null);
    window.location.hash = "";
    toast("Sesión cerrada", "info");
  };
  const pagina = partes[0] || "resumen";
  const actual = todas.find((s) => s.ruta === pagina);
  let contenido: ReactNode;
  if (!actual) {
    contenido = <FueraDelRol rol={usuario.rol_nombre} />;
  } else {
    switch (pagina) {
      case "rendimiento": contenido = <Rendimiento />; break;
      case "rutas": contenido = <RutasPago usuario={usuario} />; break;
      case "facturas": contenido = partes[1] ? <Detalle id={partes[1]} usuario={usuario} /> : <Facturas usuario={usuario} />; break;
      case "pregunta": contenido = <Pregunta usuario={usuario} />; break;
      case "pagos": contenido = <Pagos usuario={usuario} />; break;
      case "lector": contenido = <Lector usuario={usuario} />; break;
      case "wallet": contenido = <WalletPagina usuario={usuario} />; break;
      case "proveedores": contenido = <Proveedores usuario={usuario} />; break;
      case "reglas": contenido = <Reglas usuario={usuario} />; break;
      case "auditoria": contenido = <Auditoria usuario={usuario} />; break;
      case "seguridad": contenido = <Seguridad usuario={usuario} recargarUsuario={recargarUsuario} />; break;
      case "personas": contenido = <Personas usuario={usuario} />; break;
      default: contenido = <Resumen usuario={usuario} />;
    }
  }

  const ancho = contraida ? "max-w-[1680px]" : "max-w-[1440px]";
  const consulta = actual && soloConsulta(usuario.rol, pagina);

  return (
    <div className={cx("flex min-h-dvh flex-col transition-[padding] duration-200", contraida ? "lg:pl-[72px]" : "lg:pl-[248px]")}>
      {/* Barra lateral (computador): se contrae a solo íconos y recuerda la preferencia */}
      <aside className={cx("fixed inset-y-0 left-0 z-30 hidden flex-col bg-noche text-white transition-[width] duration-200 lg:flex", contraida ? "w-[72px]" : "w-[248px]")}
        aria-label="Menú principal">
        <div className={cx("flex h-14 shrink-0 items-center border-b border-white/10", contraida ? "justify-center" : "px-5")}>
          <a href="#/resumen" aria-label="Kauta, inicio">{contraida ? <Isotipo size={30} /> : <Logo claro />}</a>
        </div>
        <nav className={cx("barra-lateral flex-1 overflow-y-auto pb-3", contraida ? "px-2" : "px-3")} aria-label="Secciones">
          {grupos.map((g, i) => (
            <div key={g.titulo}>
              {contraida
                ? (i > 0 && <div className="mx-2 my-2.5 border-t border-white/10" aria-hidden="true" />)
                : <p className="px-2.5 pb-1 pt-4 text-[11px] font-semibold uppercase tracking-wider text-[#8D9AC0] [@media(max-height:760px)]:pt-2.5">{g.titulo}</p>}
              <ul className={cx("space-y-0.5", contraida && i === 0 && "pt-3")}>
                {g.secciones.map((n) => {
                  const activo = pagina === n.ruta;
                  const contador = n.ruta === "pregunta" && pendientes > 0;
                  return (
                    <li key={n.ruta}>
                      <a href={`#/${n.ruta}`} aria-current={activo ? "page" : undefined} title={contraida ? n.nombre : undefined}
                        aria-label={contraida ? `${n.nombre}${contador ? ` (${pendientes} pendientes)` : ""}` : undefined}
                        className={cx("relative flex items-center rounded-md text-[13.5px] font-medium transition-colors",
                          contraida ? "mx-auto h-10 w-10 justify-center" : "gap-2.5 px-2.5 py-[7px] [@media(max-height:760px)]:py-[5px]",
                          activo ? "bg-noche-3 text-white" : "text-[#C9D2E8] hover:bg-noche-2 hover:text-white")}>
                        {activo && <span className={cx("absolute w-[3px] rounded-r bg-azul", contraida ? "inset-y-2 -left-2" : "inset-y-1.5 left-0")} aria-hidden="true" />}
                        <n.icono className={cx("shrink-0", contraida ? "h-[18px] w-[18px]" : "h-4 w-4")} strokeWidth={1.75} />
                        {!contraida && <span className="flex-1 truncate">{n.nombre}</span>}
                        {contador && (contraida
                          ? <span className="absolute -right-0.5 -top-0.5 min-w-[18px] rounded-full bg-ambar px-1 text-center text-[10px] font-bold leading-[18px] text-noche num">{pendientes}</span>
                          : <span className="rounded-full bg-ambar px-1.5 py-px text-[11px] font-bold text-noche num">{pendientes}</span>)}
                      </a>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </nav>
        <div className="shrink-0 space-y-0.5 border-t border-white/10 p-2">
          <button type="button" onClick={() => setIntro(true)}
            className={cx("flex w-full items-center gap-2.5 rounded-md py-2 text-[13px] font-medium text-[#C9D2E8] hover:bg-noche-2 hover:text-white",
              contraida ? "justify-center" : "px-2.5")}
            title={contraida ? "Introducción (video)" : undefined} aria-label="Ver la introducción en video de su rol">
            <Clapperboard className={contraida ? "h-[18px] w-[18px]" : "h-4 w-4"} strokeWidth={1.75} />{!contraida && "Introducción (video)"}
          </button>
          <button type="button" onClick={alternar} aria-expanded={!contraida}
            className={cx("flex w-full items-center gap-2.5 rounded-md py-2 text-[13px] font-medium text-[#C9D2E8] hover:bg-noche-2 hover:text-white",
              contraida ? "justify-center" : "px-2.5")}
            title={contraida ? "Expandir el menú" : undefined} aria-label={contraida ? "Expandir el menú" : "Contraer el menú"}>
            {contraida ? <PanelLeftOpen className="h-[18px] w-[18px]" strokeWidth={1.75} /> : <><PanelLeftClose className="h-4 w-4" strokeWidth={1.75} /> Contraer menú</>}
          </button>
        </div>
      </aside>

      {/* Barra superior */}
      <header className="sticky top-0 z-20 border-b border-bruma bg-white/95 backdrop-blur supports-[backdrop-filter]:bg-white/85">
        <div className={cx("mx-auto flex h-14 items-center gap-3 px-4 sm:px-6", ancho)}>
          <button type="button" onClick={alternar} className="hidden rounded-md p-1.5 text-pizarra hover:bg-niebla hover:text-noche lg:inline-flex"
            aria-label={contraida ? "Expandir el menú" : "Contraer el menú"} title={contraida ? "Expandir el menú" : "Contraer el menú"}>
            {contraida ? <PanelLeftOpen className="h-[18px] w-[18px]" /> : <PanelLeftClose className="h-[18px] w-[18px]" />}
          </button>
          <a href="#/resumen" className="lg:hidden" aria-label="Inicio"><Logo /></a>
          <nav className="hidden min-w-0 items-center gap-2 text-[13px] sm:flex" aria-label="Ubicación">
            <span className="text-pizarra">Brisamar Labs Inc.</span>
            <span className="text-bruma">/</span>
            <span className="truncate font-medium text-noche">{partes[1] && pagina === "facturas" ? `Facturas / ${partes[1]}` : actual?.nombre ?? "Sección"}</span>
          </nav>
          <div className="ml-auto flex items-center gap-2">
            <span className="hidden items-center gap-1.5 rounded-md border border-bruma px-2.5 py-1 text-[12.5px] text-noche-3 md:inline-flex">
              <CalendarDays className="h-3.5 w-3.5 text-pizarra" /> Periodo: {PERIODO(periodo)}
            </span>
            {modo === "demo" && <span className="hidden rounded-full bg-ambar-s px-2.5 py-1 text-xs font-semibold text-ambar-t sm:inline">Demo · datos ficticios</span>}
            <MenuUsuario usuario={usuario} salir={salir} verIntro={() => setIntro(true)} />
          </div>
        </div>
      </header>

      <main className={cx("mx-auto w-full flex-1 px-4 pb-12 pt-6 sm:px-6", ancho)}>
        {consulta && (
          <p className="mb-5 flex items-start gap-2 rounded-md border border-azul/15 bg-azul-s px-4 py-2.5 text-[13px] text-azul-t" role="note">
            <Eye className="mt-0.5 h-4 w-4 shrink-0" />
            <span><b>Modo consulta.</b> Como {usuario.rol_nombre} ve esta sección para supervisar y dar soporte; no aprueba, no paga ni cambia datos. Esas acciones son de Finanzas y del CEO.</span>
          </p>
        )}
        {contenido}
      </main>

      <PiePagina usuario={usuario} modo={modo} ancho={ancho} />

      {/* Navegación inferior (celular y tableta vertical) */}
      <nav className="fixed inset-x-0 bottom-0 z-30 border-t border-bruma bg-white pb-[env(safe-area-inset-bottom)] lg:hidden" aria-label="Secciones">
        <div className="mx-auto grid max-w-xl grid-cols-5">
          {moviles.map((n) => {
            const activo = pagina === n.ruta;
            return (
              <a key={n.ruta} href={`#/${n.ruta}`} aria-current={activo ? "page" : undefined}
                className={cx("relative flex flex-col items-center gap-1 py-2.5 text-[11px] font-medium", activo ? "text-azul" : "text-pizarra")}>
                <n.icono className="h-5 w-5" strokeWidth={1.75} />
                {n.corto ?? n.nombre}
                {n.ruta === "pregunta" && pendientes > 0 && <span className="absolute right-[22%] top-1.5 rounded-full bg-ambar px-1.5 text-[10px] font-bold text-noche num">{pendientes}</span>}
              </a>
            );
          })}
          <button onClick={() => setMas(true)} className={cx("flex flex-col items-center gap-1 py-2.5 text-[11px] font-medium", todas.slice(4).some((n) => n.ruta === pagina) ? "text-azul" : "text-pizarra")}>
            <Ellipsis className="h-5 w-5" /> Más
          </button>
        </div>
      </nav>

      <Modal abierto={mas} titulo="Más secciones" onCerrar={() => setMas(false)}>
        <div className="grid grid-cols-2 gap-2">
          {todas.slice(4).map((n) => (
            <a key={n.ruta} href={`#/${n.ruta}`} onClick={() => setMas(false)} className="flex items-center gap-2.5 rounded-md border border-bruma p-3 text-[13.5px] font-medium hover:bg-niebla">
              <n.icono className="h-4.5 w-4.5 text-azul" strokeWidth={1.75} /> {n.nombre}
            </a>
          ))}
          <button onClick={() => { setMas(false); setIntro(true); }} className="col-span-2 flex items-center justify-center gap-2 rounded-md border border-bruma p-3 text-[13.5px] font-medium text-azul">
            <Clapperboard className="h-4 w-4" /> Introducción (video)
          </button>
          <button onClick={salir} className="col-span-2 flex items-center justify-center gap-2 rounded-md border border-bruma p-3 text-[13.5px] font-medium text-coral-t">
            <LogOut className="h-4 w-4" /> Cerrar sesión
          </button>
        </div>
      </Modal>
      <Introduccion usuario={usuario} abierto={intro} onCerrar={() => setIntro(false)} />
    </div>
  );
}

/** Pie de página de todas las pantallas: qué es Kauta, accesos rápidos del rol, entorno y créditos. */
function PiePagina({ usuario, modo, ancho }: { usuario: Usuario; modo: string; ancho: string }) {
  return (
    <footer className="border-t border-bruma bg-white pb-[calc(env(safe-area-inset-bottom)+4.5rem)] lg:pb-0">
      <div className={cx("mx-auto flex flex-col gap-4 px-4 py-5 sm:px-6 lg:flex-row lg:items-center lg:justify-between", ancho)}>
        <div className="flex min-w-0 items-center gap-3">
          <Isotipo size={26} />
          <p className="min-w-0 text-[13px] leading-snug text-pizarra">
            <b className="font-semibold text-noche">Kauta</b> · el agente que paga por la empresa. <span className="whitespace-nowrap">Autónoma, pero cauta.</span>
          </p>
        </div>
        <ul className="flex flex-wrap items-center gap-2 text-[12px] font-medium text-noche-3">
          <li className="inline-flex items-center gap-1.5 rounded-full bg-niebla px-2.5 py-1 ring-1 ring-bruma">
            <span className={cx("h-1.5 w-1.5 rounded-full", modo === "demo" ? "bg-ambar" : "bg-menta")} aria-hidden="true" />{modo === "demo" ? "Demo · datos ficticios" : "Producción"}
          </li>
          <li className="inline-flex items-center gap-1.5 rounded-full bg-niebla px-2.5 py-1 ring-1 ring-bruma">PayPal en modo de pruebas</li>
          <li className="inline-flex items-center gap-1.5 rounded-full bg-niebla px-2.5 py-1 ring-1 ring-bruma"><ShieldCheck className="h-3.5 w-3.5" /> Argon2id · AES-256-GCM · HMAC</li>
        </ul>
      </div>
      <div className="border-t border-bruma/70">
        <div className={cx("mx-auto flex flex-col gap-1 px-4 py-3 text-[12px] text-pizarra sm:px-6 md:flex-row md:items-center md:justify-between", ancho)}>
          <p>© 2026 Kauta · Reto Blinka · Hackathon 30X · Equipo: Luis, Juan, Mauricio y Laura</p>
          <p className="truncate">Sesión de {usuario.nombre} · {usuario.rol_nombre}</p>
        </div>
      </div>
    </footer>
  );
}

function FueraDelRol({ rol }: { rol: string }) {
  return (
    <div className="mx-auto max-w-lg py-16 text-center">
      <span className="mx-auto grid h-12 w-12 place-items-center rounded-full bg-niebla text-pizarra ring-1 ring-bruma"><Lock className="h-5 w-5" /></span>
      <h1 className="mt-5 text-[20px] font-semibold">Esta sección no es parte de su rol</h1>
      <p className="mt-2 text-[14px] text-pizarra">Como {rol}, en el menú de la izquierda tiene todo lo que su trabajo necesita. Si cree que debería verla, pídale a administración un cambio de rol.</p>
      <Boton variante="primario" className="mt-6" onClick={() => ir("resumen")}>Ir al resumen</Boton>
    </div>
  );
}

/** Menú de la cuenta: quién está conectado, su rol, la seguridad de su cuenta y cerrar sesión. */
function MenuUsuario({ usuario, salir, verIntro }: { usuario: Usuario; salir: () => void; verIntro: () => void }) {
  const [abierto, setAbierto] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!abierto) return;
    const fuera = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setAbierto(false); };
    const tecla = (e: KeyboardEvent) => e.key === "Escape" && setAbierto(false);
    document.addEventListener("mousedown", fuera);
    document.addEventListener("keydown", tecla);
    return () => { document.removeEventListener("mousedown", fuera); document.removeEventListener("keydown", tecla); };
  }, [abierto]);
  return (
    <div className="relative" ref={ref}>
      <button type="button" onClick={() => setAbierto(!abierto)} aria-haspopup="menu" aria-expanded={abierto}
        className="flex items-center gap-2 rounded-md py-1 pl-1 pr-2 hover:bg-niebla">
        <Iniciales nombre={usuario.nombre} className="h-8 w-8 text-[12px]" />
        <span className="hidden text-left leading-tight md:block">
          <span className="block max-w-[160px] truncate text-[13px] font-medium text-noche">{usuario.nombre}</span>
          <span className="block text-[11.5px] text-pizarra">{usuario.rol_nombre}</span>
        </span>
        <ChevronDown className="h-4 w-4 text-pizarra" />
      </button>
      {abierto && (
        <div role="menu" className="paso-animado absolute right-0 top-full z-40 mt-1.5 w-64 overflow-hidden rounded-lg border border-bruma bg-white shadow-lg">
          <div className="border-b border-bruma px-4 py-3">
            <p className="truncate text-[13.5px] font-semibold">{usuario.nombre}</p>
            <p className="truncate text-[12.5px] text-pizarra">{usuario.correo}</p>
            <p className="mt-1.5 inline-flex rounded bg-niebla px-1.5 py-0.5 text-[11.5px] font-medium text-noche-3">{usuario.cargo} · {usuario.rol_nombre}</p>
          </div>
          <a role="menuitem" href="#/seguridad" onClick={() => setAbierto(false)} className="flex items-center gap-2.5 px-4 py-2.5 text-[13.5px] hover:bg-niebla">
            <ShieldCheck className="h-4 w-4 text-pizarra" /> Seguridad de mi cuenta
          </a>
          <button role="menuitem" type="button" onClick={() => { setAbierto(false); verIntro(); }} className="flex w-full items-center gap-2.5 px-4 py-2.5 text-left text-[13.5px] hover:bg-niebla">
            <Clapperboard className="h-4 w-4 text-pizarra" /> Ver la introducción (video)
          </button>
          <button role="menuitem" type="button" onClick={salir} className="flex w-full items-center gap-2.5 border-t border-bruma px-4 py-2.5 text-left text-[13.5px] text-coral-t hover:bg-coral-s">
            <LogOut className="h-4 w-4" /> Cerrar sesión
          </button>
        </div>
      )}
    </div>
  );
}
