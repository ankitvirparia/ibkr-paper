#!/usr/bin/env python3
"""Log in to the IBKR gateway through the VNC desktop's own Chromium via CDP.

The desktop browser is the one browser that ever validated (2026-10-22).
VNC mouse clicks cannot flip the Paper toggle (its input is off-viewport);
only a JS el.click() on #toggle1 flips it — the proven Oct 22 method.
Credentials come from the mounted env file; values are never printed.
Leaves the desktop browser running.
"""
import json
import os
import re
import sys
import time

from playwright.sync_api import sync_playwright

ENV_FILE = os.environ.get("IBKR_ENV_FILE", "/secrets/ibkr.env")


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
        browser = p.chromium.connect_over_cdp("http://localhost:9222")
        ctx = browser.contexts[0]
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        print(f"attached to page: {page.url}", flush=True)
        page.wait_for_selector("#xyz-field-username", timeout=60000)
        print(f"login page ready: {page.url}", flush=True)

        def mode_status():
            return page.evaluate(
                """() => {
                    const s = document.querySelector('#toggle-status');
                    return s ? s.textContent.trim().toLowerCase() : '';
                }""")
        status = mode_status()
        print(f"mode before: {status!r}", flush=True)
        for i in range(5):
            if "paper" in status:
                break
            page.evaluate(
                """() => {
                    document.querySelectorAll('#toggle1').forEach(el => el.click());
                }""")
            time.sleep(1.5)
            status = mode_status()
            print(f"mode after js click {i}: {status!r}", flush=True)
        paper = "paper" in status
        print(f"paper mode: {paper}", flush=True)

        page.fill("#xyz-field-username", username)
        page.fill("#xyz-field-password", password)
        page.click("button.xyz-button-login", timeout=10000)
        print("credentials submitted", flush=True)

        deadline = time.time() + 180
        while time.time() < deadline:
            try:
                st = page.evaluate(
                    """async () => {
                        const r = await fetch('/v1/api/iserver/auth/status');
                        return await r.json();
                    }""")
            except Exception:
                st = None
            if st and st.get("authenticated"):
                print("AUTHENTICATED", flush=True)
                print(json.dumps({"ok": True, "paper": paper, "auth": True}))
                return 0
            try:
                txt = " ".join(page.inner_text("body", timeout=2500).split())[:160]
            except Exception:
                txt = "<unreadable>"
            print(f"waiting... url={page.url} page: {txt}", flush=True)
            time.sleep(8)
        print(json.dumps({"ok": False, "paper": paper, "detail": "not authenticated"}))
        return 3


if __name__ == "__main__":
    sys.exit(main())
