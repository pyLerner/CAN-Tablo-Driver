#!/usr/bin/env bash
# Сохранение Docker-образа в архив и развёртывание на другой машине (docker load + compose).
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: docker-save-deploy.sh <command> [args]

Commands:
  save <image[:tag]> [stem]
      Сохраняет образ (docker save), сжимает gzip. Файл: $SAVEDIR/<stem>.tar.gz
      Если stem не задан — имя из образа: символы / и : заменяются на _.
  remove <name>
      Удаляет контейнер с именем name (docker rm -f). Отсутствие контейнера не считается ошибкой.
  update|install <name>
      Удаляет контейнер name, загружает образ из $SAVEDIR/<name>.tar.gz, затем
      docker compose up -d --no-build.

Environment:
  SAVEDIR                  Каталог для .tar.gz (по умолчанию: ./saved-images)
  COMPOSE_FILE             Compose-файл (по умолчанию: compose.yaml)
  COMPOSE_PROJECT_DIRECTORY  Опционально: docker compose --project-directory
                             (нужен, если пути в compose относительны к корню репозитория)

Пример переноса (имя контейнера в compose = can-tablo-api):
  На машине A (из корня репозитория):
    SAVEDIR=./images ./docker-save-deploy.sh save can-tablo-driver:latest can-tablo-api
  Скопируйте images/can-tablo-api.tar.gz и проект (compose, docker/etc, docker/data).
  На машине B:
    export SAVEDIR=/path/to/images
    export COMPOSE_FILE=/path/to/CAN-Tablo-Driver/compose.yaml
    export COMPOSE_PROJECT_DIRECTORY=/path/to/CAN-Tablo-Driver
    ./docker-save-deploy.sh install can-tablo-api

Для SocketCAN обычно нужен Linux-хост; см. комментарии в compose.yaml (host network, devices).

Options: -h, --help — эта справка.
EOF
}

savedir() {
  echo "${SAVEDIR:-./saved-images}"
}

stem_from_image() {
  printf '%s' "$1" | tr '/:' '__'
}

compose_up() {
  local -a cmd=(docker compose -f "${COMPOSE_FILE:-compose.yaml}")
  if [[ -n "${COMPOSE_PROJECT_DIRECTORY:-}" ]]; then
    cmd+=(--project-directory "$COMPOSE_PROJECT_DIRECTORY")
  fi
  cmd+=(up -d --no-build)
  "${cmd[@]}"
}

cmd_save() {
  if [[ $# -lt 1 ]]; then
    echo "save: требуется образ image[:tag] и опционально stem" >&2
    exit 1
  fi
  local image="$1"
  local stem="${2:-}"
  if [[ -z "$stem" ]]; then
    stem=$(stem_from_image "$image")
  fi
  local dir out
  dir=$(savedir)
  mkdir -p "$dir"
  out="${dir}/${stem}.tar.gz"
  docker save "$image" | gzip -c >"$out"
  echo "Saved: $out"
}

cmd_remove() {
  if [[ $# -lt 1 ]]; then
    echo "remove: требуется имя контейнера" >&2
    exit 1
  fi
  docker rm -f "$1" 2>/dev/null || true
}

cmd_update_install() {
  if [[ $# -lt 1 ]]; then
    echo "install/update: требуется имя контейнера (и файл \$SAVEDIR/<name>.tar.gz)" >&2
    exit 1
  fi
  local name="$1"
  local dir archive cf
  dir=$(savedir)
  archive="${dir}/${name}.tar.gz"
  if [[ ! -f "$archive" ]]; then
    echo "Файл образа не найден: $archive" >&2
    exit 1
  fi
  cf="${COMPOSE_FILE:-compose.yaml}"
  if [[ ! -f "$cf" ]]; then
    echo "Compose-файл не найден: $cf (задайте COMPOSE_FILE)" >&2
    exit 1
  fi

  docker rm -f "$name" 2>/dev/null || true
  gunzip -c "$archive" | docker load
  compose_up
}

main() {
  case "${1:-}" in
    -h | --help | help | "")
      usage
      [[ -n "${1:-}" ]] || exit 1
      exit 0
      ;;
    save)
      shift
      cmd_save "$@"
      ;;
    remove)
      shift
      cmd_remove "$@"
      ;;
    update | install)
      shift
      cmd_update_install "$@"
      ;;
    *)
      echo "Неизвестная команда: ${1:-}" >&2
      usage >&2
      exit 1
      ;;
  esac
}

main "$@"
