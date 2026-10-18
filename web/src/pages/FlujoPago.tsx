import { ArrowRight } from "lucide-react";
import { dinero, useApi, type Usuario } from "../api";
import { enMenu, S, type Seccion } from "../menus";
import { cx, Panel } from "../ui";

type Actor = "kauta" | "finanzas" | "ceo" | "admin";
const ACTOR: Record<Actor, { nombre: string; clase: string }> = {
  kauta: { nombre: "Kauta", clase: "bg-menta-s text-menta-t" },
  finanzas: { nombre: "Finanzas", clase: "bg-azul-s text-azul-t" },
  ceo: { nombre: "CEO", clase: "bg-noche text-white" },
  admin: { nombre: "Administrador", clase: "bg-niebla text-noche-3 ring-1 ring-bruma" },
};

type Paso = { titulo: string; texto: string; quien: Actor[]; seccion: Seccion };

/** Cómo se paga una factura de punta a punta: qué pasa en cada sección y qué hace cada rol. */
export default function FlujoPago({ usuario }: { usuario: Usuario }) {
  const { datos } = useApi<any>("/reglas");
  const umbral = datos?.vigente?.umbral_aprobacion_usd as number | undefined;
  const PASOS: Paso[] = [
    { titulo: "Llega la factura", seccion: S.facturas, quien: ["finanzas"],
      texto: "Llega por el buzón o se carga: PDF, foto, correo (.eml), chat (.txt) o XML fiscal. Kauta reconoce el canal por el archivo y le avisa por correo a quien la revisa, con el documento adjunto." },
    { titulo: "Kauta la lee y revisa 13 reglas", seccion: S.lector, quien: ["kauta"],
      texto: "Lee sin IA (XML exacto, texto del PDF, OCR de la foto o texto del chat), valida identificaciones fiscales y revisa cuenta, contrato, duplicados, límites y presupuesto." },
    { titulo: "Paga, frena o pregunta", seccion: S.pregunta, quien: ["kauta"],
      texto: "Si todo cumple y está bajo el umbral, paga sola. Si rompe una regla dura, la frena. Si hay una duda, la deja en «Kauta pregunta» con una pregunta concreta." },
    { titulo: "Una persona la aprueba con token", seccion: S.pregunta, quien: ["finanzas", "ceo"],
      texto: `Aprueba o rechaza con un comentario y el token de esa factura; quien la cargó no puede aprobarla.${umbral != null ? ` Por encima de ${dinero(umbral, "USD", 0)}` : " Sobre el umbral"} la aprueba el CEO. Aprobar no paga: queda «por pagar».` },
    { titulo: "Finanzas paga con PayPal", seccion: S.pagos, quien: ["finanzas", "kauta"],
      texto: "En «Pagos», con su token: la ventana de PayPal (usted aprueba o rechaza en PayPal) o el pago directo. Kauta revisa las reglas otra vez y muestra el resultado: exitoso, en proceso, fallido o negado." },
    { titulo: "Cuándo y cómo pagar", seccion: S.rutas, quien: ["ceo", "finanzas"],
      texto: "Con la caja de cada empresa, Kauta propone la ruta más barata sin romper la reserva. El CEO aprueba negociaciones y cambios de moneda; Finanzas la ejecuta." },
  ];
  const ALREDEDOR: { seccion: Seccion; quien: Actor[]; texto: string }[] = [
    { seccion: S.proveedores, quien: ["finanzas"], texto: "Cambios de cuenta: una persona los pide y otra los verifica por un canal independiente" },
    { seccion: S.reglas, quien: ["ceo"], texto: "El CEO define límites, umbral y presupuesto; cada cambio queda versionado" },
    { seccion: S.auditoria, quien: ["ceo", "admin"], texto: "Cada decisión, firma y pago, encadenados con HMAC" },
    { seccion: S.personas, quien: ["admin"], texto: "Accesos y roles (quien se registra entra como Finanzas); el Administrador no aprueba ni paga" },
    { seccion: S.wallet, quien: ["admin", "finanzas"], texto: "Conexión con el sandbox de PayPal: probar credenciales y receptor" },
  ];
  const yo = usuario.rol as Actor;
  const admin = yo === "admin";   // supervisa el flujo; sus tareas están alrededor del pago

  return (
    <Panel titulo="Cómo se paga una factura y quién hace qué" subtitulo={admin ? "Las secciones del menú en el orden del pago. Usted entra como Administrador: supervisa todo el flujo en modo consulta; sus tareas están abajo, alrededor del pago."
          : `Las secciones del menú en el orden del pago. Usted entra como ${ACTOR[yo]?.nombre ?? usuario.rol_nombre}: sus pasos van marcados.`}>
      <ol className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
        {PASOS.map((p, i) => {
          const mio = p.quien.includes(yo);
          return (
            <li key={p.titulo} className={cx("relative rounded-lg border p-4", mio ? "border-azul/40 bg-azul-s/30" : "border-bruma bg-white")}>
              <div className="flex items-start gap-3">
                <span className={cx("grid h-7 w-7 shrink-0 place-items-center rounded-full text-[13px] font-semibold", mio ? "bg-azul text-white" : "bg-niebla text-noche-3")}>{i + 1}</span>
                <div className="min-w-0">
                  <p className="flex flex-wrap items-center gap-2 text-[14px] font-semibold text-noche">{p.titulo}{mio && <span className="rounded bg-azul px-1.5 py-0.5 text-[11px] font-semibold text-white">Usted</span>}</p>
                  <p className="mt-1 text-[13px] leading-relaxed text-pizarra">{p.texto}</p>
                  <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
                    {p.quien.map((a) => <span key={a} className={cx("rounded px-1.5 py-0.5 text-[11.5px] font-semibold", ACTOR[a].clase)}>{ACTOR[a].nombre}</span>)}
                    <EnlaceSeccion seccion={p.seccion} rol={usuario.rol} />
                  </div>
                </div>
              </div>
            </li>
          );
        })}
      </ol>
      <div className="mt-5 border-t border-bruma pt-4">
        <p className="text-[12px] font-semibold uppercase tracking-wider text-pizarra">Alrededor del pago</p>
        <ul className="mt-2 grid grid-cols-1 gap-x-6 gap-y-2.5 md:grid-cols-2">
          {ALREDEDOR.map((a) => (
            <li key={a.seccion.ruta} className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[13px]">
              <EnlaceSeccion seccion={a.seccion} rol={usuario.rol} />
              {a.quien.map((q) => <span key={q} className={cx("rounded px-1.5 py-0.5 text-[11.5px] font-semibold", ACTOR[q].clase)}>{ACTOR[q].nombre}</span>)}
              <span className="basis-full text-pizarra">{a.texto}</span>
            </li>
          ))}
        </ul>
      </div>
    </Panel>
  );
}

function EnlaceSeccion({ seccion, rol }: { seccion: Seccion; rol: string }) {
  const Icono = seccion.icono;
  if (!enMenu(rol, seccion.ruta)) {
    return <span className="inline-flex items-center gap-1 text-[12.5px] text-pizarra" title="Esta sección no está en el menú de su rol"><Icono className="h-3.5 w-3.5" />{seccion.nombre}</span>;
  }
  return (
    <a href={`#/${seccion.ruta}`} className="inline-flex items-center gap-1 text-[12.5px] font-semibold text-azul hover:underline">
      <Icono className="h-3.5 w-3.5" />{seccion.nombre}<ArrowRight className="h-3 w-3" />
    </a>
  );
}
