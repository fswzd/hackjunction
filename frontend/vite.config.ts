import { fileURLToPath, URL } from "node:url";
import { defineConfig, type ProxyOptions } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// macOS AirPlay Receiver occupies 5000, so the local Flask backend defaults to
// 5001 here. Keep both sides on the same BIRTHCO_PORT when overriding.
const backendPort = process.env.BIRTHCO_PORT ?? "5001";
const proxyTarget =
  process.env.VITE_API_PROXY_TARGET ?? `http://127.0.0.1:${backendPort}`;

function apiProxy(): Record<string, ProxyOptions> {
  return {
    "/api": {
      target: proxyTarget,
      changeOrigin: true,
      configure(proxy) {
        // The Flask session layer validates Origin/Referer/Sec-Fetch-Site.
        // Proxying as same-origin requires stripping the browser's headers.
        proxy.on("proxyReq", (proxyReq) => {
          proxyReq.removeHeader("origin");
          proxyReq.removeHeader("referer");
          proxyReq.removeHeader("sec-fetch-site");
        });
      },
    },
  };
}

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    host: "127.0.0.1",
    port: 4173,
    proxy: apiProxy(),
  },
  preview: {
    host: "127.0.0.1",
    port: 4173,
    proxy: apiProxy(),
  },
});
