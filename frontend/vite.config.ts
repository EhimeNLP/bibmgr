import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

const configuredBasePath = process.env.BIBMGR_BASE_PATH ?? "/";
const basePath =
  configuredBasePath === "/"
    ? "/"
    : `${configuredBasePath.replace(/\/+$/, "")}/`;

// https://vite.dev/config/
export default defineConfig({
  base: basePath,
  plugins: [vue()],
  server: {
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
