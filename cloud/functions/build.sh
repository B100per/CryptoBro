#!/bin/sh
# Firebase deploys this directory on its own, so the strategy modules are
# copied in rather than imported from the repo root. Run before every deploy.
set -e
cd "$(dirname "$0")"
for f in book.py features.py regime.py signals.py; do cp "../../$f" .; done
echo "copied: book features regime signals"
