#!/usr/bin/env bash
# Launch the Personal Finance Tracker in your browser.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -x .venv/bin/streamlit ]; then
  echo "Setting up the environment (one time)…"
  python3 -m venv .venv
  .venv/bin/python -m pip install --quiet --index-url https://pypi.org/simple -r requirements.txt
fi

exec .venv/bin/streamlit run app.py \
  --server.headless false \
  --browser.gatherUsageStats false
