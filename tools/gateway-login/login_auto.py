#!/usr/bin/env python3
"""IBKR Client Portal Gateway login via Playwright (server-side automation).

Reads credentials from a mounted env file (IBKR_ENV_FILE, default
/secrets/ibkr.env) containing single-quoted IBKR_PAPER_USER / IBKR_PAPER_PASS
lines. Values are NEVER printed or logged.

Uses a PERSISTENT browser profile (/data/browser-profile) so the device
identity stays stable across runs, and the gateway at https://localhost:5000
(localhost only — 127.0.0.1 does not work for this flow).

Recipe (proven 2026-10-22): submit the login form in paper mode, pin the
cookie jar to one x-sess-uuid + JSESSIONID, submit a real form POST to
/sso/Dispatcher (loginType=2, forwardTo=22), then poll auth/status until the
brokerage session is authenticated. Prints progress + a final JSON result.
"""
import json
import os
import re
import sys
import time

from playwright.sync_api import sync_playwright

GW = "https://localhost:5000"
DOMAIN = "localhost"
PROFILE = "/data/browser-profile"
WAIT_S = 300
SHOT = "/data/login_auto_last.png" if os.path.isdir("/data") else None
ENV_FILE = os.environ.get("IBKR_ENV_FILE", "/secrets/ibkr.env")


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def read_creds(path):
    text = open(path).read()
    vals = {}

    def _get(name):
        m = re.search(r"^" + name + r"='([^']*)'\s*$", text, re.M)
        return m.group(1) if m else None
    vals["user"] = _get("IBKR_PAPER_USER")
    vals["pass"] = _get("IBKR_PAPER_PASS")
    if not vals["user"] or not vals["pass"]:
        raise SystemExit("credentials missing from env file")
    return vals["user"], vals["pass"]


def auth_status(page):
    try:
        return page.evaluate(
            """async () => {
                const r = await fetch('/v1/api/iserver/auth/status');
                return await r.json();
            }""")
    except Exception:
        return None


def page_snippet(page, n=200):
    try:
        txt = page.inner_text("body", timeout=2500)
        return " ".join(txt.split())[:n]
    except Exception:
        return "<unreadable>"


def main():
    username, password = read_creds(ENV_FILE)
    log("credentials loaded from env file (values not logged)")

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            PROFILE, headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
                  "--no-first-run", "--disable-blink-features=AutomationControlled"],
            ignore_https_errors=True,
            user_agent=("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"))
        page = ctx.new_page()
        _mirror = {}
        _latest_sess = {}

        def _on_response(resp):
            try:
                for h in resp.headers_array():
                    if h["name"].lower() == "set-cookie":
                        v = h["value"]
                        lv = v.lower()
                        first = v.split(";")[0]
                        if first.split("=", 1)[0].strip() == "x-sess-uuid" and "=" in first:
                            _latest_sess["v"] = first.split("=", 1)[1].strip()
                        if "domain=.ibkr.com" in lv or "domain=ibkr.com" in lv:
                            if "=" in first:
                                nm, val = first.split("=", 1)
                                _mirror[nm.strip()] = val.strip()
                                log(f"mirror-captured: {nm.strip()}")
            except Exception:
                pass
            try:
                u = resp.url
                if "/sso/" in u or "/v1/api/" in u:
                    log(f"net {resp.request.method} {resp.status} {u[:140]}")
            except Exception:
                pass

        page.on("response", _on_response)

        def normalize_jar():
            try:
                target = _latest_sess.get("v")
                if not target:
                    return
                jar = ctx.cookies()
                sess = [c for c in jar if c["name"] == "x-sess-uuid"]
                if len(sess) == 1 and sess[0]["value"] == target and sess[0]["path"] == "/":
                    return
                snap = {}
                for c in jar:
                    if c["name"] != "x-sess-uuid":
                        snap[(c["name"], c.get("path") or "/")] = c
                ctx.clear_cookies()
                adds = [{"name": "x-sess-uuid", "value": target,
                         "domain": DOMAIN, "path": "/",
                         "secure": True, "httpOnly": True}]
                for (nm, pth), c in snap.items():
                    adds.append({"name": nm, "value": c["value"],
                                 "domain": DOMAIN, "path": pth,
                                 "secure": True, "httpOnly": True})
                ctx.add_cookies(adds)
                log(f"jar normalized: sess pinned, {len(adds)} cookies")
            except Exception as e:
                log(f"normalize failed: {e}")

        log("browser launched (persistent profile); loading gateway")
        page.goto(GW + "/", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_selector("#xyz-field-username", timeout=60000)
        log(f"login page loaded: {page.url}")

        paper = None
        try:
            def mode_status():
                return page.evaluate(
                    """() => {
                        const s = document.querySelector('#toggle-status');
                        return s ? s.textContent.trim().toLowerCase() : '';
                    }""")
            status = mode_status()
            log(f"mode status before: {status!r}")
            if "paper" not in status:
                boxes = page.locator("#toggle1")
                for i in range(boxes.count()):
                    try:
                        boxes.nth(i).evaluate("el => el.click()")
                    except Exception as e:
                        log(f"js click {i} failed: {e}")
                    time.sleep(1)
                    status = mode_status()
                    log(f"mode status after toggle {i}: {status!r}")
                    if "paper" in status:
                        break
            paper = "paper" in (status or "")
        except Exception as e:
            log(f"paper toggle handling failed: {e}")
        log(f"paper mode: {paper}")

        page.fill("#xyz-field-username", username)
        page.fill("#xyz-field-password", password)
        page.click("button.xyz-button-login", timeout=10000)
        log("credentials submitted; waiting for session")
        time.sleep(2)
        normalize_jar()
        time.sleep(3)
        log(f"page now: {page_snippet(page)}")

        ssodh_tried = False
        jar_fixed = False
        mirrored_done = False
        deadline = time.time() + WAIT_S
        detail = "not authenticated before timeout"
        while time.time() < deadline:
            if not ssodh_tried:
                ssodh_tried = True
                try:
                    r = page.evaluate(
                        """async () => {
                            const resp = await fetch('/v1/api/iserver/auth/ssodh/init', {
                                method: 'POST',
                                headers: {'Content-Type': 'application/json'},
                                body: JSON.stringify({publish: true, compete: true})
                            });
                            return {status: resp.status, body: (await resp.text()).slice(0, 300)};
                        }""")
                    log(f"ssodh/init -> {r}")
                except Exception as e:
                    log(f"ssodh/init failed: {e}")
            normalize_jar()
            if _mirror and not mirrored_done:
                try:
                    newc = [{"name": nm, "value": val, "domain": DOMAIN,
                             "path": "/", "secure": True, "httpOnly": True}
                            for nm, val in _mirror.items()]
                    ctx.add_cookies(newc)
                    log(f"mirrored cookies to local origin: {list(_mirror.keys())}")
                    mirrored_done = True
                except Exception as e:
                    log(f"mirror step failed: {e}")
            if not jar_fixed and _latest_sess.get("v"):
                jar_fixed = True
                try:
                    jsid = None
                    for c in ctx.cookies():
                        if c["name"] == "JSESSIONID":
                            jsid = c["value"]
                    ctx.clear_cookies()
                    keep = [{"name": "x-sess-uuid", "value": _latest_sess["v"],
                             "domain": DOMAIN, "path": "/",
                             "secure": True, "httpOnly": True}]
                    if jsid:
                        keep.append({"name": "JSESSIONID", "value": jsid,
                                     "domain": DOMAIN, "path": "/sso",
                                     "secure": True, "httpOnly": True})
                    for nm, val in _mirror.items():
                        keep.append({"name": nm, "value": val,
                                     "domain": DOMAIN, "path": "/",
                                     "secure": True, "httpOnly": True})
                    ctx.add_cookies(keep)
                    log(f"jar rebuilt: {[c['name'] for c in keep]}")
                    page.evaluate(
                        """() => {
                            const f = document.createElement('form');
                            f.method = 'POST';
                            f.action = '/sso/Dispatcher';
                            for (const [k, v] of [['loginType', '2'], ['forwardTo', '22']]) {
                                const i = document.createElement('input');
                                i.type = 'hidden'; i.name = k; i.value = v;
                                f.appendChild(i);
                            }
                            document.body.appendChild(f);
                            f.submit();
                        }""")
                    log("manual dispatcher form submitted")
                    time.sleep(6)
                    log(f"after dispatcher nav: url={page.url}")
                except Exception as e:
                    log(f"jar rebuild failed: {e}")
            st = auth_status(page)
            if st and st.get("authenticated"):
                log("AUTHENTICATED")
                print(json.dumps({"ok": True, "paper_toggle": paper, "auth": st}))
                ctx.close()
                return 0
            try:
                if "authentication failed" in page_snippet(page, 300).lower():
                    detail = "credentials rejected by IBKR (authentication failed)"
                    log("AUTH FAILED detected - stopping")
                    break
            except Exception:
                pass
            log(f"waiting... url={page.url} page: {page_snippet(page, 160)}")
            time.sleep(8)

        try:
            page_text = page.inner_text("body", timeout=3000)[:400]
        except Exception:
            page_text = ""
        if SHOT:
            try:
                page.screenshot(path=SHOT)
            except Exception:
                pass
        print(json.dumps({"ok": False, "paper_toggle": paper,
                          "detail": detail, "page": page_text}))
        ctx.close()
        return 3


if __name__ == "__main__":
    sys.exit(main())
