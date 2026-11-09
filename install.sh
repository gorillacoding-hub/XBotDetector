#!/data/data/com.termux/files/usr/bin/bash
# Author: gorcoding
pkg update -y && pkg install -y python termux-api
pip install -r requirements.txt
echo "Installed. Start with: bash run.sh"
