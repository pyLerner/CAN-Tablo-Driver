#!/usr/bin/env bash
set -euo pipefail

# Restores project and offline Python/uv environment from bundle.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_DIR="${1:-${SCRIPT_DIR}/workdir/CAN-Tablo-Driver}"
TARGET_DIR="$(mkdir -p "$(dirname "${TARGET_DIR}")" && cd "$(dirname "${TARGET_DIR}")" && pwd)/$(basename "${TARGET_DIR}")"

PROJECT_BUNDLE="${SCRIPT_DIR}/project/project.bundle"
WORKTREE_SNAPSHOT="${SCRIPT_DIR}/project/worktree-snapshot.tar.gz"
DEFAULT_BRANCH_FILE="${SCRIPT_DIR}/meta/default-branch.txt"
PYTHON_RUNTIME_NAME_FILE="${SCRIPT_DIR}/meta/python-runtime-name.txt"

UV_TARGET_ROOT="${HOME}/.local/offline-uv"
UV_BIN_DIR="${UV_TARGET_ROOT}/bin"
SYSTEMD_DIR="/etc/systemd/system"

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

echo "==> Selecting uv binary"
PREFERRED_UV="${HOME}/.local/bin/uv"
if [[ -x "${PREFERRED_UV}" ]]; then
  echo "    Using target uv: ${PREFERRED_UV}"
  export PATH="${HOME}/.local/bin:${PATH}"
else
  echo "    Target uv not found, restoring bundled uv"
  mkdir -p "${UV_BIN_DIR}"
  cp -a "${SCRIPT_DIR}/uv/uv" "${UV_BIN_DIR}/uv"
  if [[ -f "${SCRIPT_DIR}/uv/uvx" ]]; then
    cp -a "${SCRIPT_DIR}/uv/uvx" "${UV_BIN_DIR}/uvx"
  fi
  chmod +x "${UV_BIN_DIR}/uv" "${UV_BIN_DIR}/uvx" 2>/dev/null || true
  export PATH="${UV_BIN_DIR}:${PATH}"
fi
UV_PYTHON_DIR="$(uv python dir)"
UV_CACHE_DIR="$(uv cache dir)"

echo "==> Restoring uv Python runtimes"
if [[ -d "${SCRIPT_DIR}/uv-python" ]] && [[ -n "$(ls -A "${SCRIPT_DIR}/uv-python" 2>/dev/null || true)" ]]; then
  mkdir -p "${UV_PYTHON_DIR}"
  cp -a "${SCRIPT_DIR}/uv-python/." "${UV_PYTHON_DIR}/"
else
  echo "WARN: uv-python directory in bundle is empty"
fi

# Fix absolute symlinks that may point to donor machine paths.
python3 - "${UV_PYTHON_DIR}" <<'PY'
import os
import pathlib
import sys

root = pathlib.Path(sys.argv[1]).expanduser()
if not root.exists():
    sys.exit(0)

for path in root.rglob("*"):
    if not path.is_symlink():
        continue
    try:
        target = os.readlink(path)
    except OSError:
        continue
    if not target.startswith("/"):
        continue
    marker = "/.local/share/uv/python/"
    if marker not in target:
        continue
    suffix = target.split(marker, 1)[1]
    local_target = root / suffix
    if local_target.exists():
        rel = os.path.relpath(local_target, path.parent)
        path.unlink()
        path.symlink_to(rel)
PY

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

echo "==> Detecting required Python from uv runtimes"
PYTHON_VERSION_REQ=""
if [[ -f "${TARGET_DIR}/.python-version" ]]; then
  PYTHON_VERSION_REQ="$(tr -d '[:space:]' < "${TARGET_DIR}/.python-version")"
fi
if [[ -z "${PYTHON_VERSION_REQ}" ]]; then
  echo "ERROR: .python-version not found or empty in ${TARGET_DIR}"
  exit 1
fi
echo "    Required version: ${PYTHON_VERSION_REQ}"

if [[ -f "${PYTHON_RUNTIME_NAME_FILE}" ]]; then
  PY_RUNTIME_NAME="$(tr -d '[:space:]' < "${PYTHON_RUNTIME_NAME_FILE}")"
  if [[ -n "${PY_RUNTIME_NAME}" ]]; then
    echo "    Restored runtime: ${PY_RUNTIME_NAME}"
  fi
fi

PYTHON_BIN="$(
  uv python list "${PYTHON_VERSION_REQ}" --only-installed 2>/dev/null \
  | awk '{for(i=1;i<=NF;i++) if($i ~ /\/bin\/python([0-9.]*)?$/){print $i; exit}}'
)"
if [[ -z "${PYTHON_BIN}" || ! -x "${PYTHON_BIN}" ]]; then
  echo "ERROR: uv does not see required Python ${PYTHON_VERSION_REQ} after restore"
  echo "       uv python dir: ${UV_PYTHON_DIR}"
  echo "       Available in uv list:"
  uv python list --only-installed || true
  exit 1
fi
echo "    Using Python: ${PYTHON_BIN}"

PYTHON_MM="$(python3 - "${PYTHON_VERSION_REQ}" <<'PY'
import re
import sys
v = sys.argv[1].strip()
m = re.match(r'^(\d+\.\d+)', v)
print(m.group(1) if m else v)
PY
)"
if [[ -n "${PYTHON_MM}" ]]; then
  mkdir -p "${HOME}/.local/bin"
  ln -sfn "${PYTHON_BIN}" "${HOME}/.local/bin/python${PYTHON_MM}"
fi

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

run_systemctl() {
  if [[ "${EUID}" -eq 0 ]]; then
    systemctl "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo systemctl "$@"
  else
    echo "ERROR: systemd setup requires root or sudo"
    exit 1
  fi
}

copy_unit() {
  local src="$1"
  local dst="$2"
  if [[ ! -f "${src}" ]]; then
    return 1
  fi
  if [[ "${EUID}" -eq 0 ]]; then
    install -m 644 "${src}" "${dst}"
  elif command -v sudo >/dev/null 2>&1; then
    sudo install -m 644 "${src}" "${dst}"
  else
    echo "ERROR: cannot install ${src} without root/sudo"
    exit 1
  fi
}

echo "==> Installing systemd units (if present)"
INSTALLED_ANY_UNIT=0
if copy_unit "${SCRIPT_DIR}/systemd/can0-setup.service" "${SYSTEMD_DIR}/can0-setup.service"; then
  INSTALLED_ANY_UNIT=1
fi
if copy_unit "${SCRIPT_DIR}/systemd/led-tablo.service" "${SYSTEMD_DIR}/led-tablo.service"; then
  INSTALLED_ANY_UNIT=1
fi

if [[ "${INSTALLED_ANY_UNIT}" -eq 1 ]]; then
  run_systemctl daemon-reload
  if [[ -f "${SCRIPT_DIR}/systemd/can0-setup.service" ]]; then
    run_systemctl enable can0-setup.service
    run_systemctl restart can0-setup.service
  fi
  if [[ -f "${SCRIPT_DIR}/systemd/led-tablo.service" ]]; then
    run_systemctl enable led-tablo.service
    run_systemctl restart led-tablo.service
  fi
  run_systemctl --no-pager --full status can0-setup.service led-tablo.service || true
else
  echo "WARN: no service unit files found in ${SCRIPT_DIR}/systemd"
fi

echo
echo "Restore complete."
echo "Project: ${TARGET_DIR}"
echo "Bundled uv: ${UV_BIN_DIR}/uv"
echo "Activate venv: source \"${TARGET_DIR}/.venv/bin/activate\""
echo "Run API: ${TARGET_DIR}/run_api_server_offline.sh"
