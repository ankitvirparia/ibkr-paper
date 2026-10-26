#!/usr/bin/env python3
"""Click the Live/Paper toggle in the VNC desktop's IBKR login page.

Coordinates are plain page pixels in the 1500x950 noVNC viewport (the
reference screenshot IS the page, so no canvas remapping is applied).
"""
import os
import sys
import time

from playwright.sync_api import sync_playwright

VNC_PASS = os.environ["VNC_PASS"]


def main():
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, args=[
            "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--no-first-run",
            "--disable-blink-features=AutomationControlled"])
        pg = b.new_page(viewport={"width": 1500, "height": 950},
                        user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
        pg.goto("http://100.101.82.11:6081/vnc.html", timeout=30000)
        time.sleep(3)
        pg.click("#noVNC_connect_button", timeout=5000)
        time.sleep(2)
        pg.fill("#noVNC_password_input", VNC_PASS, timeout=5000)
        pg.click("#noVNC_credentials_button", timeout=5000)
        time.sleep(4)
        pg.mouse.click(1045, 337)  # the Paper toggle switch
        time.sleep(2)
        pg.screenshot(path="/data/drive_toggle_result.png")
        print("toggle clicked; screenshot saved", flush=True)
        b.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
