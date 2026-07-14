#!/usr/bin/env bash
set -euo pipefail

# RK3568 / Ubuntu friendly build path:
# Для cross-build на x86 и deploy bundle используйте build-off-board.sh.
# disable BuildKit/buildx and use classic docker builder.
export DOCKER_BUILDKIT=0
export COMPOSE_DOCKER_CLI_BUILD=0

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
IMAGE_TAG="${IMAGE_TAG:-can-tablo-driver:latest}"

cd "${PROJECT_ROOT}"
docker build --no-cache -f docker/Dockerfile -t "${IMAGE_TAG}" .

echo "Built ${IMAGE_TAG}"
echo "Export: docker save ${IMAGE_TAG} | gzip > can-tablo-driver-1-\$(date +%Y%m%d).tar.gz"
echo "Cross-build + bundle: ${SCRIPT_DIR}/build-off-board.sh"
