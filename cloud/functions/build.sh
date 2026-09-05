#!/bin/sh
# Firebase deploys this directory on its own, so the strategy modules are
# copied in rather than imported from the repo root. Run before every deploy.
# The CLI also needs a venv here to discover the functions; made once.
set -e
cd "$(dirname "$0")"
for f in book.py features.py regime.py signals.py; do cp "../../$f" .; done
echo "copied: book features regime signals"
if [ ! -d venv ]; then
  python3 -m venv venv && venv/bin/pip install -q -r requirements.txt
  echo "venv created"
fi
