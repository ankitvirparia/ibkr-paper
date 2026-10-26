#!/usr/bin/env python3
"""Drive the VNC desktop's own Chromium to log in to the IBKR gateway.

Why this exists: headless Playwright logins reach the Dispatcher stage but
IBKR refuses the server-side sso/validate every time; the one login that
validated (2026-10-22) was done by hand in this exact desktop browser.
This script reproduces that browser, not a fresh headless one.

Flow: connect to noVNC, click the Paper toggle, fill the login form with
credentials read from the mounted env file (values never printed), click
Login, screenshot, print a JSON result. Coordinates are fractions of the
noVNC canvas, measured from a 1500x950 reference screenshot.
"""
import json
import os
import re
import sys
import time

from playwright.sync_api import sync_playwright

VNC_PASS = os.environ["VNC_PASS"]
ENV_FILE = os.environ.get("IBKR_ENV_FILE", "/secrets/ibkr.env")
VW, VH = 1500, 950
# (name, x_frac, y_frac) in reference-screenshot space
TOGGLE = (1010 / VW, 337 / VH)
USER_FIELD = (770 / VW, 416 / VH)
PASS_FIELD = (770 / VW, 485 / VH)
LOGIN_BTN = (770 / VW, 575 / VH)


def read_creds(path):
    text = open(path).read()

    def _get(name):
        m = re.search(r"^" + name + r"='([^']*)'\s*$", text, re.M)
        return m.group(1) if m else None
    u, p = _get("IBKR_PAPER_USER"), _get("IBKR_PAPER_PASS")
    if not u or not p:
        raise SystemExit("credentials missing from env file")
    return u, p


def main():
    username, password = read_creds(ENV_FILE)
    print("credentials loaded (values not logged)", flush=True)
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, args=[
            "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--no-first-run",
            "--disable-blink-features=AutomationControlled"])
        pg = b.new_page(viewport={"width": VW, "height": VH},
                        user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
        pg.goto("http://100.101.82.11:6081/vnc.html", timeout=30000)
        time.sleep(3)
        pg.click("#noVNC_connect_button", timeout=5000)
        time.sleep(2)
        pg.fill("#noVNC_password_input", VNC_PASS, timeout=5000)
        pg.click("#noVNC_credentials_button", timeout=5000)
        time.sleep(4)
        canvas = pg.locator("canvas").first
        canvas.wait_for(timeout=10000)
        box = canvas.bounding_box()
        print(f"canvas box: {box}", flush=True)

        def click_frac(frac):
            x = box["x"] + frac[0] * box["width"]
            y = box["y"] + frac[1] * box["height"]
            pg.mouse.click(x, y)
            print(f"clicked at {x:.0f},{y:.0f}", flush=True)

        pg.screenshot(path="/data/drive_before.png")
        click_frac(TOGGLE)
        time.sleep(2)
        pg.screenshot(path="/data/drive_after_toggle.png")
        click_frac(USER_FIELD)
        time.sleep(1)
        pg.keyboard.type(username)
        click_frac(PASS_FIELD)
        time.sleep(1)
        pg.keyboard.type(password)
        time.sleep(1)
        pg.screenshot(path="/data/drive_filled.png")
        click_frac(LOGIN_BTN)
        time.sleep(10)
        pg.screenshot(path="/data/drive_after_login.png")
        print("done; screenshots in /data/drive_*.png", flush=True)
        b.close()
    print(json.dumps({"ok": True}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
