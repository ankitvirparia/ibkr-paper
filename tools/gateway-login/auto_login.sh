#!/bin/bash
# Automated IBKR paper login via the VNC desktop's own Chromium (CDP).
# This is the ONLY automated route that has ever validated: headless
# Playwright logins always die at sso/validate (401); the desktop browser
# with its stable device identity validates.
#
# Steps: relaunch desktop chromium with a loopback-only CDP port, run the
# CDP login (JS paper-toggle click + form submit from the stored env file),
# relaunch chromium normally (debug port closed), verify auth/status.
# Credentials are read from /mnt/store/data-app/ibkr-paper/.ibkr.env and are
# never printed. Usage: auto_login.sh   (exit 0 = session authenticated)
set -u
ENV_FILE=/mnt/store/data-app/ibkr-paper/.ibkr.env
TOOLS=/mnt/store/apps/ibkr-paper/tools/gateway-login
DATA=/mnt/store/data-app/ibkr-paper
IMG=ibkr-gateway-login

launch_chromium() {
  # $1 = extra chromium flags (may be empty)
  docker exec -u ankit -d -e DISPLAY=:5 vnc-desktop chromium \
    --user-data-dir=/home/ankit/.config/chromium-vnc --no-sandbox \
    --disable-dev-shm-usage --disable-gpu --start-maximized $1 \
    https://localhost:5000 >/dev/null 2>&1
}

docker exec -u ankit vnc-desktop pkill -f "chromium" 2>/dev/null
sleep 2
launch_chromium "--remote-debugging-port=9222 --remote-debugging-address=127.0.0.1"
sleep 6
docker run --rm --network host --shm-size=2g \
  -v "$ENV_FILE:/secrets/ibkr.env:ro" -v "$TOOLS:/work" \
  -e IBKR_ENV_FILE=/secrets/ibkr.env "$IMG" \
  python3 /work/cdp_desktop_login.py
RC=$?
docker exec -u ankit vnc-desktop pkill -f "chromium" 2>/dev/null
sleep 2
launch_chromium ""
sleep 4
AUTH=$(curl -sk -m 10 https://localhost:5000/v1/api/iserver/auth/status)
echo "auth_status: $(echo "$AUTH" | head -c 120)"
case "$AUTH" in
  *'"authenticated":true'*) echo "RESULT: authenticated"; exit 0 ;;
  *) echo "RESULT: not authenticated (cdp rc=$RC)"; exit 1 ;;
esac
