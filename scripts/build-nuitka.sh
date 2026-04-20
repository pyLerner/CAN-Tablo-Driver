#!/usr/bin/env bash
# Сборка onefile standalone для проекта CAN-Tablo-Driver.
# Результат: dist/CAN-Tablo-Driver/can-tablo-driver.bin
#
# Запуск:
#   bash scripts/build-nuitka.sh
# Переопределение директории:
#   OUT_DIR=/abs/path bash scripts/build-nuitka.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_ROOT_NAME="$(basename "$ROOT")"
DIST_DIR_NAME="${DIST_DIR_NAME:-$PROJECT_ROOT_NAME}"
BIN_NAME="${BIN_NAME:-can-tablo-driver.bin}"
OUT_DIR="${OUT_DIR:-$ROOT/dist/$DIST_DIR_NAME}"

mkdir -p "$OUT_DIR"

cd "$ROOT"

# Nuitka находится в dev-группе pyproject.toml, поэтому нужен --dev.
uv sync --dev

# Сборка запускается из src/, чтобы импорты main.py были как при обычном run.
cd "$ROOT/src"
uv run python -m nuitka \
  --standalone \
  --onefile \
  --assume-yes-for-downloads \
  --output-dir="$OUT_DIR" \
  --output-filename="$BIN_NAME" \
  --include-package=fastapi \
  --include-package=uvicorn \
  --include-package=pydantic \
  --include-package=can \
  --include-package=isotp \
  --include-package=tomli_w \
  --include-package=PIL \
  --nofollow-import-to='*.tests' \
  --nofollow-import-to='*.test' \
  --nofollow-import-to=unittest \
  --nofollow-import-to=pytest \
  --nofollow-import-to=doctest \
  --remove-output \
  main.py

echo "OK: $OUT_DIR/$BIN_NAME"
ls -lh "$OUT_DIR/$BIN_NAME"