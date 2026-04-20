"""Record the README demo GIF.

What this does:
1. Wipes the local SQLite trace DB so the demo starts from empty.
2. Assumes `skein serve` is already running on http://127.0.0.1:5050.
3. Pre-seeds the full scenario set so every page shows real data on arrival.
4. Opens Chromium (Playwright) with video recording, walks the dashboard
   with generous lingers so HTMX 5s auto-refresh ticks fire visibly,
   clicks into a failing task to show the timeline/cascade, scrolls the
   merged conversation view, and uses the search box.
5. Fires a small live burst while the Tasks page is visible so new rows
   pop in on the next HTMX tick.
6. Saves a .webm, then converts to a palette-optimized .gif via ffmpeg.

Output: docs/screenshots/00_demo.gif
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import sys
from pathlib import Path

from playwright.async_api import async_playwright

import skein
from skein._demo_data import build_scenarios

BASE = "http://127.0.0.1:5050"
REPO = Path(__file__).resolve().parent.parent
OUT_DIR = REPO / "docs" / "screenshots"
WEBM = OUT_DIR / "_demo_recording.webm"
GIF = OUT_DIR / "00_demo.gif"

VIEWPORT = {"width": 1280, "height": 800}


def seed_scenarios(client, scenarios) -> None:
    """Push every agent card + event synchronously so the dashboard is
    fully populated before the browser opens."""
    for card in scenarios.agent_cards:
        client.send_agent_card(card)
    for entry in scenarios.events:
        client.send(entry["payload"], direction=entry["direction"])


async def live_burst(client, scenarios, *, count: int = 8, gap: float = 0.4) -> None:
    """Re-send the last few events (with new IDs via the scenario builder)
    so the Tasks page visibly gets new rows during the walkthrough."""
    tail = scenarios.events[-count:]
    for entry in tail:
        client.send(entry["payload"], direction=entry["direction"])
        await asyncio.sleep(gap)


async def drive_browser(page, live_burst_coro) -> None:
    # Overview — already populated. Let HTMX tick at least once.
    await page.goto(BASE + "/", wait_until="networkidle")
    await page.wait_for_timeout(6500)

    # Tasks list — already populated. Kick off live burst so rows pop in.
    await page.goto(BASE + "/tasks", wait_until="networkidle")
    await page.wait_for_timeout(2000)
    burst = asyncio.create_task(live_burst_coro)
    # Use the search box to demonstrate filtering
    try:
        await page.fill("input[name='q']", "research")
        await page.wait_for_timeout(1500)
        await page.fill("input[name='q']", "")
    except Exception:
        pass
    # Wait long enough for a 5s HTMX tick after the burst lands
    await page.wait_for_timeout(7000)
    await burst

    # Drill into a failing task — cascade + timeline
    await page.goto(BASE + "/tasks/task-research-review", wait_until="networkidle")
    await page.wait_for_timeout(2500)
    await page.evaluate(
        "window.scrollTo({top: document.body.scrollHeight, behavior: 'smooth'})"
    )
    await page.wait_for_timeout(3500)
    await page.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})")
    await page.wait_for_timeout(1500)

    # Contexts list -> merged conversation
    await page.goto(BASE + "/contexts", wait_until="networkidle")
    await page.wait_for_timeout(3000)
    await page.goto(
        BASE + "/contexts/ctx-research-2026-04-19", wait_until="networkidle"
    )
    await page.wait_for_timeout(2000)
    await page.evaluate(
        "window.scrollTo({top: document.body.scrollHeight / 2, behavior: 'smooth'})"
    )
    await page.wait_for_timeout(3000)
    await page.evaluate(
        "window.scrollTo({top: document.body.scrollHeight, behavior: 'smooth'})"
    )
    await page.wait_for_timeout(2500)

    # Failures
    await page.goto(BASE + "/failures", wait_until="networkidle")
    await page.wait_for_timeout(3500)

    # Spec warnings
    await page.goto(BASE + "/spec-warnings", wait_until="networkidle")
    await page.wait_for_timeout(3500)


async def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Sanity: server must be up
    import urllib.request
    try:
        urllib.request.urlopen(BASE + "/trace/health", timeout=2).read()
    except Exception:
        print(
            f"error: skein serve not reachable at {BASE} — start it first",
            file=sys.stderr,
        )
        return 2

    # Clean DB so the recording starts from empty, then pre-seed.
    db_path = REPO / "data" / "skein.db"
    for ext in ("", "-wal", "-shm"):
        p = db_path.with_suffix(db_path.suffix + ext) if ext else db_path
        if p.exists():
            try:
                p.unlink()
            except OSError:
                from skein.db import open_db
                conn = open_db(db_path)
                for table in (
                    "artifacts", "state_transitions", "message_references",
                    "spec_warnings", "messages", "tasks", "agents",
                ):
                    conn.execute(f"DELETE FROM {table}")
                conn.close()
                break

    client = skein.SkeinClient(BASE) if hasattr(skein, "SkeinClient") else None
    if client is None:
        from skein.sdk.client import SkeinClient as _SC
        client = _SC(BASE)
    scenarios = build_scenarios()

    # Pre-seed everything so pages render populated immediately.
    seed_scenarios(client, scenarios)
    # Small settle so the server finishes writing before we start recording.
    await asyncio.sleep(1.0)

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        ctx = await browser.new_context(
            viewport=VIEWPORT,
            device_scale_factor=1,
            color_scheme="dark",
            record_video_dir=str(OUT_DIR),
            record_video_size=VIEWPORT,
        )
        page = await ctx.new_page()

        await drive_browser(page, live_burst(client, scenarios))

        await ctx.close()
        await browser.close()

    candidates = sorted(OUT_DIR.glob("*.webm"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        print("error: no .webm produced", file=sys.stderr)
        return 1
    src = candidates[0]
    if WEBM.exists():
        WEBM.unlink()
    src.rename(WEBM)
    print(f"wrote {WEBM} ({WEBM.stat().st_size // 1024} KB)")

    if not shutil.which("ffmpeg"):
        print("warning: ffmpeg not found; skipping GIF conversion", file=sys.stderr)
        return 0
    palette = OUT_DIR / "_palette.png"
    fps = 12
    width = 960
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(WEBM),
         "-vf", f"fps={fps},scale={width}:-1:flags=lanczos,palettegen=stats_mode=diff",
         str(palette)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(WEBM), "-i", str(palette),
         "-lavfi", f"fps={fps},scale={width}:-1:flags=lanczos[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=4",
         str(GIF)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    palette.unlink(missing_ok=True)
    WEBM.unlink(missing_ok=True)
    print(f"wrote {GIF} ({GIF.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
