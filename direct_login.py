#!/usr/bin/env python3
"""Direct gateway login via headless Chrome (no proxy, no inlined page).

Uses the gateway's real /sso/Login page at localhost:5000. Paper mode ON.
Saves authenticated cookies to the jar for ibkr_client.
"""
import json
import os
import sys
import time
import urllib.request
import ssl

LOGIN_URL = "https://localhost:5000/sso/Login"
GW_AUTH_STATUS = "https://localhost:5000/v1/api/iserver/auth/status"
JAR = "/mnt/store/data-app/ibkr-paper/.ibkr_cookies.json"
PW_FILE = "/mnt/store/data-app/ibkr-paper/.paper_password"
USERNAME = os.environ.get("IBKR_PAPER_USER", "sonalivpt")


def save_jar(cookies: list[dict]) -> None:
    jar = {}
    try:
        jar = json.load(open(JAR))
    except (OSError, ValueError):
        pass
    for c in cookies:
        if c.get("name") and c.get("value"):
            jar[c["name"]] = c["value"]
    os.makedirs(os.path.dirname(JAR), exist_ok=True)
    json.dump(jar, open(JAR, "w"))
    print("JAR_SAVED %d cookies" % len(jar), flush=True)


def check_auth() -> bool:
    try:
        jar = json.load(open(JAR))
    except (OSError, ValueError):
        return False
    cookie = "; ".join("%s=%s" % (k, v) for k, v in jar.items())
    req = urllib.request.Request(GW_AUTH_STATUS,
                                headers={"Cookie": cookie})
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(req, timeout=20, context=ctx) as r:
            data = json.loads(r.read().decode("utf-8", "replace") or "{}")
            return bool(data.get("authenticated"))
    except Exception:
        return False


def main() -> None:
    password = open(PW_FILE).read().strip()
    from playwright.sync_api import sync_playwright
    try:
        from playwright_stealth import stealth_sync
        HAS_STEALTH = True
    except ImportError:
        HAS_STEALTH = False

    print("BROWSER_START direct-gateway stealth=%s" % HAS_STEALTH, flush=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(
            channel="chrome", headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage",
                  "--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(ignore_https_errors=True,
                                  user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                                  viewport={"width": 1366, "height": 768})
        page = ctx.new_page()
        if HAS_STEALTH:
            stealth_sync(page)
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_selector("input[name=username]", timeout=30000)
        time.sleep(3)
        print("PAGE_READY", flush=True)

        page.fill("input[name=username]", USERNAME)
        page.fill("input[name=password]", password)
        # NB: password kept in memory for the paper-confirmation page; wiped at exit

        # paper mode toggle via its label
        try:
            page.click("label[for=toggle1]", timeout=10000)
            on = page.evaluate(
                "() => document.querySelector('.xyz-paper-switch').checked")
            print("PAPER_MODE_%s" % ("on" if on else "STILL_OFF"), flush=True)
            if not on:
                print("ABORT no paper toggle", flush=True)
                browser.close()
                sys.exit(3)
        except Exception as e:
            print("ABORT toggle %s" % e, flush=True)
            browser.close()
            sys.exit(3)

        # click login and wait for navigation / result
        page.click(".xyz-button-login")
        print("SUBMITTED", flush=True)

        deadline = time.time() + 120
        simulated_done = False
        while time.time() < deadline:
            time.sleep(5)
            try:
                url = page.url
                # paper flow: on the SIMULATED page, fill creds and submit
                # via JS requestSubmit (native button click is unreliable)
                if not simulated_done and "Dispatcher" in url:
                    try:
                        done = page.evaluate("""(creds) => {
                            const btn = [...document.querySelectorAll('button')].find(
                                x => x.innerText.trim() === 'Simulated Login');
                            if (!btn || !btn.is_visible) return false;
                            const f = btn.closest('form');
                            if (!f) return false;
                            const u = f.querySelector('input[name=username]');
                            const pw = f.querySelector('input[name=password]');
                            if (u) u.value = creds.u;
                            if (pw) pw.value = creds.p;
                            f.requestSubmit(btn);
                            return true;
                        }""", {"u": USERNAME, "p": password})
                        if done:
                            simulated_done = True
                            print("SIMULATED_SUBMITTED", flush=True)
                    except Exception:
                        pass
            except Exception:
                url = "?"
            # save whatever cookies we have and test
            try:
                save_jar(ctx.cookies())
            except Exception:
                pass
            if check_auth():
                print("LOGIN_OK url=%s" % url, flush=True)
                password = "x" * 64
                browser.close()
                return
            if "sso/Login" not in url and "Dispatcher" not in url:
                print("NAVIGATED %s (not yet auth)" % url, flush=True)
        try:
            print("FINAL_URL %s" % page.url, flush=True)
            print("FINAL_TEXT %s" % page.evaluate(
                "() => document.body.innerText.slice(0, 800)"), flush=True)
        except Exception:
            pass
        print("LOGIN_TIMEOUT", flush=True)
        password = "x" * 64
        browser.close()
        sys.exit(1)


if __name__ == "__main__":
    main()
