// Local-dev default. In a deployed image this file is regenerated at
// container startup from the API_BASE_URL environment variable -- see
// docker/frontend-entrypoint.sh -- so it is never edited by hand for a real
// deployment; this checked-in copy only backs `npm run dev` / `vite preview`.
window.__ENV__ = {
  API_BASE_URL: "http://127.0.0.1:8001",
};
