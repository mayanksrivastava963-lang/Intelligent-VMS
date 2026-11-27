import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      // MediaMTX serves H.264/fMP4 HLS without EME/DRM or caption muxers; light build cuts chunk size ~37%.
      "hls.js": "hls.js/dist/hls.light.mjs",
    },
  },
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
});
