"""Generate the dashboard screenshots used in the README.

Run with `skein serve` (and `skein demo` already executed) on
http://127.0.0.1:5050, then:

    python packaging/screenshots.py

Outputs PNGs into docs/screenshots/.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright

BASE = "http://127.0.0.1:5050"
OUT = Path(__file__).resolve().parent.parent / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)

# (filename, path-on-server, optional pre-screenshot delay seconds)
SHOTS: list[tuple[str, str, float]] = [
    ("01_overview.png",         "/", 0.5),
    ("02_tasks.png",            "/tasks", 0.5),
    ("03_task_detail.png",      "/tasks/task-research-review", 0.5),
    ("04_contexts.png",         "/contexts", 0.5),
    ("05_context_detail.png",   "/contexts/ctx-research-2026-04-19", 0.5),
    ("06_failures.png",         "/failures", 0.5),
    ("07_spec_warnings.png",    "/spec-warnings", 0.5),
]


async def main() -> int:
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        ctx = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            device_scale_factor=2,  # crisp on Retina-class displays
            color_scheme="dark",
        )
        page = await ctx.new_page()
        for fname, path, delay in SHOTS:
            url = BASE + path
            print(f"  - {url}  ->  {fname}")
            await page.goto(url, wait_until="networkidle")
            await page.wait_for_timeout(int(delay * 1000))
            target = OUT / fname
            await page.screenshot(path=str(target), full_page=True)
        await ctx.close()
        await browser.close()
    print(f"wrote {len(SHOTS)} screenshots to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
