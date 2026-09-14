#!/bin/sh
set -eu

escape_js() {
  printf '%s' "${1-}" | sed 's/\\/\\\\/g; s/"/\\"/g'
}

dsn=$(escape_js "${VITE_SENTRY_DSN-}")
environment=$(escape_js "${VITE_SENTRY_ENVIRONMENT:-${SENTRY_ENVIRONMENT-}}")
traces_sample_rate=$(escape_js "${VITE_SENTRY_TRACES_SAMPLE_RATE-}")

cat > /usr/share/nginx/html/env.js <<EOF
window.__ENV__ = {
  VITE_SENTRY_DSN: "${dsn}",
  VITE_SENTRY_ENVIRONMENT: "${environment}",
  VITE_SENTRY_TRACES_SAMPLE_RATE: "${traces_sample_rate}"
};
EOF

exec nginx -g "daemon off;"
