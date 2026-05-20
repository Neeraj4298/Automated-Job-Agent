#!/usr/bin/env bash
# setup.sh — One-shot setup script for the Autonomous Job Application System
# Run: chmod +x setup.sh && ./setup.sh

set -e

echo "════════════════════════════════════════"
echo " Job Agent Setup"
echo "════════════════════════════════════════"

# ── Python version check ─────────────────────────────────────────────────
PYTHON=$(which python3.11 2>/dev/null || which python3 2>/dev/null || echo "")
if [ -z "$PYTHON" ]; then
  echo "❌ Python 3.11+ required. Install it and try again."
  exit 1
fi

PY_VERSION=$($PYTHON --version 2>&1 | awk '{print $2}')
echo "✅ Python: $PY_VERSION"

# ── Virtual environment ──────────────────────────────────────────────────
if [ ! -d ".venv" ]; then
  echo "Creating virtual environment..."
  $PYTHON -m venv .venv
fi
source .venv/bin/activate
echo "✅ Virtual environment activated"

# ── Install dependencies ──────────────────────────────────────────────────
echo "Installing Python dependencies..."
pip install --upgrade pip -q
pip install -r requirements.txt -q
echo "✅ Dependencies installed"

# ── Playwright browser ────────────────────────────────────────────────────
echo "Installing Playwright Chromium browser..."
playwright install chromium
echo "✅ Playwright Chromium installed"

# ── Copy .env template ────────────────────────────────────────────────────
if [ ! -f ".env" ]; then
  cp .env.example .env
  echo ""
  echo "⚠️  .env file created from template."
  echo "   Edit .env with your real values before running the agent."
  echo ""
fi

# ── Run tests ─────────────────────────────────────────────────────────────
echo ""
echo "Running test suite..."
python -m pytest tests/test_timing.py tests/test_qualify.py tests/test_ai_prompts.py -v --tb=short 2>&1 | tail -20
echo ""
echo "════════════════════════════════════════"
echo " Setup complete!"
echo " Next steps:"
echo "  1. Edit .env with your details"
echo "  2. python main.py --dry-run     (test run, no submissions)"
echo "  3. python main.py               (start scheduler)"
echo "════════════════════════════════════════"
