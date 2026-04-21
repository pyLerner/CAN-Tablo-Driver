#!/usr/bin/env bash
set -euo pipefail

# Restores project and offline Python/uv environment from bundle.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_DIR="${1:-${SCRIPT_DIR}/workdir/CAN-Tablo-Driver}"
TARGET_DIR="$(mkdir -p "$(dirname "${TARGET_DIR}")" && cd "$(dirname "${TARGET_DIR}")" && pwd)/$(basename "${TARGET_DIR}")"

PROJECT_BUNDLE="${SCRIPT_DIR}/project/project.bundle"
WORKTREE_SNAPSHOT="${SCRIPT_DIR}/project/worktree-snapshot.tar.gz"
DEFAULT_BRANCH_FILE="${SCRIPT_DIR}/meta/default-branch.txt"

UV_TARGET_ROOT="${HOME}/.local/offline-uv"
UV_BIN_DIR="${UV_TARGET_ROOT}/bin"
UV_PYTHON_DIR="${HOME}/.local/share/uv/python"
UV_CACHE_DIR="${HOME}/.cache/uv"

need_file() {
  [[ -f "$1" ]] || {
    echo "ERROR: required file not found: $1"
    exit 1
  }
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "ERROR: '$1' not found in PATH"
    exit 1
  }
}

need_cmd git
need_cmd tar
need_file "${PROJECT_BUNDLE}"
need_file "${WORKTREE_SNAPSHOT}"
need_file "${SCRIPT_DIR}/uv/uv"

echo "==> Restoring uv binary"
mkdir -p "${UV_BIN_DIR}"
cp -a "${SCRIPT_DIR}/uv/uv" "${UV_BIN_DIR}/uv"
if [[ -f "${SCRIPT_DIR}/uv/uvx" ]]; then
  cp -a "${SCRIPT_DIR}/uv/uvx" "${UV_BIN_DIR}/uvx"
fi
chmod +x "${UV_BIN_DIR}/uv" "${UV_BIN_DIR}/uvx" 2>/dev/null || true

# Use bundled uv first in this script.
export PATH="${UV_BIN_DIR}:${PATH}"

echo "==> Restoring uv Python runtimes"
if [[ -d "${SCRIPT_DIR}/uv-python" ]] && [[ -n "$(ls -A "${SCRIPT_DIR}/uv-python" 2>/dev/null || true)" ]]; then
  mkdir -p "${UV_PYTHON_DIR}"
  cp -a "${SCRIPT_DIR}/uv-python/." "${UV_PYTHON_DIR}/"
else
  echo "WARN: uv-python directory in bundle is empty"
fi

echo "==> Restoring uv cache"
if [[ -d "${SCRIPT_DIR}/uv-cache" ]] && [[ -n "$(ls -A "${SCRIPT_DIR}/uv-cache" 2>/dev/null || true)" ]]; then
  mkdir -p "${UV_CACHE_DIR}"
  cp -a "${SCRIPT_DIR}/uv-cache/." "${UV_CACHE_DIR}/"
else
  echo "WARN: uv-cache directory in bundle is empty"
fi

echo "==> Restoring git repository"
if [[ -d "${TARGET_DIR}/.git" ]]; then
  git -C "${TARGET_DIR}" fetch "${PROJECT_BUNDLE}" "refs/*:refs/*"
else
  git clone "${PROJECT_BUNDLE}" "${TARGET_DIR}"
fi

if [[ -f "${DEFAULT_BRANCH_FILE}" ]]; then
  BRANCH="$(<"${DEFAULT_BRANCH_FILE}")"
  git -C "${TARGET_DIR}" checkout "${BRANCH}" || true
fi

echo "==> Applying worktree snapshot (includes donor uncommitted files)"
tar -xzf "${WORKTREE_SNAPSHOT}" -C "${TARGET_DIR}"

echo "==> Detecting Python from restored uv runtimes"
PYTHON_BIN="$(uv python list --only-installed | awk 'NR==1{print $NF}')"
if [[ -z "${PYTHON_BIN}" || ! -x "${PYTHON_BIN}" ]]; then
  # Fallback: search manually in restored uv python dir without extra tools.
  for candidate in "${UV_PYTHON_DIR}"/*/bin/python*; do
    if [[ -x "${candidate}" ]]; then
      PYTHON_BIN="${candidate}"
      break
    fi
  done
fi
if [[ -z "${PYTHON_BIN}" || ! -x "${PYTHON_BIN}" ]]; then
  echo "ERROR: unable to locate restored Python interpreter"
  echo "       Check ${UV_PYTHON_DIR} and set up Python manually."
  exit 1
fi
echo "    Using Python: ${PYTHON_BIN}"

echo "==> Creating virtual environment"
cd "${TARGET_DIR}"
uv venv --python "${PYTHON_BIN}" .venv

echo "==> Offline dependency install"
uv pip sync \
  "${SCRIPT_DIR}/project/requirements-thirdparty.txt" \
  --python "${TARGET_DIR}/.venv/bin/python" \
  --offline

echo "==> Installing local project"
uv pip install \
  --python "${TARGET_DIR}/.venv/bin/python" \
  --offline \
  -e "${TARGET_DIR}"

cat > "${TARGET_DIR}/run_api_server_offline.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${SCRIPT_DIR}/.venv/bin/run_api_server" "$@"
EOF
chmod +x "${TARGET_DIR}/run_api_server_offline.sh"

echo
echo "Restore complete."
echo "Project: ${TARGET_DIR}"
echo "Bundled uv: ${UV_BIN_DIR}/uv"
echo "Activate venv: source \"${TARGET_DIR}/.venv/bin/activate\""
echo "Run API: ${TARGET_DIR}/run_api_server_offline.sh"
