#!/bin/bash

cd /root
python3 ./oci-web1.py $*
cd /root/DocumentRoot
python3 -m http.server 8080