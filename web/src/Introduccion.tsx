import { useEffect, useRef, useState } from "react";
import { CirclePlay, PlayCircle, Volume2 } from "lucide-react";
import type { Usuario } from "./api";
import { Boton, cx, Modal } from "./ui";

type Capitulo = { t: number; titulo: string; texto: string };
type Video = { video: string; duracion: number; capitulos: Capitulo[] };

/** Lo que cada rol encuentra y hace, en pocas líneas (el video lo muestra en la pantalla real). */
const ROL: Record<string, { titulo: string; lema: string; encuentra: string[]; hace: string[] }> = {
  finanzas: {
    titulo: "Finanzas", lema: "Usted opera y paga",
    encuentra: ["Resumen: su trabajo del día", "Kauta pregunta", "Pagos", "Facturas y el buzón", "Probar la lectura (OCR)", "Proveedores, wallet y rutas"],
    hace: ["Responde lo que Kauta pregunta y aprueba hasta USD 3.000 con su token",
           "Paga en «Pagos» lo aprobado: con la ventana de PayPal (aprueba o rechaza en PayPal) o con el pago directo",
           "Revisa cómo terminó cada pago (exitoso, en proceso, fallido o negado) y reintenta los fallidos",
           "Carga facturas por cualquier canal y verifica cambios de cuenta de proveedores"],
  },
  ceo: {
    titulo: "CEO", lema: "Usted decide",
    encuentra: ["Resumen: lo que espera su decisión y el impacto", "Kauta pregunta", "Pagos (consulta)", "Rutas de pago", "Reglas de pago", "Rendimiento y auditoría"],
    hace: ["Aprueba con su token las facturas que superan USD 3.000 (después las paga Finanzas)",
           "Aprueba las rutas de pago: negociaciones y cambios de moneda",
           "Cambia las reglas (umbral, límites, presupuesto) y ve qué facturas cambiarían",
           "Revisa rendimiento, costos y la auditoría"],
  },
  admin: {
    titulo: "Administrador", lema: "Usted gestiona la plataforma",
    encuentra: ["Resumen: la plataforma", "Personas y roles", "Seguridad", "Auditoría", "Supervisión en modo consulta"],
    hace: ["Invita personas y cambia roles (quien se registra entra como Finanzas)",
           "Revisa sesiones, bloqueos, integraciones (PayPal, correo, OCR, IA) y la auditoría",
           "Prueba la conexión con PayPal",
           "Supervisa pagos, facturas y reglas sin poder aprobar ni pagar"],
  },
};

const clave = (u: Usuario) => `kauta.intro.${u.id}`;
const claveSesion = (u: Usuario) => `kauta.intro.sesion.${u.id}`;

/**
 * ¿Se muestra la introducción al entrar? Sí, en cada inicio de sesión, hasta que la persona marque «No volver a
 * mostrarlo». «Ver más tarde» la cierra solo por esta sesión. Nunca en las grabaciones ni en las pruebas automáticas.
 */
export function debeMostrarIntro(u: Usuario): boolean {
  try {
    return localStorage.getItem("kauta.intro.desactivada") !== "1" && localStorage.getItem(clave(u)) !== "nunca"
      && sessionStorage.getItem(claveSesion(u)) !== "cerrada";
  } catch {
    return false;
  }
}

/** Al cerrar sesión: el próximo inicio de sesión vuelve a mostrarla (salvo «No volver a mostrarlo»). */
export function olvidarSesionIntro(u: Usuario) {
  try { sessionStorage.removeItem(claveSesion(u)); } catch { /* sin almacenamiento */ }
}

const mmss = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

/** Bienvenida por rol: un video de la pantalla real con capítulos, más lo que el rol encuentra y hace. */
export default function Introduccion({ usuario, abierto, onCerrar }: { usuario: Usuario; abierto: boolean; onCerrar: () => void }) {
  const [videos, setVideos] = useState<Record<string, Video> | null>(null);
  const [actual, setActual] = useState(0);
  const [silenciado, setSilenciado] = useState(false);
  const [nunca, setNunca] = useState(() => { try { return localStorage.getItem(clave(usuario)) === "nunca"; } catch { return false; } });
  const ref = useRef<HTMLVideoElement>(null);
  const info = ROL[usuario.rol] ?? ROL.finanzas;
  const v = videos?.[usuario.rol];

  useEffect(() => {
    if (!abierto || videos) return;
    fetch("/videos/capitulos.json", { cache: "no-cache" }).then((r) => (r.ok ? r.json() : {})).then(setVideos).catch(() => setVideos({}));
  }, [abierto, videos]);

  const cerrar = () => {
    try {
      sessionStorage.setItem(claveSesion(usuario), "cerrada");
      if (nunca) localStorage.setItem(clave(usuario), "nunca"); else localStorage.removeItem(clave(usuario));
    } catch { /* sin almacenamiento: se vuelve a mostrar */ }
    ref.current?.pause();
    onCerrar();
  };
  const ir = (t: number) => {
    if (!ref.current) return;
    ref.current.currentTime = t;
    ref.current.play().catch(() => {});
  };
  // Con voz: se intenta reproducir con sonido; si el navegador no lo permite sin un clic, arranca en silencio y ofrece la voz
  const arrancar = () => {
    const el = ref.current;
    if (!el) return;
    el.muted = false;
    el.play().then(() => setSilenciado(false)).catch(() => {
      el.muted = true;
      setSilenciado(true);
      el.play().catch(() => {});
    });
  };
  const activarVoz = () => {
    if (!ref.current) return;
    ref.current.muted = false;
    ref.current.play().catch(() => {});
    setSilenciado(false);
  };
  const alAvanzar = () => {
    const t = ref.current?.currentTime ?? 0;
    const caps = v?.capitulos ?? [];
    let i = 0;
    caps.forEach((c, j) => { if (t >= c.t) i = j; });
    setActual(i);
  };

  return (
    <Modal abierto={abierto} titulo={`Bienvenida, ${usuario.nombre.split(" ")[0]} · ${info.titulo}`} onCerrar={cerrar} ancho="max-w-6xl">
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1.65fr)_minmax(0,1fr)]">
        <div className="min-w-0">
          {v ? (
            <div className="relative">
              <video ref={ref} src={v.video} className="aspect-video w-full rounded-lg bg-noche" controls playsInline preload="auto"
                onLoadedData={arrancar} onTimeUpdate={alAvanzar} onVolumeChange={() => ref.current && !ref.current.muted && setSilenciado(false)}
                aria-label={`Video de introducción para ${info.titulo}, con voz`} />
              {silenciado && (
                <button onClick={activarVoz} className="absolute left-1/2 top-4 inline-flex -translate-x-1/2 items-center gap-2 rounded-full bg-white px-4 py-2 text-[13.5px] font-semibold text-noche shadow-lg ring-1 ring-bruma hover:bg-niebla">
                  <Volume2 className="h-4 w-4 text-azul" /> Activar la voz
                </button>
              )}
            </div>
          ) : (
            <div className="grid aspect-video w-full place-items-center rounded-lg bg-noche text-center text-[#C9D2E8]">
              <p className="px-6 text-[14px]"><PlayCircle className="mx-auto mb-2 h-8 w-8" />{videos ? "El video de este rol aún no está grabado (scripts/grabar_videos.py)." : "Cargando el video…"}</p>
            </div>
          )}
          <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <p className="text-[12px] font-semibold uppercase tracking-wider text-pizarra">Qué encuentra</p>
              <ul className="mt-2 space-y-1 text-[13.5px] text-noche">{info.encuentra.map((x) => <li key={x}>· {x}</li>)}</ul>
            </div>
            <div>
              <p className="text-[12px] font-semibold uppercase tracking-wider text-pizarra">Qué hace</p>
              <ul className="mt-2 space-y-1.5 text-[13.5px] leading-snug text-noche">{info.hace.map((x) => <li key={x}>· {x}</li>)}</ul>
            </div>
          </div>
        </div>
        <div className="flex min-w-0 flex-col">
          <p className="text-[18px] font-semibold text-noche">{info.lema}</p>
          <p className="mt-0.5 text-[13px] text-pizarra">{v ? `Video con voz de ${mmss(v.duracion)} sobre la pantalla real, paso a paso. Toque un capítulo para ir a esa parte.` : "Paso a paso de su rol."}</p>
          <ol className="mt-3 max-h-[420px] space-y-1 overflow-y-auto pr-1">
            {(v?.capitulos ?? []).map((c, i) => (
              <li key={i}>
                <button onClick={() => ir(c.t)} className={cx("flex w-full gap-3 rounded-md px-2.5 py-2 text-left text-[13px] hover:bg-niebla", i === actual && "bg-azul-s")}>
                  <span className={cx("mt-0.5 shrink-0 font-mono text-xs", i === actual ? "text-azul-t" : "text-pizarra")}>{mmss(c.t)}</span>
                  <span className="min-w-0">
                    <span className={cx("block font-semibold", i === actual ? "text-azul-t" : "text-noche")}>{c.titulo}</span>
                    <span className="block leading-snug text-pizarra">{c.texto}</span>
                  </span>
                </button>
              </li>
            ))}
          </ol>
          <div className="mt-auto space-y-3 border-t border-bruma pt-4">
            <label className="flex cursor-pointer items-center gap-2 text-[13px] text-noche">
              <input type="checkbox" checked={nunca} onChange={(e) => setNunca(e.target.checked)} /> No volver a mostrarlo al entrar
            </label>
            <p className="text-xs text-pizarra">Siempre lo puede volver a ver en «Introducción (video)», abajo en el menú de la izquierda, o en el menú de su nombre.</p>
            <div className="flex flex-wrap justify-end gap-2">
              <Boton onClick={cerrar}>Ver más tarde</Boton>
              <Boton variante="primario" icono={<CirclePlay className="h-4 w-4" />} onClick={cerrar}>Empezar</Boton>
            </div>
          </div>
        </div>
      </div>
    </Modal>
  );
}
