#!/data/data/com.termux/files/usr/bin/bash
# Author: gorcoding
cd "$(dirname "$0")"
(sleep 2; command -v termux-open-url >/dev/null && termux-open-url http://127.0.0.1:8080) &
python app.py
