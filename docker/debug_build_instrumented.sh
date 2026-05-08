#!/usr/bin/env bash
set -u

LOG_PATH="/home/pyler/netdisk/Projects/Infoteh-main-project/projects/CAN-Tablo-Driver/.cursor/debug-a677b4.log"
RUN_ID="build-$(date +%s)"
SESSION_ID="a677b4"

log_event() {
  local hypothesis_id="$1"
  local location="$2"
  local message="$3"
  local data="$4"
  local ts
  ts="$(date +%s%3N 2>/dev/null || date +%s000)"
  printf '{"sessionId":"%s","runId":"%s","hypothesisId":"%s","location":"%s","message":"%s","data":%s,"timestamp":%s}\n' \
    "$SESSION_ID" "$RUN_ID" "$hypothesis_id" "$location" "$message" "$data" "$ts" >> "$LOG_PATH"
}

# region agent log
log_event "H0" "docker/debug_build_instrumented.sh:18" "Start debug build run" '{"cwd":"'"$(pwd)"'","composeFile":"docker/docker-compose.yml"}'
# endregion

# region agent log
docker version >/tmp/can_tablo_docker_version.txt 2>&1
log_event "H1" "docker/debug_build_instrumented.sh:23" "Collected docker version" '{"exitCode":'"$?"',"outputFile":"/tmp/can_tablo_docker_version.txt"}'
# endregion

# region agent log
docker buildx version >/tmp/can_tablo_buildx_version.txt 2>&1
log_event "H1" "docker/debug_build_instrumented.sh:28" "Collected buildx version" '{"exitCode":'"$?"',"outputFile":"/tmp/can_tablo_buildx_version.txt"}'
# endregion

# region agent log
DOCKER_BUILDKIT=1 docker compose -f docker/docker-compose.yml build --no-cache can-tablo-api >/tmp/can_tablo_compose_build.txt 2>&1
BUILD_EXIT="$?"
log_event "H2" "docker/debug_build_instrumented.sh:34" "Compose build finished" '{"exitCode":'"$BUILD_EXIT"',"outputFile":"/tmp/can_tablo_compose_build.txt"}'
# endregion

# region agent log
DOCKER_BUILDKIT=1 docker build --no-cache -f docker/Dockerfile . >/tmp/can_tablo_direct_build.txt 2>&1
DIRECT_EXIT="$?"
log_event "H3" "docker/debug_build_instrumented.sh:40" "Direct docker build finished" '{"exitCode":'"$DIRECT_EXIT"',"outputFile":"/tmp/can_tablo_direct_build.txt"}'
# endregion

# region agent log
log_event "H4" "docker/debug_build_instrumented.sh:44" "End debug build run" '{"composeExit":'"$BUILD_EXIT"',"directExit":'"$DIRECT_EXIT"'}'
# endregion

if [ "$BUILD_EXIT" -ne 0 ] || [ "$DIRECT_EXIT" -ne 0 ]; then
  exit 1
fi
exit 0
