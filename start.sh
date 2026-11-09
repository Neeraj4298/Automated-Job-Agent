#!/usr/bin/env bash
# start.sh — Single-command launcher for AetherApply (Database + Backend API + Frontend UI)
# Usage:
#   ./start.sh               -> Starts SQLite DB + Backend REST API + Frontend Web UI on port 8080
#   ./start.sh --docker      -> Starts full stack via Docker Compose
#   PORT=3000 ./start.sh     -> Starts on custom port

set -e

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8080}"

if [ ! -f ".env" ] && [ -f ".env.example" ]; then
  cp .env.example .env
  echo "✅ Created .env from .env.example"
fi

if [ "${1:-}" = "--docker" ]; then
  echo "🚀 Launching AetherApply stack via Docker Compose..."
  exec docker compose up --build
fi

# Activate virtualenv if present
if [ -f ".venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  source ".venv/bin/activate"
fi

PYTHON_BIN="$(command -v python3 || command -v python)"

echo "════════════════════════════════════════════════════════════════"
echo "  AetherApply — Autonomous AI Job Application Console"
echo "  • Database : SQLite (applied_jobs.db — auto-initialized)"
echo "  • Backend  : REST API + Agent Telemetry Bridge"
echo "  • Frontend : Obsidian Dark & Alabaster Light UI"
echo "  • URL      : http://127.0.0.1:${PORT}"
echo "════════════════════════════════════════════════════════════════"

exec "$PYTHON_BIN" server.py --host "$HOST" --port "$PORT"
