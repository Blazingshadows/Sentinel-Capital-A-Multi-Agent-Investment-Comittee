#!/bin/sh
# Regenerates env-config.js from this container's environment at startup --
# run automatically by nginx's image (anything executable in
# /docker-entrypoint.d/ runs before nginx starts). Overwrites the static
# dev-default copied in from public/env-config.js at build time.
set -eu

cat > /usr/share/nginx/html/env-config.js <<EOF
window.__ENV__ = {
  API_BASE_URL: "${API_BASE_URL:-http://127.0.0.1:8001}"
};
EOF
