# doorman

<p align="center"><img src="assets/banner.svg" alt="doorman: a Claude Code skill that fetches pages behind Cloudflare walls. Solve once, then walk in at about 0.2 s through the cached, direct and solve tiers. A brick wall with its door open, a page stepping out and a cf_clearance cookie beside it." width="680"></p>

A Claude skill that fetches pages behind Cloudflare and DDoS-Guard browser challenges.

It solves a challenge once in a real Chrome (through [FlareSolverr](https://github.com/FlareSolverr/FlareSolverr)),
keeps the `cf_clearance` cookie together with the exact User-Agent, and from then on fetches
the same host with a Chrome-fingerprinted HTTP client in a fraction of a second. It tells a
challenge from a real block, so it stops where solving cannot help.

## The escalation ladder

Every fetch takes the cheapest tier that works:

| tier | what happens | cost |
| --- | --- | --- |
| `cached` | Stored `cf_clearance` + solver User-Agent, sent with curl_cffi (Chrome TLS fingerprint). A stale entry is dropped and the ladder goes on. | ~0.2-0.7 s |
| `direct` | Plain request with a Chrome TLS/HTTP2 fingerprint. Many sites only block non-browser fingerprints. | ~0.3 s |
| `solve` | FlareSolverr drives Chrome through the challenge; the cookies are cached for next time. | 10-30 s |
| `solve+replay` | POST: solve on a GET, then replay the POST with the clearance. | 10-30 s |

Measured on a Cloudflare-protected test page:

| scenario | result |
| --- | --- |
| plain curl | 403, `cf-mitigated: challenge` |
| first fetch (solve) | 200 in 14-17 s |
| next fetch (cached) | 200 in 0.2-0.7 s |
| deliberately broken cookie | detected, solved again, 200 |
| curl with the exported clearance + UA | 200 |
| batch of 4 URLs | 3 from cache with no browser, the 429 one backed off |

## Compared with a thin FlareSolverr wrapper

| | thin wrapper | doorman |
| --- | --- | --- |
| solver | must already be running | `up` starts it: Docker if present, otherwise native from source (macOS without Xvfb works) |
| corporate TLS interception | breaks on certificates | trusts the macOS keychain (`truststore`, `UV_NATIVE_TLS`, exported CA bundle) |
| every request | full browser, ~15 s | cache first, ~0.2 s after one solve |
| TLS fingerprint | urllib | curl_cffi impersonating Chrome |
| protection detection | none | Cloudflare challenge / 1020 / 1015, DDoS-Guard, 429, 401, Akamai, DataDome, PerimeterX, Imperva, AWS WAF, CAPTCHA walls |
| what to do next | raw JSON | `action`: solve, stop or back off; never loops on a hard block |
| expired clearance | n/a | detected, dropped, solved again in the same call |
| flaky solve | error | one automatic retry |
| many URLs | none | `batch`: one solve per host, per-host delay, backoff, `manifest.jsonl` |
| output | JSON with HTML inside | `html`, readable `text`, or `raw` bytes, to stdout or a file |
| JS-rendered pages | none | `--render --wait N`, `--fast` |
| screenshot | none | `--screenshot page.png` |
| proxy | none | `--proxy`; the cache is kept per proxy, since the clearance is bound to the IP |
| cookie export | none | header, Netscape (curl, wget, yt-dlp), JSON, curl command, Playwright |
| tests | `--help` smoke test | 22 offline tests (classifier on FlareSolverr's own samples, cache, text) + `--live` |

## Use

```bash
DOORMAN=~/.claude/skills/doorman/scripts/doorman
$DOORMAN probe https://example.com/            # what protects it, no solving
$DOORMAN fetch https://example.com/page -f text
$DOORMAN batch urls.txt --out pages/ -f html --delay 2
$DOORMAN cookies example.com --format netscape > cookies.txt
$DOORMAN doctor
```

Body goes to stdout (or `-o FILE`), one JSON metadata line to stderr, or everything as JSON
with `--json`. Exit 0 means content, 2 means a wall or error page (see `protection`), 1 means
a tool or solver failure. The full command list and the agent instructions are in
[`doorman/SKILL.md`](doorman/SKILL.md).

## Install

As a plugin in Claude Code:

```
/plugin marketplace add Bambeek/doorman-skill
/plugin install doorman-skill@doorman-skill
```

Or copy the folder:

```bash
git clone https://github.com/Bambeek/doorman-skill.git
cp -r doorman-skill/doorman ~/.claude/skills/
```

Needs [uv](https://docs.astral.sh/uv/) (the CLI installs `curl_cffi` and `truststore` by
itself) and Google Chrome or Docker for the solver. `doorman up` installs FlareSolverr into
`~/.local/share/flaresolverr` the first time it has to.

## Boundaries

doorman gets past bot interstitials on pages you could open in a normal browser. It does not
log in, open paywalls, solve interactive CAPTCHAs, or work around a block the site owner set
on purpose (Cloudflare 1020, 401, 403 walls): it reports those and stops. Batch keeps a
per-host delay; respect each site's terms. The solver listens on localhost only.

MIT licence.
