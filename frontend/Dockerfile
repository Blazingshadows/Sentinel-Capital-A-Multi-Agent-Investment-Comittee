# Build context is frontend/ itself (see docker-compose.yml).

# --- build: compile the static bundle ---------------------------------------
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# --- runtime: nginx serving the static bundle -------------------------------
FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
# nginx's own image runs every executable script in /docker-entrypoint.d/
# before starting nginx -- this regenerates env-config.js from this
# container's $API_BASE_URL each time it starts, so the *same built image*
# can be pointed at any backend (staging, prod, ...) via one env var, with
# no rebuild. See src/api.ts / env.d.ts for how the frontend reads it.
COPY docker-entrypoint.sh /docker-entrypoint.d/30-env-config.sh
RUN chmod +x /docker-entrypoint.d/30-env-config.sh

EXPOSE 80
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
    CMD wget -q -O /dev/null http://127.0.0.1/ || exit 1
