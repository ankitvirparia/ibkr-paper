#!/usr/bin/env python3
"""Headless IBKR paper login via the inlined gateway login page.

Reads the paper password from IBKR_PAPER_PASSWORD env var or
~/.ibkr_paper_password (chmod 600). Drives headless Chrome through the
login + 2FA flow. The user approves the 2FA challenge in the IBKR mobile
app. The ibkr-paper proxy captures the authenticated session cookies
into the jar; this script polls the jar and verifies auth status.

Usage: python3 headless_login.py
"""
import json
import os
import sys
import time
import urllib.request
import ssl

LOGIN_URL = "https://100.101.82.11:8005/sso/Login"
GW_AUTH_STATUS = "https://127.0.0.1:5000/v1/api/iserver/auth/status"
JAR = "/mnt/store/data-app/ibkr-paper/.ibkr_cookies.json"
PW_FILE = "/mnt/store/data-app/ibkr-paper/.paper_password"
USERNAME = os.environ.get("IBKR_PAPER_USER", "sonalivpt")


def get_password() -> str:
    pw = os.environ.get("IBKR_PAPER_PASSWORD")
    if pw:
        return pw
    if os.path.exists(PW_FILE):
        return open(PW_FILE).read().strip()
    print("NO_PASSWORD: set IBKR_PAPER_PASSWORD or write %s (chmod 600)"
          % PW_FILE, flush=True)
    sys.exit(2)


def jar_mtime() -> float:
    try:
        return os.path.getmtime(JAR)
    except OSError:
        return 0.0


def check_auth() -> bool:
    """Test current jar cookies against the gateway auth endpoint."""
    try:
        jar = json.load(open(JAR))
    except (OSError, ValueError):
        return False
    if not jar:
        return False
    cookie = "; ".join("%s=%s" % (k, v) for k, v in jar.items())
    req = urllib.request.Request(
        GW_AUTH_STATUS, headers={"Cookie": cookie})
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(req, timeout=20, context=ctx) as r:
            body = r.read().decode("utf-8", "replace")
            data = json.loads(body) if body else {}
            return bool(data.get("authenticated"))
    except Exception:
        return False


def main() -> None:
    password = get_password()
    from playwright.sync_api import sync_playwright

    print("BROWSER_START", flush=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            channel="chrome", headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = browser.new_context(ignore_https_errors=True)
        page = ctx.new_page()
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_selector("input[name=username]", timeout=30000)
        print("PAGE_READY", flush=True)

        page.fill("input[name=username]", USERNAME)
        page.fill("input[name=password]", password)
        # never keep the password in the page longer than needed
        password = "x" * 64

        # enable paper trading mode by clicking its <label> (native toggle)
        try:
            page.click("label[for=toggle1]", timeout=10000)
            paper_on = page.evaluate(
                "() => document.querySelector('.xyz-paper-switch').checked")
            print("PAPER_MODE_%s" % ("on" if paper_on else "STILL_OFF"),
                  flush=True)
            if not paper_on:
                print("ABORT: paper trading toggle could not be enabled",
                      flush=True)
                browser.close()
                sys.exit(3)
        except Exception as e:
            print("ABORT: paper toggle error %s" % e, flush=True)
            browser.close()
            sys.exit(3)

        page.click(".xyz-button-login")
        print("SUBMITTED", flush=True)

        # paper login needs no MFA: wait for navigation away from the
        # login page (success) or a 2FA challenge (live mode fallback)
        print("WAITING_FOR_RESULT", flush=True)
        deadline = time.time() + 90
        last_mtime = jar_mtime()
        mfa_announced = False
        while time.time() < deadline:
            if jar_mtime() > last_mtime:
                last_mtime = jar_mtime()
                if check_auth():
                    print("LOGIN_OK", flush=True)
                    browser.close()
                    return
            try:
                if "sso/Login" not in page.url:
                    print("PAGE_NAVIGATED %s" % page.url, flush=True)
                    time.sleep(3)
                    if check_auth():
                        print("LOGIN_OK", flush=True)
                    else:
                        print("NAVIGATED_BUT_NOT_AUTH", flush=True)
                    browser.close()
                    return
                # 2FA challenge visible? (only for live mode)
                tfa = page.evaluate(
                    """() => !!document.querySelector(
                        '.xyz-bronze-response, .xyz-silver-response,'
                        + ' .xyz-gold-response, .xyz-temp-response')""")
                if tfa and not mfa_announced:
                    mfa_announced = True
                    print("MFA_NEEDED: approve the login in your IBKR "
                          "mobile app now", flush=True)
            except Exception:
                pass
            time.sleep(3)

        # final state dump for debugging
        try:
            print("FINAL_URL %s" % page.url, flush=True)
            print("FINAL_TITLE %s" % page.title(), flush=True)
        except Exception:
            pass
        print("LOGIN_TIMEOUT", flush=True)
        browser.close()
        sys.exit(1)


if __name__ == "__main__":
    main()
