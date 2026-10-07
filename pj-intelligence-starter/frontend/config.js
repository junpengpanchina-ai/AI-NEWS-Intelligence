window.PJ_CONFIG = {
  API_BASE: "/api",
  APP_NAME: "PJ Intelligence",
};

function getApiBase() {
  const host = window.location.hostname;
  const local = host === "localhost" || host === "127.0.0.1" || host === "";
  if (local) return "http://localhost:8765";
  const configured = window.PJ_CONFIG && typeof window.PJ_CONFIG.API_BASE === "string"
    ? window.PJ_CONFIG.API_BASE.trim()
    : "";
  return configured || "/api";
}

function apiPath(path) {
  const base = getApiBase().replace(/\/$/, "");
  const clean = path.startsWith("/") ? path : `/${path}`;
  if (base === "" || base === "/") return clean;
  if (base === "/api" && clean.startsWith("/api/")) return clean;
  return `${base}${clean}`;
}
