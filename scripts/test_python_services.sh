#!/usr/bin/env bash
set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PY:-${RAIZ}/.venv/bin/python}"

cd "$RAIZ"

if [ ! -x "$PY" ]; then
  python3 -m venv .venv
  PY="${RAIZ}/.venv/bin/python"
fi

"$PY" -m pip install -q \
  -r servicos/auth/requirements.txt -r servicos/auth/requirements-dev.txt \
  -r servicos/data/requirements.txt -r servicos/data/requirements-dev.txt \
  -r servicos/transform/requirements.txt -r servicos/transform/requirements-dev.txt

./scripts/gen_protos.sh "$PY"

PYTHONPATH=servicos/auth "$PY" -m pytest servicos/auth/tests -q
PYTHONPATH=servicos/data "$PY" -m pytest servicos/data/tests -q
PYTHONPATH=servicos/transform "$PY" -m pytest servicos/transform/tests -q
