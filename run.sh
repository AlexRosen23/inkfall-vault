#!/bin/sh
# One command, one port: seeds the fictional database if it is missing, builds the static UI if it is missing, then
# serves the API, the read-only contract (/health, /capabilities, /runs) and the UI on 127.0.0.1:${INKFALL_API_PORT:-5110}.
# Used by `make serve` and by the Constellation's launcher. Needs `make setup` once (Python venv + web/node_modules).
set -eu
cd "$(dirname "$0")"
PORT="${INKFALL_API_PORT:-5110}"
if [ ! -x .venv/bin/python ]; then
  echo "run.sh: .venv missing - run make setup once" >&2
  exit 1
fi
if [ ! -f data/inkfall.db ]; then
  .venv/bin/python -m inkfall.seed
fi
if [ ! -f web/out/index.html ]; then
  if [ ! -d web/node_modules ]; then
    echo "run.sh: web/node_modules missing - run make setup once" >&2
    exit 1
  fi
  (cd web && INKFALL_EXPORT=1 ./node_modules/.bin/next build)
fi
exec .venv/bin/python -m uvicorn inkfall.api:create_app --factory --host 127.0.0.1 --port "$PORT"
