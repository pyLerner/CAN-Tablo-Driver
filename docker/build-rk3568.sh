#!/usr/bin/env bash
set -euo pipefail

# RK3568 / Ubuntu 20.04 friendly build path:
# disable BuildKit/buildx and use classic docker builder.
export DOCKER_BUILDKIT=0
export COMPOSE_DOCKER_CLI_BUILD=0

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${PROJECT_ROOT}"
docker compose -f docker/docker-compose.yml build --no-cache can-tablo-api
