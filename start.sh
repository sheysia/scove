#!/usr/bin/env bash
# SCove — start the web server.
#
# Usage:
#   ./start.sh              localhost:8787 (local only)
#   ./start.sh --remote     0.0.0.0:8787 + Tailscale Serve hint

set -euo pipefail
cd "$(dirname "$0")"

export V_ROOT="${V_ROOT:-$HOME/V}"
export VHOME_ROOT="${VHOME_ROOT:-$HOME/V/VHome}"

HOST="127.0.0.1"
PORT="8787"

if [[ "${1:-}" == "--remote" ]]; then
  HOST="0.0.0.0"
  echo ""
  echo "  SCove remote mode: binding $HOST:$PORT"
  echo ""
  echo "  To expose via Tailscale (private, no public internet):"
  echo "    tailscale serve --bg $PORT"
  echo ""
  echo "  Then open https://$(hostname).tail-scale-dns:443 on your phone."
  echo "  To stop: tailscale serve --bg off"
  echo ""
fi

echo "SCove starting on http://${HOST}:${PORT}"
exec ./.venv/bin/uvicorn backend.app:app \
  --host "$HOST" \
  --port "$PORT" \
  --no-access-log
