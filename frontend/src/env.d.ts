export {};

declare global {
  interface Window {
    // Populated by /env-config.js -- a static placeholder for local dev
    // (see frontend/public/env-config.js), regenerated from container
    // environment variables at startup in a deployed image (see
    // frontend/docker-entrypoint.sh). Optional because it's absent until
    // that script tag runs, and never present at all under `vite dev` if
    // the file's been deleted.
    __ENV__?: {
      API_BASE_URL?: string;
    };
  }
}
