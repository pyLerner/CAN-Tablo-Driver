#!/bin/sh
set -eu

CAN_IFACE="${CAN_IFACE:-can0}"
CAN_WAIT_SECONDS="${CAN_WAIT_SECONDS:-2}"

while ! ip link show "${CAN_IFACE}" >/dev/null 2>&1; do
    echo "$(date -u +"%Y-%m-%dT%H:%M:%SZ") can interface '${CAN_IFACE}' is unavailable, waiting ${CAN_WAIT_SECONDS}s..."
    sleep "${CAN_WAIT_SECONDS}"
done

echo "$(date -u +"%Y-%m-%dT%H:%M:%SZ") can interface '${CAN_IFACE}' is available, starting app"
exec "$@"
