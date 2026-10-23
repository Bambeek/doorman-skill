---
name: unwall
description: >-
  Fetch web pages that ordinary retrieval cannot get because of a browser challenge:
  Cloudflare "Just a moment...", managed/JS challenge, Turnstile interstitial, DDoS-Guard,
  or a 403/503 from a bot wall. Use when WebFetch/curl returns a challenge page, 403 with
  cf-mitigated, or empty JS shell, or when the user mentions Cloudflare, FlareSolverr,
  cf_clearance, or scraping a protected site. Handles the whole path: classifies the
  protection, starts a local FlareSolverr itself (Docker or native macOS, no Docker needed),
  solves once, caches cf_clearance + User-Agent and reuses them in a Chrome-fingerprinted
  HTTP client (~0.2 s/page instead of ~15 s), batch-crawls with per-host rate limits, and
  exports cookies for curl / yt-dlp / Playwright.
---

# unwall

One CLI, `scripts/unwall`, wraps the whole job. It is a self-contained `uv` script (deps install
themselves on first run). Always call it by absolute path, from this skill's directory
(`~/.claude/skills/unwall` for a copied install, the plugin cache for a plugin install):

```bash
UNWALL=~/.claude/skills/unwall/scripts/unwall
$UNWALL fetch https://example.com/page -f text
```

## How it works: the escalation ladder

Every `fetch` takes the cheapest tier that works and reports which one in `tier`:

| Tier | What happens | Cost |
|---|---|---|
| `cached` | Reuse stored `cf_clearance` + the exact solver User-Agent in curl_cffi (Chrome TLS fingerprint). If the edge challenges again, the entry is dropped and the ladder continues. | ~0.2-0.7 s |
| `direct` | Plain request with a Chrome TLS/HTTP2 fingerprint. Many "protected" sites only block python-requests/curl fingerprints, so this alone often passes. | ~0.3 s |
| `solve` | FlareSolverr drives a real Chrome, passes the challenge, returns the DOM. Cookies get cached, so the next request to that host goes back to `cached`. | 10-30 s |
| `solve+replay` | For POST: solve on a GET, then replay the POST with the clearance. | 10-30 s |

The local FlareSolverr starts automatically on the first `solve` (`--no-autostart` turns that off).

## Commands

```bash
$UNWALL probe URL                        # what protects it? no solving, ~0.4 s
$UNWALL fetch URL [-f html|text|raw] [-o FILE] [--json]
$UNWALL fetch URL --render --wait 3      # always use the browser (JS-rendered content), let it settle 3 s
$UNWALL fetch URL --screenshot shot.png  # PNG of the rendered page (implies browser tier)
$UNWALL fetch URL -d 'q=x&page=2'        # POST (form-encoded)
$UNWALL batch urls.txt --out DIR -f text # many URLs: 1 solve per host, the rest reuse it
$UNWALL solve URL                        # only get + cache clearance
$UNWALL cookies HOST --format header|netscape|json|curl|playwright
$UNWALL up | down | doctor | install     # solver lifecycle
$UNWALL session create|list|destroy [ID] # warm browser sessions (multi-step flows)
$UNWALL raw '{"cmd":"request.get","url":"..."}'   # anything else in the /v1 API
```

Useful flags: `--force-solve` (ignore cache), `--no-solve` (never escalate), `--fast` (browser
skips images/CSS/fonts), `--max-timeout 90` (browser budget), `--proxy socks5://...`,
`-H 'Name: value'` (extra header on the HTTP tiers), `--delay`/`--retries` (batch).

## Output contract

- Body goes to stdout (or `-o FILE`). One JSON metadata line goes to stderr. With `--json`,
  stdout gets a single JSON object holding the metadata and `body`.
- Progress events (`challenge`, `solve_retry`, `backoff`, `item`, `solver_started`) go to stderr as JSON lines.
- Exit 0 = got the content, 2 = finished but the content is a wall or error page (see `protection`),
  1 = tool or solver failure (`error`: `solver_down`, `timeout`, `blocked`, `solve_failed`, ...).
- `-f text` strips script/style/head and gives readable text. Use it when you will read the page
  yourself; use `html` when you need to parse it, `raw` for binary (PDF, images, JSON APIs).
- `batch` writes `NNNN_<host_path>.{html,txt}` plus an appendable `manifest.jsonl` (one record per URL).

## Reading `protection` and what to do

| `protection` | `action` | What it means and what to do |
|---|---|---|
| `none` | ok | Done. |
| `cloudflare_challenge`, `ddos_guard` | solve | Normal case; unwall escalates by itself. |
| `turnstile_widget` | ok | The page loaded, a Turnstile sits on a form. Only if you really need the token: `--turnstile-tabs N` (returns `turnstile_token`). |
| `cloudflare_block` (1020 etc.) | **stop** | The site owner blocks this IP/client. Solving will not help. Tell the user; do not rotate IPs or proxies to get around it unless the user owns the site or explicitly arranged that access. |
| `cloudflare_rate_limit`, `rate_limited`, `server_error` | backoff | Slow down (`--delay`). batch retries with exponential backoff by itself. |
| `auth_required` | **stop** | Needs credentials. Out of scope; ask the user. |
| `akamai`, `datadome`, `perimeterx`, `imperva`, `aws_waf` | solve (best effort) | Not what FlareSolverr is built for. `--render` sometimes passes JS-only checks; a hard CAPTCHA will not. Report it instead of looping. |
| `recaptcha_wall`, `hcaptcha_wall` | solve (best effort) | An interactive CAPTCHA. Do not wire in CAPTCHA-solving services. Ask the user to open it in their own browser. |

## Patterns

**Agent reading a protected page:** `$UNWALL fetch URL -f text`, then read stdout. If `ok` is false,
read `detail` instead of retrying blindly.

**Crawl a listing:** fetch page 1 (`-f html`), extract links, write them to a file, then
`$UNWALL batch links.txt --out data/ -f html --delay 2`. Only the first URL per host pays the browser cost.

**Hand the clearance to another tool.** The cookie only works with the same User-Agent
(printed on stderr) and from the same IP:
```bash
$UNWALL solve https://site.example/
curl -sL -A "$($UNWALL cookies site.example --format json | jq -r .user_agent)" \
     -b "$($UNWALL cookies site.example)" https://site.example/api/items
$UNWALL cookies site.example --format netscape > cookies.txt   # yt-dlp --cookies / wget --load-cookies
$UNWALL cookies site.example --format playwright > state.json  # context.add_cookies(json.load(...))
```

**Code that has to run unattended** (a scraper in the user's project): call FlareSolverr's
`/v1` only when a response is classified as a challenge, cache `cf_clearance` + `userAgent`,
and use `curl_cffi` with `impersonate="chrome"` for everything else. Copy `classify()` and the
cache logic from `scripts/unwall` instead of inventing new ones.

## Solver setup (handled by `unwall up`)

- **Docker/Podman present:** runs `ghcr.io/flaresolverr/flaresolverr:v3.5.2` bound to `127.0.0.1:8191`.
- **No Docker (this Mac):** installs FlareSolverr from source into `~/.local/share/flaresolverr`
  (git + uv venv, Python 3.13) and starts it through `scripts/macos_launcher.py`, which turns off
  the upstream Xvfb requirement and trusts the macOS keychain (corporate TLS interception).
  It uses the installed Google Chrome. `unwall up --visible` shows the browser window for debugging.
- Remote solver: `export FLARESOLVERR_URL=http://host:8191` (unwall will not try to start it).
- State lives in `~/.cache/unwall/` (clearance cache with 0600 permissions, solver log, pid). `unwall down` stops what unwall started.
- After a FlareSolverr release or a Chrome major update: `unwall down && unwall install && unwall up`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `solver_down` | `unwall up`; check `~/.cache/unwall/flaresolverr.log`. |
| `timeout` after retry | `--max-timeout 120`; try `--visible` to watch it; the site may serve an interactive CAPTCHA. |
| `cached` keeps falling back to `solve` | Clearance is bound to IP + UA. A VPN/proxy change invalidates it (the cache keys on `--proxy`). |
| SSL errors on the direct tier | unwall falls back to a CA bundle exported from the macOS keychain; set `UNWALL_CA_BUNDLE=/path.pem` for a custom one; `--insecure` is the last resort. |
| Chromedriver/Chrome version mismatch | `unwall install` (pulls upstream), then restart. |
| Page is empty or a JS shell | `--render --wait 3` (content rendered client-side). |

Run `scripts/selftest.py` after changing unwall (offline classifier and cache tests; `--live` adds a real solve).

## Boundaries

- This gets past bot *interstitials* on content the user may otherwise view in a normal browser.
  It is not for logging in, paywalls, or access the site owner explicitly denied (1020, 401/403 walls).
- Keep request rates human-like (batch defaults to 1.5 s/host) and respect the site's terms and robots policy.
- GET is read-only. A POST can change state on the target, so confirm with the user before
  POSTing anything other than a search or filter form.
- Never expose the solver beyond localhost.
