import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Without the React plugin there is no Fast Refresh, so every edit to main.jsx
// triggers a full page reload — which aborts an in-flight /api/analyze request
// and surfaces as "cannot reach the API" mid-analysis.
export default defineConfig({
  plugins: [react()],
  server: { host: "localhost", port: 5173, strictPort: true },
});
