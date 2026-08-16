#!/usr/bin/env bash
# Launch the Personal Finance Tracker in your browser, setting up the
# environment on first run. Safe to run on a machine that has never seen it.
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PFT_PYTHON:-python3}"

if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "Python 3 not found. Install it (python.org, or 'brew install python')," >&2
  echo "or point PFT_PYTHON at an interpreter: PFT_PYTHON=/path/to/python3 ./run.sh" >&2
  exit 1
fi

# Streamlit and pandas both need 3.9 or newer.
if ! "$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)'; then
  echo "Python 3.9 or newer is required; found $("$PYTHON" --version 2>&1)." >&2
  echo "Point PFT_PYTHON at a newer interpreter: PFT_PYTHON=python3.12 ./run.sh" >&2
  exit 1
fi

if [ ! -x .venv/bin/streamlit ]; then
  echo "Setting up the environment (one time, ~1 minute)…"
  "$PYTHON" -m venv .venv

  # Default to upstream PyPI. A work machine may point PIP_INDEX_URL at a
  # corporate mirror that is unreachable off-VPN, which would fail confusingly;
  # set PFT_PIP_INDEX to use your own mirror instead.
  INDEX="${PFT_PIP_INDEX:-https://pypi.org/simple}"
  if ! .venv/bin/python -m pip install --quiet --index-url "$INDEX" -r requirements.txt; then
    echo >&2
    echo "Could not install dependencies from $INDEX." >&2
    echo "If you are behind a proxy or need a mirror, retry with:" >&2
    echo "  PFT_PIP_INDEX=<your-index-url> ./run.sh" >&2
    rm -rf .venv
    exit 1
  fi
fi

exec .venv/bin/streamlit run app.py \
  --server.headless false \
  --browser.gatherUsageStats false
