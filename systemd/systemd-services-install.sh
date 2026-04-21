#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYSTEMD_DIR="/etc/systemd/system"
CAN0_SETUP_SERVICE="${SCRIPT_DIR}/can0-setup.service"
LED_TABLO_SERVICE="${SCRIPT_DIR}/led-tablo.service"

cp -a "${CAN0_SETUP_SERVICE}" "${SYSTEMD_DIR}/can0-setup.service"
cp -a "${LED_TABLO_SERVICE}" "${SYSTEMD_DIR}/led-tablo.service"

systemctl daemon-reload
systemctl enable "${CAN0_SETUP_SERVICE}"
systemctl enable "${LED_TABLO_SERVICE}"
systemctl start "${CAN0_SETUP_SERVICE}"
systemctl start "${LED_TABLO_SERVICE}"