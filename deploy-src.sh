#!/bin/bash

service=led-tablo.service

sudo cp $service /etc/systemd/system
sudo systemctl daemon-reload
sudo systemctl enable $service
sudo systemctl start $service
sleep 3
sudo systemctl status $service
