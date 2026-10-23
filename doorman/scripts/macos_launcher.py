"""Run FlareSolverr from source without Docker (macOS, or Linux without Xvfb).

Upstream assumes Linux: in headless mode it starts an Xvfb display. On macOS
there is no Xvfb, so we turn that into a no-op and let Chrome run with
--headless=new (FlareSolverr already strips "HeadlessChrome" from the UA).
Set HEADLESS=false to see the browser window when debugging.
"""
import os
import runpy
import shutil
import sys

src = os.path.join(os.environ.get("FLARESOLVERR_HOME", os.path.expanduser("~/.local/share/flaresolverr")), "src")
sys.path.insert(0, src)
os.chdir(os.path.dirname(src))

try:  # corporate TLS interception: trust the macOS keychain, not just certifi
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

import utils  # noqa: E402  (FlareSolverr's own module)

if shutil.which("Xvfb") is None:  # macOS, or Linux without xvfb installed
    utils.start_xvfb_display = lambda: None
runpy.run_path(os.path.join(src, "flaresolverr.py"), run_name="__main__")
