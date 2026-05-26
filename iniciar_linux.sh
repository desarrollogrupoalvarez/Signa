#!/usr/bin/env bash
set -e

echo "============================================================"
echo " Signa — Remitos"
echo "============================================================"

python3 --version >/dev/null 2>&1 || { echo "ERROR: Python3 requerido"; exit 1; }

VENV="backend/venv"
[ -d "$VENV" ] || python3 -m venv "$VENV"
source "$VENV/bin/activate"

pip install -q -r backend/requirements.txt

mkdir -p datos/Bandeja_Entrada datos/Remitos_Firmados logs
[ -f .env ] || cp .env.example .env

echo ""
echo "Iniciando servidor en http://0.0.0.0:5000"
echo ""
cd backend
python server.py
