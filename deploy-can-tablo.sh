#!/usr/bin/env bash

set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo ./deploy-can-tablo.sh"
  exit 1
fi

USER="$USER"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="/home/${USER}/CAN-Tablo-Driver"
SYSTEMD_DIR="/etc/systemd/system"

# REPO_URL="$(git -C "${SCRIPT_DIR}" remote get-url origin 2>/dev/null || true)"
REPO_URL="https://github.com/${USER}/CAN-Tablo-Driver.git"

echo "[1/6] Sync project to ${APP_DIR}"
if [[ -d "${APP_DIR}/.git" ]]; then
  git -C "${APP_DIR}" fetch --all --tags
  CURRENT_BRANCH="$(git -C "${APP_DIR}" rev-parse --abbrev-ref HEAD)"
  git -C "${APP_DIR}" checkout "${CURRENT_BRANCH}"
  git -C "${APP_DIR}" pull --ff-only
else
  if [[ -z "${REPO_URL}" ]]; then
    echo "Unable to detect git remote URL from ${SCRIPT_DIR}."
    echo "Set REPO_URL manually in deploy-can-tablo.sh and run again."
    exit 1
  fi
  mkdir -p "$(dirname "${APP_DIR}")"
  git clone "${REPO_URL}" "${APP_DIR}"
fi

echo "[2/6] Ensure runtime script is executable"
chmod 755 "${APP_DIR}/tablo.run"

echo "[3/6] Install systemd units"
install -m 644 "${APP_DIR}/can0-setup.service" "${SYSTEMD_DIR}/can0-setup.service"
install -m 644 "${APP_DIR}/led-tablo.service" "${SYSTEMD_DIR}/led-tablo.service"

echo "[4/6] Reload systemd"
systemctl daemon-reload

echo "[5/6] Enable units at boot"
systemctl enable can0-setup.service
systemctl enable led-tablo.service

echo "[6/6] Restart services"
systemctl restart can0-setup.service
systemctl restart led-tablo.service

echo
echo "Deployment complete."
echo "Service status:"
systemctl --no-pager --full status can0-setup.service led-tablo.service || true
