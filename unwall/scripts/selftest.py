#!/usr/bin/env -S UV_NATIVE_TLS=1 uv run --quiet --script
# /// script
# dependencies = ["curl_cffi>=0.7", "truststore>=0.9"]
# ///
"""Offline tests for unwall's classifier and helpers. `--live` adds a real solve round-trip."""
import importlib.machinery
import importlib.util
import subprocess
import sys
import time
from pathlib import Path

here = Path(__file__).resolve().parent
loader = importlib.machinery.SourceFileLoader("unwall", str(here / "unwall"))
spec = importlib.util.spec_from_loader("unwall", loader)
unwall = importlib.util.module_from_spec(spec)
loader.exec_module(unwall)

CF = {"server": "cloudflare", "cf-ray": "8abc-WAW"}
CASES = [
    # (name, status, headers, body, expected protection, expected action)
    ("cf managed challenge header", 403, {**CF, "cf-mitigated": "challenge"}, "<html></html>", "cloudflare_challenge", "solve"),
    ("cf just a moment", 503, CF, "<title>Just a moment...</title><script>window._cf_chl_opt={}</script>", "cloudflare_challenge", "solve"),
    ("cf 1020", 403, CF, "<title>Access denied | x.com used Cloudflare to restrict access</title>Error code: 1020", "cloudflare_block", "stop"),
    ("cf attention required", 403, CF, "<title>Attention Required! | Cloudflare</title>", "cloudflare_block", "stop"),
    ("cf 1015", 429, CF, "<h1>Error 1015</h1> You are being rate limited", "cloudflare_rate_limit", "backoff"),
    ("ddos-guard", 403, {"server": "ddos-guard"}, "<title>DDoS-Guard</title>", "ddos_guard", "solve"),
    ("plain 429", 429, {"retry-after": "30"}, "slow down", "rate_limited", "backoff"),
    ("401", 401, {}, "login", "auth_required", "stop"),
    ("datadome", 403, {}, "<script src='https://geo.captcha-delivery.com/x.js'>", "datadome", "solve"),
    ("cf page with turnstile form", 200, CF, "<form><div class='cf-turnstile' data-sitekey=x></div></form>", "turnstile_widget", "ok"),
    ("normal cf page", 200, CF, "<title>Shop</title>", "none", "ok"),
    ("404", 404, {}, "nope", "http_error", "stop"),
    ("502", 502, {}, "bad gateway", "server_error", "backoff"),
]

fails = 0
for name, st, hd, body, prot, act in CASES:
    got = unwall.classify(st, hd, body)
    ok = got["protection"] == prot and got["action"] == act
    fails += not ok
    print(("PASS" if ok else "FAIL"), name, "" if ok else f"-> {got}")

# upstream FlareSolverr challenge samples (if the source install is present)
samples = unwall.HOME / "html_samples"
for f in sorted(samples.glob("cloudflare_*.html")) if samples.exists() else []:
    got = unwall.classify(503, CF, f.read_text(errors="replace"))
    ok = got["action"] == "solve"
    fails += not ok
    print(("PASS" if ok else "FAIL"), "upstream sample", f.name, "" if ok else f"-> {got}")

text = unwall.html_to_text("<html><head><title>t</title><style>x{}</style></head><body><h1>A</h1><p>b&amp;c</p><script>1</script></body></html>")
ok = text == "A\n\nb&c"
fails += not ok
print(("PASS" if ok else "FAIL"), "html_to_text", "" if ok else repr(text))

# clearance cache: expiry normalisation (selenium 'expiry'), parent-domain lookup, proxy isolation
unwall.CLEARANCE = Path(unwall.STATE) / "selftest-clearance.json"
unwall.CLEARANCE.unlink(missing_ok=True)
unwall.cache_put("shop.example.com", None, {"userAgent": "UA", "cookies": [
    {"name": "cf_clearance", "value": "v", "domain": ".example.com", "expiry": int(time.time()) + 3600}]})
checks = [
    ("cache exact host", unwall.cache_get("shop.example.com", None) is not None),
    ("cache other proxy isolated", unwall.cache_get("shop.example.com", "socks5://p:1") is None),
    ("cache expiry from 'expiry'", abs(unwall.cache_get("shop.example.com", None)["expires"] - time.time() - 3600) < 5),
]
unwall.cache_drop("shop.example.com", None)
checks.append(("cache drop", unwall.cache_get("shop.example.com", None) is None))
unwall.CLEARANCE.unlink(missing_ok=True)
for name, ok in checks:
    fails += not ok
    print(("PASS" if ok else "FAIL"), name)

if "--live" in sys.argv:
    url = "https://www.scrapingcourse.com/cloudflare-challenge"
    r = subprocess.run([str(here / "unwall"), "fetch", url, "--force-solve", "-f", "text", "--json"], capture_output=True, text=True)
    ok = r.returncode == 0 and "bypassed the cloudflare challenge" in r.stdout.lower()
    fails += not ok
    print(("PASS" if ok else "FAIL"), "live solve", "" if ok else (r.stdout + r.stderr)[-800:])
    r = subprocess.run([str(here / "unwall"), "fetch", url, "-o", "/dev/null", "--json"], capture_output=True, text=True)
    ok = '"tier": "cached"' in r.stdout
    fails += not ok
    print(("PASS" if ok else "FAIL"), "live cached reuse", "" if ok else r.stdout[-500:])

print(f"\n{'OK' if not fails else f'{fails} FAILED'}")
sys.exit(1 if fails else 0)
