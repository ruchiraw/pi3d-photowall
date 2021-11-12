#!/usr/bin/sh

export TERM=linux
export TERMINFO=/etc/terminfo

cd /home/pi/photowall
/usr/bin/python3 index.py 
