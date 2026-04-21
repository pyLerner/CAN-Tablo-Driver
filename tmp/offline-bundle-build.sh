#!/usr/bin/env bash
set -euo pipefail

# Строгая сборка офлайн-бандла для переноса на RK3588 (aarch64, Ubuntu 20.04).
# Запускается на машине-доноре с интернетом (amd64).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${1:-$SCRIPT_DIR}"

export PYTHON_VERSION="${PYTHON_VERSION:-3.11}"
export TARGET_PLATFORM="${TARGET_PLATFORM:-manylinux2014_aarch64}"
export TARGET_PYTHON_TAG="${TARGET_PYTHON_TAG:-cp311}"
export TARGET_PYTHON_ARCH="${TARGET_PYTHON_ARCH:-aarch64-unknown-linux-gnu}"
export TARGET_UV_ASSET="${TARGET_UV_ASSET:-uv-aarch64-unknown-linux-gnu.tar.gz}"
export STRICT_WHEELS=1

echo "==> Строгая сборка офлайн-бандла (wheel-only)"
echo "    PROJECT_DIR=${PROJECT_DIR}"
echo "    PYTHON_VERSION=${PYTHON_VERSION}"
echo "    TARGET_PLATFORM=${TARGET_PLATFORM}"
echo "    TARGET_PYTHON_TAG=${TARGET_PYTHON_TAG}"
echo "    TARGET_PYTHON_ARCH=${TARGET_PYTHON_ARCH}"

"${SCRIPT_DIR}/offline-bundle.sh" "$PROJECT_DIR"

