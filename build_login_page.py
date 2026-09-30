"""Build a fully self-contained IBKR gateway login page.

Fetches /sso/Login from the local gateway, inlines every stylesheet and
script, strips third-party telemetry, and appends lightweight diagnostic
beacons. The result is a single HTML file: a phone only needs to load ONE
page for the login form to render.

Output: static/sso_login.html  (served by ibkr-paper at /sso/Login)

Run on the server (needs gateway access):
    python3 build_login_page.py
"""

import re
import ssl
import urllib.request
from urllib.parse import urljoin, urlparse

GW = "https://127.0.0.1:5000"
PAGE_URL = GW + "/sso/Login?forwardTo=22&RL=1&ip2loc=US"


def resolve(url: str) -> str:
    """Resolve a page-relative URL to a gateway-absolute path."""
    u = urlparse(urljoin(PAGE_URL, url))
    return u.path + (("?" + u.query) if u.query else "")

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def get(path: str) -> str:
    with urllib.request.urlopen(GW + path, context=CTX, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def main() -> None:
    print("fetching login page ...", flush=True)
    html = get(urlparse(PAGE_URL).path + "?" + urlparse(PAGE_URL).query)

    # ---- inline stylesheets -------------------------------------------------
    def inline_css(m: re.Match) -> str:
        href = m.group(1)
        try:
            css = get(resolve(href))
        except Exception as e:  # noqa: BLE001
            print("  css fetch failed:", href, e, flush=True)
            return m.group(0)
        css = re.sub(r"@import[^;]+;", "", css)  # drop external font imports
        return "<style>/* inlined: %s */\n%s\n</style>" % (href, css)

    html = re.sub(
        r'<link[^>]*rel="stylesheet"[^>]*href="([^"]+)"[^>]*>',
        inline_css,
        html,
    )

    # ---- inline <script src=...> preserving order ---------------------------
    chunks = re.split(r'(<script[^>]*src="([^"]+)"[^>]*>\s*</script>)', html)
    out: list[str] = []
    for i, chunk in enumerate(chunks):
        kind = i % 3
        if kind == 2:  # the src URL itself
            try:
                js = get(resolve(chunk))
            except Exception as e:  # noqa: BLE001
                print("  js fetch failed:", chunk, e, flush=True)
                out.append('<script src="%s"></script>' % chunk)
                continue
            assert "</script" not in js.lower(), "unsafe to inline: %s" % chunk
            print("  inlined js: %s (%d bytes)" % (chunk, len(js)), flush=True)
            out.append("<script>/* inlined: %s */\n%s\n</script>" % (chunk, js))
        elif kind == 0:
            out.append(chunk)
        # kind == 1 is the original <script src> tag: replaced above
    html = "".join(out)

    # ---- strip third-party telemetry (boomerang / go-mpulse) -----------------
    html = re.sub(
        r'<script>!function\(a\)\{var e="https://s\.go-mpulse.*?</script>',
        "",
        html,
        flags=re.S,
    )
    html = re.sub(r"<script>\(window\.BOOMR_mq.*?</script>", "", html, flags=re.S)

    # ---- diagnostic beacons --------------------------------------------------
    # 1. error trap: must be the first script so it catches bundle errors
    trap = """<script>
window.onerror=function(m){try{fetch('/diag?err='+encodeURIComponent(String(m).slice(0,180)),{keepalive:true}).catch(function(){})}catch(x){}return false;};
</script>"""
    html = html.replace(
        '<script type="text/javascript" src="/scripts/',
        trap + '\n<script type="text/javascript" src="/scripts/',
        1,
    )
    # 2. parse + render beacons at end of <head> (run after all page scripts)
    beacons = """<script>
try{fetch('/diag?parsed=1',{keepalive:true}).catch(function(){})}catch(e){}
document.addEventListener('DOMContentLoaded',function(){setTimeout(function(){
try{
var w=document.querySelector('.loginformWrapper');
var n=w?w.querySelectorAll('input').length:-1;
fetch('/diag?rendered=1&inputs='+n,{keepalive:true}).catch(function(){});
}catch(e){}},4000);});
</script>"""
    html = html.replace("</head>", beacons + "\n</head>", 1)

    with open("static/sso_login.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("wrote static/sso_login.html (%d bytes)" % len(html), flush=True)


if __name__ == "__main__":
    main()
