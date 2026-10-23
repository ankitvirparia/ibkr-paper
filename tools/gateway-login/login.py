#!/usr/bin/env python3
"""IBKR Client Portal Gateway login via Playwright (runs on the server).

Reads username and password (two lines) from stdin - never from disk or argv.
Opens the gateway at https://127.0.0.1:5000 (true localhost origin), submits
the login form in paper mode, then waits for the second-factor step and polls
auth status until the brokerage session is live. Progress is printed live
(flush) so the operator can watch the flow; a final JSON result line is
printed on stdout. Screenshots go to /data/login_last.png when /data exists.
"""
import json
import os
import sys
import time

from playwright.sync_api import sync_playwright

GW = "https://127.0.0.1:5000"
WAIT_S = 300
SHOT = "/data/login_last.png" if os.path.isdir("/data") else None


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def auth_status(page):
    try:
        return page.evaluate(
            """async () => {
                const r = await fetch('/v1/api/iserver/auth/status');
                return await r.json();
            }"""
        )
    except Exception:
        return None


def page_snippet(page, n=220):
    try:
        txt = page.inner_text("body", timeout=2500)
        return " ".join(txt.split())[:n]
    except Exception:
        return "<unreadable>"


def click_text(page, text):
    """Click a visible button/link whose text contains `text`."""
    try:
        loc = page.get_by_text(text, exact=False)
        for i in range(min(loc.count(), 4)):
            el = loc.nth(i)
            if el.is_visible():
                el.click(timeout=2500)
                log(f"clicked text: {text!r}")
                return True
    except Exception:
        pass
    return False


def click_role(page, name):
    try:
        btn = page.get_by_role("button", name=name)
        if btn.count() > 0 and btn.first.is_visible():
            btn.first.click(timeout=2500)
            log(f"clicked button: {name!r}")
            return True
    except Exception:
        pass
    return False


def main():
    log("script started")
    lines = sys.stdin.read().splitlines()
    log("stdin read: %d lines" % len(lines))
    if len(lines) < 2 or not lines[0].strip():
        print(json.dumps({"ok": False, "detail": "credentials missing on stdin"}))
        return 2
    username, password = lines[0].strip(), lines[1].strip()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--no-first-run",
            "--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(
            ignore_https_errors=True,
            user_agent=("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
        )
        page = ctx.new_page()
        _mirror = {}
        _latest_sess = {}
        def _on_response(resp):
            try:
                try:
                    for h in resp.headers_array():
                        if h["name"].lower() == "set-cookie":
                            v = h["value"]
                            lv = v.lower()
                            first = v.split(";")[0]
                            if first.split("=", 1)[0].strip() == "x-sess-uuid" and "=" in first:
                                _latest_sess["v"] = first.split("=", 1)[1].strip()
                            if "domain=.ibkr.com" in lv or "domain=ibkr.com" in lv:
                                first = v.split(";")[0]
                                if "=" in first:
                                    nm, val = first.split("=", 1)
                                    _mirror[nm.strip()] = val.strip()
                                    log(f"mirror-captured: {nm.strip()}")
                except Exception:
                    pass
            except Exception:
                pass
            try:
                u = resp.url
                if ("/sso/" in u or "/v1/api/" in u or "auth" in u.lower()):
                    log(f"net {resp.request.method} {resp.status} {u[:140]}")
                    if "Dispatcher" in u:
                        try:
                            ck = resp.request.all_headers().get("cookie", "")
                            names = [p.split("=")[0].strip() for p in ck.split(";") if "=" in p]
                            sess = [p.strip()[:44] for p in ck.split(";") if "x-sess-uuid" in p]
                            log(f"dispatcher req cookies: {names} sess={sess}")
                        except Exception as e:
                            log(f"dispatcher cookie log failed: {e}")
                    if "Authenticator" in u or "Dispatcher" in u:
                        try:
                            pd = resp.request.post_data or ""
                            keys = []
                            if pd.strip().startswith("{"):
                                import json as _json
                                keys = list(_json.loads(pd).keys())
                            elif pd:
                                keys = [p.split("=")[0] for p in pd.split("&") if p]
                            log(f"net-req-keys {u[:50]}: {keys}")
                            import re as _re
                            for m in _re.finditer(r"(paper|mode|loginType|accountType)[^&,}]*", pd, _re.I):
                                log(f"net-req-mode: {m.group(0)[:80]}")
                        except Exception as e:
                            log(f"net-req inspect failed: {e}")
                        try:
                            body = resp.text()
                            if body:
                                log(f"net-body {u[:50]}: {body[:500]}")
                        except Exception as e:
                            log(f"net-body failed: {e}")
            except Exception:
                pass
        page.on("response", _on_response)
        _auth_reqs = {}
        _cdp = None
        try:
            _cdp = ctx.new_cdp_session(page)
            _cdp.send("Network.enable")
            def _resp_recv(params):
                try:
                    u = params["response"]["url"]
                    if "Dispatcher" in u:
                        try:
                            ck = resp.request.all_headers().get("cookie", "")
                            names = [p.split("=")[0].strip() for p in ck.split(";") if "=" in p]
                            sess = [p.strip()[:44] for p in ck.split(";") if "x-sess-uuid" in p]
                            log(f"dispatcher req cookies: {names} sess={sess}")
                        except Exception as e:
                            log(f"dispatcher cookie log failed: {e}")
                    if "Authenticator" in u or "Dispatcher" in u:
                        _auth_reqs[params["requestId"]] = u
                except Exception:
                    pass
            _cdp.on("Network.responseReceived", _resp_recv)
        except Exception as e:
            log(f"cdp setup failed: {e}")
        log("browser launched; loading gateway")
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
                         "domain": "127.0.0.1", "path": "/",
                         "secure": True, "httpOnly": True}]
                for (nm, pth), c in snap.items():
                    adds.append({"name": nm, "value": c["value"],
                                 "domain": "127.0.0.1", "path": pth,
                                 "secure": True, "httpOnly": True})
                ctx.add_cookies(adds)
                log(f"jar normalized: sess pinned, {len(adds)} cookies")
            except Exception as e:
                log(f"normalize failed: {e}")

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
                log(f"toggle boxes found: {boxes.count()}")
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
            paper = None
        log(f"paper mode: {paper}")

        page.fill("#xyz-field-username", username)
        page.fill("#xyz-field-password", password)
        page.click("button.xyz-button-login", timeout=10000)
        log("credentials submitted; waiting for second factor / session")
        time.sleep(2)
        normalize_jar()
        time.sleep(3)
        log(f"page now: {page_snippet(page)}")
        try:
            names = [c["name"] for c in ctx.cookies()]
            log(f"cookies after submit: {names}")
        except Exception:
            pass

        ssodh_tried = False
        resubmitted = True
        portal_tried = True
        mirrored_done = False
        jar_fixed = False
        bodies_dumped = False
        loop_n = 0
        deadline = time.time() + WAIT_S
        detail = "not authenticated before timeout"
        last_shot = 0.0
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
            if not resubmitted:
                try:
                    uf = page.locator("#xyz-field-username")
                    if uf.count() > 0 and uf.first.is_visible() and not uf.first.input_value():
                        resubmitted = True
                        log("bounced back to empty login form; re-entering credentials once")
                        uf.first.fill(username)
                        page.fill("#xyz-field-password", password)
                        st2 = mode_status()
                        log(f"mode status before resubmit: {st2!r}")
                        page.click("button.xyz-button-login", timeout=5000)
                        log("credentials re-submitted")
                        time.sleep(3)
                except Exception as e:
                    log(f"resubmit step failed: {e}")
            loop_n += 1
            normalize_jar()
            if _mirror and not mirrored_done:
                try:
                    newc = [{"name": nm, "value": val, "domain": "127.0.0.1",
                             "path": "/", "secure": True, "httpOnly": True}
                            for nm, val in _mirror.items()]
                    ctx.add_cookies(newc)
                    log(f"mirrored cookies to local origin: {list(_mirror.keys())}")
                    mirrored_done = True
                    log("mirror stored (no nav)")
                except Exception as e:
                    log(f"mirror step failed: {e}")
            if _cdp is not None and _auth_reqs and not bodies_dumped:
                bodies_dumped = True
                for rid, u in list(_auth_reqs.items()):
                    try:
                        r = _cdp.send("Network.getResponseBody", {"requestId": rid})
                        log(f"auth-body {u[:60]}: {r.get('body', '')[:600]}")
                    except Exception as e:
                        log(f"auth-body fetch failed: {e}")
            if not jar_fixed and _latest_sess.get("v"):
                jar_fixed = True
                try:
                    jsid = None
                    for c in ctx.cookies():
                        if c["name"] == "JSESSIONID":
                            jsid = c["value"]
                    ctx.clear_cookies()
                    keep = [{"name": "x-sess-uuid", "value": _latest_sess["v"],
                             "domain": "127.0.0.1", "path": "/",
                             "secure": True, "httpOnly": True}]
                    if jsid:
                        keep.append({"name": "JSESSIONID", "value": jsid,
                                     "domain": "127.0.0.1", "path": "/sso",
                                     "secure": True, "httpOnly": True})
                    for nm, val in _mirror.items():
                        keep.append({"name": nm, "value": val,
                                     "domain": "127.0.0.1", "path": "/",
                                     "secure": True, "httpOnly": True})
                    ctx.add_cookies(keep)
                    log(f"jar rebuilt: {[c['name'] for c in keep]}")
                    try:
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
                    except Exception:
                        pass
                    log("manual dispatcher form submitted")
                    time.sleep(6)
                    try:
                        log(f"after dispatcher nav: url={page.url}")
                    except Exception:
                        pass
                except Exception as e:
                    log(f"jar rebuild failed: {e}")
            if not portal_tried and loop_n >= 2:
                portal_tried = True
                try:
                    page.goto(GW + "/", wait_until="domcontentloaded", timeout=30000)
                    log(f"navigated to portal root; url={page.url}")
                    time.sleep(5)
                except Exception as e:
                    log(f"portal nav failed: {e}")
            st = auth_status(page)
            if st and st.get("authenticated"):
                log("AUTHENTICATED")
                print(json.dumps({"ok": True, "paper_toggle": paper, "auth": st}))
                browser.close()
                return 0

            # second-factor method choices (select dropdown or text options)
            try:
                sel = page.locator("select:visible")
                if sel.count() > 0:
                    opts = sel.first.locator("option")
                    for i in range(opts.count()):
                        t = (opts.nth(i).inner_text() or "").lower()
                        if "ib key" in t or "mobile" in t or "push" in t:
                            sel.first.select_option(index=i)
                            log(f"selected 2FA option: {t}")
                            break
            except Exception:
                pass
            for label in ("IB Key", "Push Notification",
                          "Authenticate", "Continue", "Send Notification"):
                if click_text(page, label) or click_role(page, label):
                    break

            # detect a typed-code challenge (needs a code, not a push)
            try:
                code_inputs = page.locator(
                    "input:visible[id*='code' i], input:visible[name*='code' i], "
                    "input:visible[placeholder*='code' i]")
                if code_inputs.count() > 0:
                    detail = "challenge wants a typed code, not a push approval"
                    log("CODE INPUT VISIBLE - push flow not offered")
            except Exception:
                pass

            # credential rejection: stop early instead of waiting out the clock
            try:
                if "authentication failed" in page_snippet(page, 300).lower():
                    detail = "credentials rejected by IBKR (authentication failed)"
                    log("AUTH FAILED detected - stopping")
                    break
            except Exception:
                pass

            log(f"waiting... url={page.url} page: {page_snippet(page, 160)}")
            if SHOT and time.time() - last_shot > 30:
                last_shot = time.time()
                try:
                    page.screenshot(path=SHOT)
                except Exception:
                    pass
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
        browser.close()
        return 3


if __name__ == "__main__":
    sys.exit(main())
