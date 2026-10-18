import {
  Banknote, Building2, LayoutDashboard, MessageCircleQuestion, ReceiptText, Route, ScanText, ScrollText, ShieldCheck, SlidersHorizontal, TrendingUp,
  Users, Wallet,
} from "lucide-react";

export type Seccion = { ruta: string; nombre: string; corto?: string; icono: typeof LayoutDashboard };
/** consulta: el rol ve estas secciones para supervisar, pero no actúa en ellas (no aprueba, no paga, no edita). */
export type Grupo = { titulo: string; secciones: Seccion[]; consulta?: boolean };

export const S = {
  resumen: { ruta: "resumen", nombre: "Resumen", icono: LayoutDashboard },
  rendimiento: { ruta: "rendimiento", nombre: "Rendimiento y costos", corto: "Rendimiento", icono: TrendingUp },
  rutas: { ruta: "rutas", nombre: "Rutas de pago", corto: "Rutas", icono: Route },
  facturas: { ruta: "facturas", nombre: "Facturas", icono: ReceiptText },
  pregunta: { ruta: "pregunta", nombre: "Kauta pregunta", corto: "Pregunta", icono: MessageCircleQuestion },
  proveedores: { ruta: "proveedores", nombre: "Proveedores", icono: Building2 },
  pagos: { ruta: "pagos", nombre: "Pagos", icono: Banknote },
  lector: { ruta: "lector", nombre: "Probar la lectura (OCR)", corto: "Lectura", icono: ScanText },
  wallet: { ruta: "wallet", nombre: "Wallet y conciliación", corto: "Wallet", icono: Wallet },
  reglas: { ruta: "reglas", nombre: "Reglas de pago", corto: "Reglas", icono: SlidersHorizontal },
  auditoria: { ruta: "auditoria", nombre: "Auditoría", icono: ScrollText },
  seguridad: { ruta: "seguridad", nombre: "Seguridad", icono: ShieldCheck },
  personas: { ruta: "personas", nombre: "Personas y roles", corto: "Personas", icono: Users },
} satisfies Record<string, Seccion>;

/** Cada rol ve solo lo que su trabajo necesita (los permisos se revisan además en el servidor). */
export const MENUS: Record<string, Grupo[]> = {
  finanzas: [
    { titulo: "General", secciones: [S.resumen, S.rendimiento] },
    { titulo: "Cuentas por pagar", secciones: [S.pregunta, S.pagos, S.facturas, S.lector, S.proveedores] },
    { titulo: "Tesorería", secciones: [S.wallet, S.rutas] },
    { titulo: "Mi cuenta", secciones: [S.seguridad] },
  ],
  ceo: [
    { titulo: "Dirección", secciones: [S.resumen, S.rendimiento] },
    { titulo: "Decisiones", secciones: [S.pregunta, S.pagos, S.rutas, S.facturas] },
    { titulo: "Control", secciones: [S.reglas, S.auditoria] },
    { titulo: "Mi cuenta", secciones: [S.seguridad] },
  ],
  admin: [
    { titulo: "Administración", secciones: [S.resumen, S.personas, S.seguridad, S.auditoria] },
    { titulo: "Supervisión · solo consulta", consulta: true, secciones: [S.pagos, S.facturas, S.lector, S.wallet, S.proveedores, S.reglas, S.rendimiento] },
  ],
};

export const menuDe = (rol: string) => MENUS[rol] ?? MENUS.finanzas;
export const enMenu = (rol: string, ruta: string) => menuDe(rol).some((g) => g.secciones.some((s) => s.ruta === ruta));
export const soloConsulta = (rol: string, ruta: string) => menuDe(rol).some((g) => g.consulta && g.secciones.some((s) => s.ruta === ruta));
