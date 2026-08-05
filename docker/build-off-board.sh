#!/usr/bin/env bash
set -euo pipefail

# Cross-build linux/arm64 image on dev machine (x86) for RK3568 deployment.
# Prerequisites (one-time):
#   docker buildx create --name cantablo-builder --use 2>/dev/null || docker buildx use cantablo-builder
#   docker run --privileged --rm tonistiigi/binfmt --install all

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DOCKER_DIR="${SCRIPT_DIR}"
IMAGE_TAG="${IMAGE_TAG:-can-tablo-driver:2-static-antistorm}"
EXPORT_TAR_DEFAULT="${DOCKER_DIR}/can-tablo-driver-1-$(date +%Y%m%d).tar.gz"
BUNDLE_DIR_NAME="${BUNDLE_DIR_NAME:-CanTabloDriverDockerApp}"
BUNDLE_TAR_DEFAULT="${DOCKER_DIR}/${BUNDLE_DIR_NAME}-$(date +%Y%m%d).tar.gz"
BUILDER_NAME="${BUILDER_NAME:-cantablo-builder}"

if [[ -n "${EXPORT_TAR:-}" ]]; then
  if [[ "${EXPORT_TAR}" = /* ]]; then
    EXPORT_TAR_PATH="${EXPORT_TAR}"
  else
    EXPORT_TAR_PATH="${DOCKER_DIR}/${EXPORT_TAR}"
  fi
else
  EXPORT_TAR_PATH="${EXPORT_TAR_DEFAULT}"
fi

if [[ -n "${BUNDLE_TAR:-}" ]]; then
  if [[ "${BUNDLE_TAR}" = /* ]]; then
    BUNDLE_TAR_PATH="${BUNDLE_TAR}"
  else
    BUNDLE_TAR_PATH="${DOCKER_DIR}/${BUNDLE_TAR}"
  fi
else
  BUNDLE_TAR_PATH="${BUNDLE_TAR_DEFAULT}"
fi

log() { printf '%s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "команда не найдена: $1"
}

ensure_buildx() {
  need_cmd docker
  if ! docker buildx version >/dev/null 2>&1; then
    die "docker buildx не найден; обновите Docker Engine"
  fi
  if ! docker buildx inspect "${BUILDER_NAME}" >/dev/null 2>&1; then
    log "Создаю buildx builder «${BUILDER_NAME}»…"
    docker buildx create --name "${BUILDER_NAME}" --use
  else
    docker buildx use "${BUILDER_NAME}"
  fi
  if ! docker buildx inspect --bootstrap >/dev/null 2>&1; then
    die "не удалось инициализировать buildx builder"
  fi
}

build_deploy_bundle() {
  local bundle_root="${DOCKER_DIR}/${BUNDLE_DIR_NAME}"
  local bundle_project="${bundle_root}/can-tablo-driver"
  local image_basename
  image_basename="$(basename "${EXPORT_TAR_PATH}")"

  [[ -f "${EXPORT_TAR_PATH}" ]] || die "архив образа не найден: ${EXPORT_TAR_PATH}"
  [[ -f "${DOCKER_DIR}/install-old-docker.sh" ]] || die "нет install-old-docker.sh в ${DOCKER_DIR}"
  [[ -f "${DOCKER_DIR}/docker-compose.prod.yml" ]] || die "нет production compose: ${DOCKER_DIR}/docker-compose.prod.yml"
  [[ -d "${DOCKER_DIR}/etc" ]] || die "нет каталога: ${DOCKER_DIR}/etc"
  [[ -d "${DOCKER_DIR}/data" ]] || die "нет каталога: ${DOCKER_DIR}/data"
  [[ -f "${DOCKER_DIR}/systemd/can0-setup.service" ]] || die "нет unit: ${DOCKER_DIR}/systemd/can0-setup.service"

  need_cmd rsync
  rm -rf "${bundle_root}"
  mkdir -p "${bundle_project}/systemd" "${bundle_project}/logs"

  log "Сборка deploy bundle в ${BUNDLE_TAR_PATH}…"
  rsync -a "${DOCKER_DIR}/etc/" "${bundle_project}/etc/"
  rsync -a "${DOCKER_DIR}/data/" "${bundle_project}/data/"
  cp "${DOCKER_DIR}/systemd/can0-setup.service" "${bundle_project}/systemd/"
  cp "${DOCKER_DIR}/docker-compose.prod.yml" "${bundle_project}/docker-compose.yml"
  cp "${EXPORT_TAR_PATH}" "${bundle_root}/${image_basename}"
  cp "${DOCKER_DIR}/install-old-docker.sh" "${bundle_root}/"
  chmod +x "${bundle_root}/install-old-docker.sh"
  if [[ -f "${DOCKER_DIR}/install-docker-from-tar.sh" ]]; then
    cp "${DOCKER_DIR}/install-docker-from-tar.sh" "${bundle_root}/"
    chmod +x "${bundle_root}/install-docker-from-tar.sh"
  fi

  tar -czf "${BUNDLE_TAR_PATH}" -C "${DOCKER_DIR}" "${BUNDLE_DIR_NAME}"
  rm -rf "${bundle_root}"

  log "Deploy bundle: ${BUNDLE_TAR_PATH}"
}

cd "${PROJECT_ROOT}"
ensure_buildx

log "Сборка ${IMAGE_TAG} (linux/arm64)…"
docker buildx build \
  --platform linux/arm64 \
  --no-cache \
  -f docker/Dockerfile \
  -t "${IMAGE_TAG}" \
  --load \
  .

log "Экспорт образа в ${EXPORT_TAR_PATH}…"
mkdir -p "${DOCKER_DIR}"
docker save "${IMAGE_TAG}" | gzip > "${EXPORT_TAR_PATH}"

log "Готово: ${EXPORT_TAR_PATH}"
build_deploy_bundle
