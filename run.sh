#!/usr/bin/env bash
# Start the bridge and the web UI together. Ctrl-C stops both.
set -euo pipefail
cd "$(dirname "$0")"

[ -f .env ] && { set -a; . ./.env; set +a; }

PORT_BRIDGE="${PORT_BRIDGE:-8000}"
PORT_WEB="${PORT_WEB:-3000}"

python3 -m uvicorn firehose.server:app --host 127.0.0.1 --port "$PORT_BRIDGE" &
BRIDGE=$!
trap 'kill $BRIDGE 2>/dev/null || true' EXIT INT TERM

cd web
[ -d node_modules ] || npm install
FIREHOSE_BRIDGE="http://127.0.0.1:$PORT_BRIDGE" npm run dev -- --port "$PORT_WEB"
