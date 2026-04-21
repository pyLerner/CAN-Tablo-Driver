#!/usr/bin/env bash
set -euo pipefail

# Creates a fully offline bundle from donor machine:
# - project git history (all branches/tags)
# - donor uv binary
# - uv-managed Python runtimes
# - uv cache (wheels/sdists)
# - requirements export for deterministic restore

PROJECT_DIR="${1:-$(pwd)}"
OUTPUT_DIR="${2:-$(pwd)}"
BUNDLE_NAME="${BUNDLE_NAME:-can-tablo-offline-bundle}"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
BUNDLE_ROOT="${OUTPUT_DIR}/${BUNDLE_NAME}-${TIMESTAMP}"
ARCHIVE_PATH="${BUNDLE_ROOT}.tar.gz"

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "ERROR: '$1' not found in PATH"
    exit 1
  }
}

need_cmd git
need_cmd tar
need_cmd uv
need_cmd python3

PROJECT_DIR="$(cd "${PROJECT_DIR}" && pwd)"
OUTPUT_DIR="$(cd "${OUTPUT_DIR}" && pwd)"
UV_BIN="$(command -v uv)"

if [[ ! -d "${PROJECT_DIR}" ]]; then
  echo "ERROR: project directory not found: ${PROJECT_DIR}"
  exit 1
fi

if [[ ! -d "${PROJECT_DIR}/.git" ]]; then
  echo "ERROR: ${PROJECT_DIR} is not a git repository"
  exit 1
fi

echo "==> Creating offline bundle"
echo "    PROJECT_DIR: ${PROJECT_DIR}"
echo "    OUTPUT_DIR:  ${OUTPUT_DIR}"
echo "    UV_BIN:      ${UV_BIN}"

rm -rf "${BUNDLE_ROOT}" "${ARCHIVE_PATH}"
mkdir -p "${BUNDLE_ROOT}"/{project,uv,uv-cache,uv-python,meta,systemd}

echo "==> Saving git repository with all branches and tags"
git -C "${PROJECT_DIR}" bundle create "${BUNDLE_ROOT}/project/project.bundle" --all
git -C "${PROJECT_DIR}" rev-parse --abbrev-ref HEAD > "${BUNDLE_ROOT}/meta/default-branch.txt"
git -C "${PROJECT_DIR}" status --porcelain > "${BUNDLE_ROOT}/meta/dirty-status.txt" || true

echo "==> Saving source snapshot (for uncommitted donor changes)"
tar -czf "${BUNDLE_ROOT}/project/worktree-snapshot.tar.gz" \
  --exclude='.git' \
  -C "${PROJECT_DIR}" .

echo "==> Exporting requirements from uv.lock"
uv export \
  --directory "${PROJECT_DIR}" \
  --format requirements-txt \
  --no-hashes \
  -o "${BUNDLE_ROOT}/project/requirements.txt"

python3 - "${BUNDLE_ROOT}/project/requirements.txt" "${BUNDLE_ROOT}/project/requirements-thirdparty.txt" <<'PY'
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

echo "==> Saving uv binaries"
cp -a "${UV_BIN}" "${BUNDLE_ROOT}/uv/uv"
if command -v uvx >/dev/null 2>&1; then
  cp -a "$(command -v uvx)" "${BUNDLE_ROOT}/uv/uvx"
fi
chmod +x "${BUNDLE_ROOT}/uv/uv" "${BUNDLE_ROOT}/uv/uvx" 2>/dev/null || true

echo "==> Saving uv Python runtimes and cache"
UV_PYTHON_DIR="${HOME}/.local/share/uv/python"
UV_CACHE_DIR="${HOME}/.cache/uv"
if [[ -d "${UV_PYTHON_DIR}" ]]; then
  cp -a "${UV_PYTHON_DIR}/." "${BUNDLE_ROOT}/uv-python/"
else
  echo "WARN: uv Python runtime directory not found: ${UV_PYTHON_DIR}"
fi
if [[ -d "${UV_CACHE_DIR}" ]]; then
  cp -a "${UV_CACHE_DIR}/." "${BUNDLE_ROOT}/uv-cache/"
else
  echo "WARN: uv cache directory not found: ${UV_CACHE_DIR}"
fi

[[ -f "${PROJECT_DIR}/pyproject.toml" ]] && cp "${PROJECT_DIR}/pyproject.toml" "${BUNDLE_ROOT}/project/"
[[ -f "${PROJECT_DIR}/uv.lock" ]] && cp "${PROJECT_DIR}/uv.lock" "${BUNDLE_ROOT}/project/"
[[ -f "${PROJECT_DIR}/can0-setup.service" ]] && cp "${PROJECT_DIR}/can0-setup.service" "${BUNDLE_ROOT}/systemd/"
[[ -f "${PROJECT_DIR}/led-tablo.service" ]] && cp "${PROJECT_DIR}/led-tablo.service" "${BUNDLE_ROOT}/systemd/"

cat > "${BUNDLE_ROOT}/INSTALL.md" <<'EOF'
# Offline restore instructions

On target machine:

```bash
tar xzf <bundle>.tar.gz
cd <bundle>
./offline-install-bundle.sh /opt/CAN-Tablo-Driver
```

If project path is omitted, default is `./workdir/CAN-Tablo-Driver`.
EOF

cp -a "${PROJECT_DIR}/offline-install-bundle.sh" "${BUNDLE_ROOT}/offline-install-bundle.sh"
chmod +x "${BUNDLE_ROOT}/offline-install-bundle.sh"

echo "==> Packing archive"
tar -czf "${ARCHIVE_PATH}" -C "${OUTPUT_DIR}" "$(basename "${BUNDLE_ROOT}")"

echo
echo "Bundle created: ${ARCHIVE_PATH}"
echo "Transfer this archive to the offline target machine."
