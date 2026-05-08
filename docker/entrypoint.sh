#!/bin/sh
set -eu

CAN_IFACE="${CAN_IFACE:-can0}"
echo "$(date -u +"%Y-%m-%dT%H:%M:%SZ") host-managed can interface '${CAN_IFACE}', starting app"
exec "$@"
