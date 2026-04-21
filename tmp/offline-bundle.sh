#!/usr/bin/env bash
set -euo pipefail

PYTHON_VERSION="${PYTHON_VERSION:-3.11}"
TARGET_PLATFORM="${TARGET_PLATFORM:-manylinux2014_aarch64}"
TARGET_PYTHON_TAG="${TARGET_PYTHON_TAG:-cp311}"
TARGET_UV_ASSET="${TARGET_UV_ASSET:-uv-aarch64-unknown-linux-gnu.tar.gz}"
TARGET_PYTHON_ARCH="${TARGET_PYTHON_ARCH:-aarch64-unknown-linux-gnu}"
STRICT_WHEELS="${STRICT_WHEELS:-0}"
PROJECT_DIR="${1:-.}"
BUNDLE_DIR="${BUNDLE_DIR:-offline-bundle}"

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "ERROR: '$1' не найден в PATH"
    exit 1
  }
}

need_cmd uv
need_cmd curl
need_cmd tar
need_cmd git
need_cmd python3
need_cmd zstd

PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd)"
BUNDLE_DIR_ABS="${PROJECT_DIR}/${BUNDLE_DIR}"
ARCHIVE_PATH="${PROJECT_DIR}/${BUNDLE_DIR}.tar.gz"

echo "==> Создание офлайн-бандла для RK3588/aarch64"
echo "    PROJECT_DIR=${PROJECT_DIR}"
echo "    PYTHON_VERSION=${PYTHON_VERSION}"
echo "    TARGET_PLATFORM=${TARGET_PLATFORM}"
echo "    TARGET_PYTHON_TAG=${TARGET_PYTHON_TAG}"
echo "    STRICT_WHEELS=${STRICT_WHEELS}"

rm -rf "$BUNDLE_DIR_ABS" "$ARCHIVE_PATH"
mkdir -p \
  "$BUNDLE_DIR_ABS"/{python,uv,wheels,src,meta,tmp}

resolve_latest_asset_url() {
  local repo="$1"
  local regex="$2"
  python3 - "$repo" "$regex" <<'PY'
import json
import re
import sys
import urllib.request

repo = sys.argv[1]
pattern = re.compile(sys.argv[2])
api = f"https://api.github.com/repos/{repo}/releases/latest"
with urllib.request.urlopen(api, timeout=30) as r:
    payload = json.load(r)

for asset in payload.get("assets", []):
    url = asset.get("browser_download_url", "")
    name = asset.get("name", "")
    if pattern.search(name) or pattern.search(url):
        print(url)
        sys.exit(0)
sys.exit(1)
PY
}

echo "==> Экспорт зависимостей из uv.lock/pyproject"
uv export \
  --directory "$PROJECT_DIR" \
  --format requirements-txt \
  --no-hashes \
  -o "$BUNDLE_DIR_ABS/requirements.txt"

# Убираем editable-запись проекта (-e .), чтобы download тянул только внешние зависимости.
python3 - "$BUNDLE_DIR_ABS/requirements.txt" "$BUNDLE_DIR_ABS/requirements-thirdparty.txt" <<'PY'
import pathlib
import sys

src = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
dst = []
for line in src:
    stripped = line.strip()
    if stripped in {"-e .", ".", ""}:
        continue
    dst.append(line)
pathlib.Path(sys.argv[2]).write_text("\n".join(dst) + "\n", encoding="utf-8")
PY

echo "==> Скачивание python-build-standalone для aarch64"
if [[ -z "${PYTHON_BUILD_URL:-}" ]]; then
  PYTHON_BUILD_URL="$(
    resolve_latest_asset_url \
      "astral-sh/python-build-standalone" \
      "cpython-${PYTHON_VERSION}.*${TARGET_PYTHON_ARCH}.*install_only.*\\.tar\\.zst$"
  )" || {
    echo "ERROR: не удалось подобрать python-build-standalone автоматически."
    echo "       Укажите вручную:"
    echo "       export PYTHON_BUILD_URL='https://github.com/...tar.zst'"
    exit 1
  }
fi
echo "    PYTHON_BUILD_URL=${PYTHON_BUILD_URL}"
curl -fL --retry 3 --retry-delay 2 "$PYTHON_BUILD_URL" \
  -o "$BUNDLE_DIR_ABS/tmp/python-build.tar.zst"
tar -I zstd -xf "$BUNDLE_DIR_ABS/tmp/python-build.tar.zst" \
  -C "$BUNDLE_DIR_ABS/python" --strip-components=1
chmod +x "$BUNDLE_DIR_ABS/python/bin/python"

echo "==> Скачивание uv для Linux aarch64"
if [[ -z "${UV_URL:-}" ]]; then
  UV_URL="$(
    resolve_latest_asset_url \
      "astral-sh/uv" \
      "${TARGET_UV_ASSET}$"
  )" || {
    echo "ERROR: не удалось подобрать uv asset автоматически."
    echo "       Укажите вручную:"
    echo "       export UV_URL='https://github.com/astral-sh/uv/releases/download/.../${TARGET_UV_ASSET}'"
    exit 1
  }
fi
echo "    UV_URL=${UV_URL}"
curl -fL --retry 3 --retry-delay 2 "$UV_URL" -o "$BUNDLE_DIR_ABS/tmp/uv.tar.gz"
tar -xzf "$BUNDLE_DIR_ABS/tmp/uv.tar.gz" -C "$BUNDLE_DIR_ABS/uv" --strip-components=1
chmod +x "$BUNDLE_DIR_ABS/uv/uv" "$BUNDLE_DIR_ABS/uv/uvx" || true

echo "==> Загрузка wheels для ${TARGET_PLATFORM} (${TARGET_PYTHON_TAG})"
UV_DOWNLOAD_ARGS=()
if [[ "$STRICT_WHEELS" == "1" ]]; then
  # Fail-fast: запрещаем source distributions, чтобы на target не понадобилась сборка.
  UV_DOWNLOAD_ARGS+=(--only-binary=:all:)
fi

uv pip download \
  --python-platform "$TARGET_PLATFORM" \
  --python-version "$TARGET_PYTHON_TAG" \
  --dest "$BUNDLE_DIR_ABS/wheels" \
  "${UV_DOWNLOAD_ARGS[@]}" \
  -r "$BUNDLE_DIR_ABS/requirements-thirdparty.txt"

if [[ "$STRICT_WHEELS" == "1" ]]; then
  if rg --files "$BUNDLE_DIR_ABS/wheels" | rg -v '\.whl$' >/dev/null; then
    echo "ERROR: в strict-режиме найдены не-wheel артефакты в wheels/."
    echo "       Удалите проблемные пакеты или зафиксируйте версии с готовыми aarch64 wheels."
    exit 1
  fi
fi

echo "==> Экспорт исходников и веток git"
if git -C "$PROJECT_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git -C "$PROJECT_DIR" bundle create "$BUNDLE_DIR_ABS/src/project.bundle" --all
  git -C "$PROJECT_DIR" rev-parse --abbrev-ref HEAD > "$BUNDLE_DIR_ABS/meta/default-branch.txt"
  git -C "$PROJECT_DIR" status --porcelain > "$BUNDLE_DIR_ABS/meta/dirty-status.txt" || true
else
  echo "WARN: '$PROJECT_DIR' не git-репозиторий, копирую как есть."
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
PYTHON_BIN="${SCRIPT_DIR}/python/bin/python"
UV_BIN="${SCRIPT_DIR}/uv/uv"
DEFAULT_BRANCH_FILE="${SCRIPT_DIR}/meta/default-branch.txt"

mkdir -p "$WORK_DIR"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "ERROR: Python не найден: $PYTHON_BIN"
  exit 1
fi

if [[ ! -x "$UV_BIN" ]]; then
  echo "ERROR: uv не найден: $UV_BIN"
  exit 1
fi

echo "==> Восстановление исходников проекта"
if [[ -f "${SCRIPT_DIR}/src/project.bundle" ]]; then
  if [[ -d "${PROJECT_DIR}/.git" ]]; then
    echo "    Репозиторий уже есть: ${PROJECT_DIR}, обновляю refs из bundle"
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
  echo "ERROR: исходники не найдены в bundle"
  exit 1
fi

echo "==> Создание виртуального окружения"
cd "$PROJECT_DIR"
"$UV_BIN" venv --python "$PYTHON_BIN" .venv

echo "==> Установка зависимостей (строго офлайн)"
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

echo
echo "Готово."
echo "Проект: $PROJECT_DIR"
echo "Активация: source \"$PROJECT_DIR/.venv/bin/activate\""
EOF
chmod +x "$BUNDLE_DIR_ABS/restore.sh"

cat > "$BUNDLE_DIR_ABS/README.offline.md" <<EOF
# Offline bundle (amd64 -> RK3588 aarch64)

Состав:
- \`python/\` — standalone Python ${PYTHON_VERSION} для Linux aarch64
- \`uv/\` — \`uv\` и \`uvx\` для Linux aarch64
- \`wheels/\` — офлайн-зависимости (manylinux2014_aarch64, ${TARGET_PYTHON_TAG})
- \`src/project.bundle\` — git bundle со всеми ветками и тегами (\`--all\`)
- \`restore.sh\` — скрипт восстановления на целевой машине

Переменная \`STRICT_WHEELS\` при сборке:
- \`0\` (по умолчанию) — допускает обычное поведение резолвера.
- \`1\` — fail-fast, только готовые \`.whl\`, без source dist.

## Использование на целевой машине (без интернета)

\`\`\`bash
tar xzf ${BUNDLE_DIR}.tar.gz
cd ${BUNDLE_DIR}
./restore.sh
\`\`\`

По умолчанию проект будет восстановлен в \`./workdir/CAN-Tablo-Driver\`.
Путь можно поменять через \`WORK_DIR\` и \`PROJECT_NAME\`.
EOF

rm -rf "$BUNDLE_DIR_ABS/tmp"

echo "==> Упаковка архива"
tar -czf "$ARCHIVE_PATH" -C "$PROJECT_DIR" "$BUNDLE_DIR"

echo
echo "Готово: $ARCHIVE_PATH"
echo "Перенесите архив на RK3588 и выполните:"
echo "  tar xzf ${BUNDLE_DIR}.tar.gz && cd ${BUNDLE_DIR} && ./restore.sh"