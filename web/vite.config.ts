import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// En desarrollo, la API corre en FastAPI (puerto 8000) y Vite la reenvía.
// En producción, FastAPI sirve web/dist directamente: un solo origen, sin CORS.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { port: 5173, proxy: { "/api": "http://127.0.0.1:8000" } },
  build: { outDir: "dist", sourcemap: false, chunkSizeWarningLimit: 900, modulePreload: { polyfill: false } },
});
