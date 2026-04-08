#!/bin/bash

set -xvv

# sudo modprobe vcan
# sudo ip link add dev can0 type vcan
DEVICE=/dev/ttyACM0
sudo slcand -o -c -s6 $DEVICE can0
sudo ip link set up can0
