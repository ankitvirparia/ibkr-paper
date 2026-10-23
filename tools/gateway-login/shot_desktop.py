import os, time
from playwright.sync_api import sync_playwright

pw = os.environ["VNC_PASS"]
with sync_playwright() as p:
    b = p.chromium.launch(headless=True, args=[
        "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--no-first-run",
        "--disable-blink-features=AutomationControlled"])
    pg = b.new_page(viewport={"width": 1500, "height": 950},
                    user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
    pg.goto("http://100.101.82.11:6081/vnc.html", timeout=30000)
    time.sleep(3)
    # Connect button
    for sel in ["#noVNC_connect_button", "button:has-text('Connect')", "input[value='Connect']"]:
        try:
            pg.click(sel, timeout=2500); print("clicked", sel); break
        except Exception:
            pass
    time.sleep(2)
    # Password prompt
    for sel in ["#noVNC_password_input", "input[type='password']"]:
        try:
            pg.fill(sel, pw, timeout=2500); print("filled", sel); break
        except Exception:
            pass
    for sel in ["#noVNC_credentials_button", "button:has-text('Send')", "button:has-text('OK')"]:
        try:
            pg.click(sel, timeout=2000); print("submitted", sel); break
        except Exception:
            pass
    time.sleep(6)
    pg.screenshot(path="/data/desktop_proof.png")
    print("status text:", pg.inner_text("body")[:200].replace("\n", " | "))
    b.close()
print("DONE")
