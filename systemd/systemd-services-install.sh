#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYSTEMD_DIR="/etc/systemd/system"
CAN0_SETUP_SERVICE="can0-setup.service"
LED_TABLO_SERVICE="led-tablo.service"

cp -a "${CAN0_SETUP_SERVICE}" "${SYSTEMD_DIR}/"
cp -a "${LED_TABLO_SERVICE}" "${SYSTEMD_DIR}/"

systemctl daemon-reload
systemctl enable "${CAN0_SETUP_SERVICE}"
systemctl enable "${LED_TABLO_SERVICE}"
systemctl start "${CAN0_SETUP_SERVICE}"
systemctl start "${LED_TABLO_SERVICE}"
