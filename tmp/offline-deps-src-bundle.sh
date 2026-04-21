#!/usr/bin/env bash
set -euo pipefail

# Формирует архив ТОЛЬКО с зависимостями и исходниками (со всеми ветками),
# без упаковки uv и Python runtime.
# Целевая машина: есть uv и Python 3.13 aarch64.

PROJECT_DIR="${1:-.}"
PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd)"

BUNDLE_DIR="${BUNDLE_DIR:-offline-deps-src-bundle}"
BUNDLE_DIR_ABS="${PROJECT_DIR}/${BUNDLE_DIR}"
ARCHIVE_PATH="${PROJECT_DIR}/${BUNDLE_DIR}.tar.gz"

TARGET_PLATFORM="${TARGET_PLATFORM:-manylinux2014_aarch64}"
TARGET_PYTHON_TAG="${TARGET_PYTHON_TAG:-cp313}"
STRICT_WHEELS="${STRICT_WHEELS:-1}"

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "ERROR: '$1' не найден в PATH"
    exit 1
  }
}

need_cmd uv
need_cmd git
need_cmd tar
need_cmd python3

echo "==> Сборка архива зависимостей и исходников"
echo "    PROJECT_DIR=${PROJECT_DIR}"
echo "    TARGET_PLATFORM=${TARGET_PLATFORM}"
echo "    TARGET_PYTHON_TAG=${TARGET_PYTHON_TAG}"
echo "    STRICT_WHEELS=${STRICT_WHEELS}"

rm -rf "$BUNDLE_DIR_ABS" "$ARCHIVE_PATH"
mkdir -p "$BUNDLE_DIR_ABS"/{wheels,src,meta}

echo "==> Экспорт зависимостей"
uv export \
  --directory "$PROJECT_DIR" \
  --format requirements-txt \
  --no-hashes \
  -o "$BUNDLE_DIR_ABS/requirements.txt"

python3 - "$BUNDLE_DIR_ABS/requirements.txt" "$BUNDLE_DIR_ABS/requirements-thirdparty.txt" <<'PY'
import pathlib
import sys

src = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
dst = []
for line in src:
    stripped = line.strip()
    if stripped in {"-e .", ".", ""}:
        continue
    if stripped.startswith("nuitka=="):
        continue
    dst.append(line)
pathlib.Path(sys.argv[2]).write_text("\n".join(dst) + "\n", encoding="utf-8")
PY

echo "==> Загрузка wheels для ${TARGET_PLATFORM} (${TARGET_PYTHON_TAG})"
UV_DOWNLOAD_ARGS=()
if [[ "$STRICT_WHEELS" == "1" ]]; then
  UV_DOWNLOAD_ARGS+=(--only-binary=:all:)
fi

if [[ "$TARGET_PYTHON_TAG" =~ ^cp([0-9])([0-9]{2})$ ]]; then
  TARGET_PYTHON_VERSION="${BASH_REMATCH[1]}.${BASH_REMATCH[2]}"
else
  TARGET_PYTHON_VERSION="3.13"
fi

set +e
uv pip download --help >/dev/null 2>&1
UV_HAS_DOWNLOAD_RC=$?
set -e

if [[ $UV_HAS_DOWNLOAD_RC -eq 0 ]]; then
  set +e
  UV_DOWNLOAD_OUTPUT="$(
    uv pip download \
      --python-platform "$TARGET_PLATFORM" \
      --python-version "$TARGET_PYTHON_TAG" \
      --dest "$BUNDLE_DIR_ABS/wheels" \
      "${UV_DOWNLOAD_ARGS[@]}" \
      -r "$BUNDLE_DIR_ABS/requirements-thirdparty.txt" 2>&1
  )"
  UV_DOWNLOAD_RC=$?
  set -e
else
  UV_DOWNLOAD_OUTPUT="uv pip download unavailable, using python -m pip download"
  UV_DOWNLOAD_RC=99
fi

if [[ $UV_DOWNLOAD_RC -ne 0 ]]; then
  set +e
  python3 -m pip --version >/dev/null 2>&1
  PIP_AVAILABLE_RC=$?
  set -e

  if [[ $PIP_AVAILABLE_RC -ne 0 ]]; then
    set +e
    ENSUREPIP_OUTPUT="$(python3 -m ensurepip --upgrade 2>&1)"
    ENSUREPIP_RC=$?
    set -e
    if [[ $ENSUREPIP_RC -ne 0 ]]; then
      echo "$ENSUREPIP_OUTPUT"
      exit "$ENSUREPIP_RC"
    fi
  fi

  set +e
  PIP_DOWNLOAD_OUTPUT="$(
    python3 -m pip download \
      --dest "$BUNDLE_DIR_ABS/wheels" \
      --platform "$TARGET_PLATFORM" \
      --implementation cp \
      --python-version "$TARGET_PYTHON_VERSION" \
      --abi "$TARGET_PYTHON_TAG" \
      "${UV_DOWNLOAD_ARGS[@]}" \
      -r "$BUNDLE_DIR_ABS/requirements-thirdparty.txt" 2>&1
  )"
  PIP_DOWNLOAD_RC=$?
  set -e

  if [[ $PIP_DOWNLOAD_RC -ne 0 ]]; then
    echo "$UV_DOWNLOAD_OUTPUT"
    echo "$PIP_DOWNLOAD_OUTPUT"
    exit "$PIP_DOWNLOAD_RC"
  fi
fi

if [[ "$STRICT_WHEELS" == "1" ]]; then
  if rg --files "$BUNDLE_DIR_ABS/wheels" | rg -v '\.whl$' >/dev/null; then
    echo "ERROR: strict-режим: найдены не-wheel артефакты."
    exit 1
  fi
fi

echo "==> Экспорт исходников со всеми ветками"
if git -C "$PROJECT_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git -C "$PROJECT_DIR" bundle create "$BUNDLE_DIR_ABS/src/project.bundle" --all
  git -C "$PROJECT_DIR" rev-parse --abbrev-ref HEAD > "$BUNDLE_DIR_ABS/meta/default-branch.txt"
else
  echo "WARN: '$PROJECT_DIR' не git-репозиторий, копирую дерево проекта."
  cp -a "$PROJECT_DIR" "$BUNDLE_DIR_ABS/src/project-copy"
fi

[[ -f "$PROJECT_DIR/pyproject.toml" ]] && cp "$PROJECT_DIR/pyproject.toml" "$BUNDLE_DIR_ABS/"
[[ -f "$PROJECT_DIR/uv.lock" ]] && cp "$PROJECT_DIR/uv.lock" "$BUNDLE_DIR_ABS/"

cat > "$BUNDLE_DIR_ABS/restore.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK_DIR="${WORK_DIR:-$SCRIPT_DIR/workdir}"
PROJECT_NAME="${PROJECT_NAME:-CAN-Tablo-Driver}"
PROJECT_DIR="${WORK_DIR}/${PROJECT_NAME}"

# По умолчанию используем Python, который вы указали:
# ~/.local/share/uv/python/cpython-3.13-linux-aarch64-gnu/bin/python3.13
TARGET_PYTHON="${TARGET_PYTHON:-$HOME/.local/share/uv/python/cpython-3.13-linux-aarch64-gnu/bin/python3.13}"
UV_BIN="${UV_BIN:-uv}"
DEFAULT_BRANCH_FILE="${SCRIPT_DIR}/meta/default-branch.txt"

command -v "$UV_BIN" >/dev/null 2>&1 || {
  echo "ERROR: uv не найден. Укажите UV_BIN=/path/to/uv"
  exit 1
}

if [[ ! -x "$TARGET_PYTHON" ]]; then
  echo "ERROR: Python не найден: $TARGET_PYTHON"
  echo "       Укажите TARGET_PYTHON=/path/to/python3.13"
  exit 1
fi

mkdir -p "$WORK_DIR"

echo "==> Восстановление исходников"
if [[ -f "${SCRIPT_DIR}/src/project.bundle" ]]; then
  if [[ -d "${PROJECT_DIR}/.git" ]]; then
    git -C "$PROJECT_DIR" fetch "${SCRIPT_DIR}/src/project.bundle" "refs/*:refs/*"
  else
    git clone "${SCRIPT_DIR}/src/project.bundle" "$PROJECT_DIR"
  fi
  if [[ -f "$DEFAULT_BRANCH_FILE" ]]; then
    BRANCH="$(cat "$DEFAULT_BRANCH_FILE")"
    git -C "$PROJECT_DIR" checkout "$BRANCH" || true
  fi
elif [[ -d "${SCRIPT_DIR}/src/project-copy" ]]; then
  rm -rf "$PROJECT_DIR"
  cp -a "${SCRIPT_DIR}/src/project-copy" "$PROJECT_DIR"
else
  echo "ERROR: исходники не найдены."
  exit 1
fi

echo "==> Создание venv через uv"
cd "$PROJECT_DIR"
"$UV_BIN" venv --python "$TARGET_PYTHON" .venv

echo "==> Установка зависимостей строго офлайн"
"$UV_BIN" pip sync \
  "$SCRIPT_DIR/requirements-thirdparty.txt" \
  --python "$PROJECT_DIR/.venv/bin/python" \
  --no-index \
  --find-links "$SCRIPT_DIR/wheels"

echo "==> Установка локального проекта"
"$UV_BIN" pip install \
  --python "$PROJECT_DIR/.venv/bin/python" \
  --no-index \
  --find-links "$SCRIPT_DIR/wheels" \
  -e "$PROJECT_DIR"

cat > "$PROJECT_DIR/run_api_server_offline.sh" <<'RUN_EOF'
#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/.venv/bin/run_api_server" "$@"
RUN_EOF
chmod +x "$PROJECT_DIR/run_api_server_offline.sh"

echo
echo "Готово."
echo "Проект: $PROJECT_DIR"
echo "Активация: source \"$PROJECT_DIR/.venv/bin/activate\""
echo "Офлайн-запуск API: \"$PROJECT_DIR/run_api_server_offline.sh\""
EOF
chmod +x "$BUNDLE_DIR_ABS/restore.sh"

cat > "$BUNDLE_DIR_ABS/README.offline.md" <<EOF
# Offline deps+src bundle (amd64 -> RK3588 aarch64)

Состав:
- \`wheels/\` — зависимости как wheel для \`${TARGET_PLATFORM}\` + \`${TARGET_PYTHON_TAG}\`
- \`requirements.txt\` и \`requirements-thirdparty.txt\`
- \`src/project.bundle\` — git bundle со всеми ветками/тегами (\`--all\`)
- \`restore.sh\` — восстановление проекта и офлайн-установка

## На целевой машине

Ожидается:
- \`uv\` в PATH
- Python: \`~/.local/share/uv/python/cpython-3.13-linux-aarch64-gnu/bin/python3.13\`
  (или передайте \`TARGET_PYTHON=/другой/python3.13\`)

\`\`\`bash
tar xzf ${BUNDLE_DIR}.tar.gz
cd ${BUNDLE_DIR}
./restore.sh
\`\`\`

Запуск API на целевой машине:

\`\`\`bash
./workdir/CAN-Tablo-Driver/run_api_server_offline.sh
\`\`\`

Важно: для офлайн-режима не используйте \`uv run run_api_server\`, он может попытаться выполнить sync/resolve через индекс.
EOF

echo "==> Упаковка"
tar -czf "$ARCHIVE_PATH" -C "$PROJECT_DIR" "$BUNDLE_DIR"

echo
echo "Готово: $ARCHIVE_PATH"
echo "Перенесите архив на target и выполните: tar xzf ${BUNDLE_DIR}.tar.gz && cd ${BUNDLE_DIR} && ./restore.sh"

