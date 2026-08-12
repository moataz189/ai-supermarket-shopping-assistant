"""One-time, manual, out-of-band session capture. Run locally on a machine with a real
display — never in CI, never in a container — once per retailer, before that retailer can
be used by the automated flow:

    python -m mcp_servers.retailer_cart_mcp.login shufersal
    python -m mcp_servers.retailer_cart_mcp.login rami_levy

Opens a real, visible browser, lets you log in by hand, and saves the resulting session
(cookies/storage) to sessions/<retailer>.json with restrictive (owner-only) permissions —
these files carry live login cookies and must never be committed, logged, or returned
through the API, and must never be baked into a Docker image. The automated flow
(server.py / automation.py) never performs a login itself; this script is the only place a
session is ever captured.

Getting a captured session file into a deployed environment is out of scope here — that's
CP11/CP13's job, via a Kubernetes Secret mounted as a volume (or another equally secure
external mechanism), never a plain ConfigMap or a file baked into the image.
"""

import asyncio
import os
import stat
import sys

from playwright.async_api import async_playwright

from mcp_servers.retailer_cart_mcp.adapters.rami_levy import RamiLevyAdapter
from mcp_servers.retailer_cart_mcp.adapters.shufersal import ShufersalAdapter

ADAPTERS = {"shufersal": ShufersalAdapter, "rami_levy": RamiLevyAdapter}
SESSIONS_DIR = os.environ.get("RETAILER_SESSIONS_DIR", "sessions")

# Deliberately NOT trimming large localStorage entries (a prior version dropped anything
# over 20KB, assuming it was disposable analytics cache). Confirmed live, 2026-08-13: on
# Rami Levy that assumption was wrong — the large entry is a full serialized Vuex/Pinia
# store snapshot (cart/checkout/authuser/preferences), real application state the site
# uses for cart-to-account linkage. Dropping it produced sessions where add-to-cart
# succeeded server-side but never appeared in the account's real cart. Saving the session
# untrimmed is what's confirmed working; shrinking it for GitHub Secrets' size limit is a
# separate, not-yet-solved problem — not a return to trimming.


async def main(retailer: str) -> None:
    adapter = ADAPTERS[retailer]()
    os.makedirs(SESSIONS_DIR, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)  # visible — you log in by hand
        try:
            context = await browser.new_context()
            page = await context.new_page()
            await adapter.open_site(page)

            input(
                f"A browser window opened to {retailer}'s site. Log into your account there, "
                "then come back here and press Enter..."
            )

            session_path = os.path.join(SESSIONS_DIR, f"{retailer}.json")
            await context.storage_state(path=session_path)
            os.chmod(session_path, stat.S_IRUSR | stat.S_IWUSR)  # 0600 — live cookies inside
            print(f"Saved {retailer} login session to {session_path}")
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
