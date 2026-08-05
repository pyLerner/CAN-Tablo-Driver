#!/usr/bin/env bash
# Развёртывание из каталога, где лежат подкаталог can-tablo-driver/ и архив can-tablo-driver*.tar.gz
# — загрузка образа (docker load), остановка/удаление контейнера при обновлении, запуск compose.
# Совместимость: docker-compose v1 (бинарник docker-compose). При отсутствии — fallback на docker compose.
# Опционально: копирование can-tablo-driver → /opt/can-tablo-driver (как в docker-compose volumes).
set -euo pipefail

COMPOSE_REL_PATH="${COMPOSE_REL_PATH:-}"
DEFAULT_CONTAINER_NAME="${CONTAINER_NAME:-can-tablo-api}"
OPT_TARGET="/opt/can-tablo-driver"
SYSTEMD_UNIT="can0-setup.service"
COMPOSE_BIN=""

usage() {
  cat <<'EOF'
Usage: install-old-docker.sh [options] [DEPLOY_DIR]

  DEPLOY_DIR — каталог с can-tablo-driver/ и can-tablo-driver*.tar.gz (по умолчанию: текущий).

Options:
  --copy-to-opt       Скопировать can-tablo-driver в /opt/can-tablo-driver (нужен root).
  --no-up             Только docker load (и опционально --copy-to-opt), без запуска.
  --enable-service    После --copy-to-opt: установить can0-setup.service и включить на хосте.
  --tar FILE          Явный путь к .tar.gz; иначе ищется can-tablo-driver*.tar.gz в DEPLOY_DIR.
  -h, --help          Справка.

Переменные окружения:
  TAR_FILE            То же, что --tar.
  CONTAINER_NAME      Имя контейнера для остановки перед обновлением (по умолчанию: can-tablo-api).
  COMPOSE_REL_PATH    Путь к compose от корня проекта (по умолчанию: авто — docker-compose.yml или docker/docker-compose.yml).

Несколько файлов can-tablo-driver*.tar.gz: берётся самый новый по дате модификации.

Требуется docker-compose (v1). Если его нет — используется «docker compose» (plugin v2).
EOF
}

log() { printf '%s\n' "$*"; }

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "команда не найдена: $1"
}

resolve_compose_bin() {
  if command -v docker-compose >/dev/null 2>&1; then
    COMPOSE_BIN="docker-compose"
    return 0
  fi
  if docker compose version >/dev/null 2>&1; then
    log "Предупреждение: docker-compose (v1) не найден, использую «docker compose»"
    COMPOSE_BIN="docker compose"
    return 0
  fi
  die "нужен docker-compose (v1) или плагин «docker compose»"
}

compose_cmd() {
  # shellcheck disable=SC2086
  ${COMPOSE_BIN} "$@"
}

pick_newest_tar() {
  local -n __arr=$1
  local newest="" mt=-1 t
  [[ ${#__arr[@]} -gt 0 ]] || return 1
  for f in "${__arr[@]}"; do
    if [[ ! -f "$f" ]]; then
      continue
    fi
    t=$(stat -c %Y "$f" 2>/dev/null || stat -f %m "$f" 2>/dev/null || echo 0)
    if (( t > mt )); then
      mt=$t
      newest=$f
    fi
  done
  [[ -n "$newest" ]] || return 1
  printf '%s' "$newest"
}

resolve_tar_path() {
  local dir="$1"
  if [[ -n "${TAR_FILE:-}" ]]; then
    [[ -f "$TAR_FILE" ]] || die "файл не найден: $TAR_FILE"
    realpath -s "$TAR_FILE" 2>/dev/null || readlink -f "$TAR_FILE" 2>/dev/null || printf '%s' "$TAR_FILE"
    return
  fi
  local -a candidates=()
  shopt -s nullglob
  candidates=( "${dir}"/can-tablo-driver*.tar.gz )
  shopt -u nullglob
  ((${#candidates[@]} == 0)) && die "в $dir нет файлов can-tablo-driver*.tar.gz (задайте --tar или TAR_FILE=)"
  if ((${#candidates[@]} > 1)); then
    log "Найдено несколько архивов, выбран самый новый по mtime:"
    printf '  %s\n' "${candidates[@]}"
  fi
  pick_newest_tar candidates || die "не удалось выбрать архив"
}

resolve_compose_rel_path() {
  local root="$1"
  if [[ -n "${COMPOSE_REL_PATH}" ]]; then
    return 0
  fi
  if [[ -f "${root}/docker-compose.yml" ]]; then
    COMPOSE_REL_PATH="docker-compose.yml"
  elif [[ -f "${root}/docker/docker-compose.yml" ]]; then
    COMPOSE_REL_PATH="docker/docker-compose.yml"
  else
    die "не найден compose в ${root} (ожидается docker-compose.yml или docker/docker-compose.yml)"
  fi
}

stop_existing_container() {
  local name="$1"
  if docker ps -a --format '{{.Names}}' 2>/dev/null | grep -Fxq "$name"; then
    log "Останавливаю и удаляю контейнер «$name» (обновление образа)…"
    docker rm -f "$name" >/dev/null
  fi
}

compose_down_project() {
  local root="$1"
  local cf="${root}/${COMPOSE_REL_PATH}"
  [[ -f "$cf" ]] || return 0
  log "${COMPOSE_BIN} down в ${root}…"
  ( cd "$root" && compose_cmd -f "$COMPOSE_REL_PATH" down --remove-orphans 2>/dev/null ) || true
}

copy_project_to_opt() {
  local src="$1"
  [[ -d "$src" ]] || die "нет каталога: $src"
  need_cmd rsync
  log "Копирование ${src} → ${OPT_TARGET} …"
  mkdir -p "${OPT_TARGET}"
  rsync -a --delete "${src}/" "${OPT_TARGET}/"
  mkdir -p "${OPT_TARGET}/logs"
  chown -R 1000:1000 "${OPT_TARGET}/logs"
}

disable_legacy_units() {
  systemctl disable led-tablo.service 2>/dev/null || true
  rm -f /etc/systemd/system/led-tablo.service
}

enable_service_on_host() {
  local unit_src="${OPT_TARGET}/systemd/${SYSTEMD_UNIT}"
  [[ -f "$unit_src" ]] || die "не найден unit: ${unit_src}"

  need_cmd systemctl
  log "Установка ${SYSTEMD_UNIT}…"
  disable_legacy_units
  cp "$unit_src" "/etc/systemd/system/${SYSTEMD_UNIT}"
  systemctl daemon-reload
  systemctl enable "${SYSTEMD_UNIT}"
  systemctl start "${SYSTEMD_UNIT}" 2>/dev/null || true
}

start_stack() {
  local project_root="$1"
  log "Запуск stack в ${project_root} (${COMPOSE_BIN})…"
  ( cd "$project_root" && compose_cmd -f "$COMPOSE_REL_PATH" up -d --no-build )
}

main() {
  local deploy_dir=""
  local copy_to_opt=0
  local no_up=0
  local enable_service=0
  local tar_explicit=""

  while [[ $# -gt 0 ]]; do
    case "$1" in
      -h | --help)
        usage
        exit 0
        ;;
      --copy-to-opt)
        copy_to_opt=1
        shift
        ;;
      --no-up)
        no_up=1
        shift
        ;;
      --enable-service)
        enable_service=1
        shift
        ;;
      --tar)
        [[ -n "${2:-}" ]] || die "ожидается путь после --tar"
        tar_explicit=$2
        shift 2
        ;;
      -*)
        die "неизвестный параметр: $1"
        ;;
      *)
        [[ -z "$deploy_dir" ]] || die "указано несколько каталогов"
        deploy_dir=$1
        shift
        ;;
    esac
  done

  need_cmd docker
  resolve_compose_bin
  deploy_dir="${deploy_dir:-.}"
  deploy_dir=$(cd "$deploy_dir" && pwd)

  if [[ -n "$tar_explicit" ]]; then
    TAR_FILE=$tar_explicit
  fi

  local src_project="${deploy_dir}/can-tablo-driver"
  [[ -d "$src_project" ]] || die "ожидается каталог: ${src_project}"

  local tar_path
  tar_path=$(resolve_tar_path "$deploy_dir")
  [[ -f "$tar_path" ]] || die "архив образа: $tar_path"

  local project_root="$src_project"
  if (( copy_to_opt )); then
    if [[ "${EUID}" -ne 0 ]]; then
      die "для --copy-to-opt запустите от root: sudo $0 ..."
    fi
    copy_project_to_opt "$src_project"
    project_root="${OPT_TARGET}"
    if (( enable_service )); then
      enable_service_on_host
    else
      log "Подсказка: для production на хосте выполните:"
      log "  sudo cp ${OPT_TARGET}/systemd/${SYSTEMD_UNIT} /etc/systemd/system/"
      log "  sudo systemctl daemon-reload"
      log "  sudo systemctl enable --now ${SYSTEMD_UNIT}"
      log "или переустановите с флагом --enable-service"
    fi
  elif (( enable_service )); then
    die "--enable-service требует --copy-to-opt"
  fi

  resolve_compose_rel_path "${project_root}"

  local compose_file="${project_root}/${COMPOSE_REL_PATH}"
  [[ -f "$compose_file" ]] || die "не найден compose: $compose_file (COMPOSE_REL_PATH=${COMPOSE_REL_PATH})"

  compose_down_project "$project_root"
  stop_existing_container "$DEFAULT_CONTAINER_NAME"

  log "Загрузка образа из ${tar_path} …"
  gunzip -c "$tar_path" | docker load

  if (( no_up )); then
    log "Готово (--no-up: контейнер не запускался)."
    exit 0
  fi

  start_stack "$project_root"
  log "Готово."
}

main "$@"
