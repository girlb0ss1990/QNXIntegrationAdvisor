import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Default build goes into the Python package so `qnx-advisor serve` ships one process.
// `--mode static` builds the M0 viewer (no API, pre-generated reports only) for GitHub Pages.
export default defineConfig(({ mode }) => ({
  plugins: [react()],
  base: "./",
  define: { __STATIC_VIEWER__: JSON.stringify(mode === "static") },
  build: {
    outDir: mode === "static" ? "dist-static" : "../advisor/static",
    emptyOutDir: true,
    chunkSizeWarningLimit: 4000,
  },
  server: { proxy: { "/api": "http://127.0.0.1:8765" } },
}));
