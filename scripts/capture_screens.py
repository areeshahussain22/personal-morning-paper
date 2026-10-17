"""Optional Playwright capture helper for demo recording."""
from __future__ import annotations

import asyncio
from pathlib import Path


async def main() -> None:
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise SystemExit("Install optional Playwright support before capturing screens.") from exc
    output = Path("out/demo/screens")
    output.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page(viewport={"width": 1920, "height": 1080})
        for name, url in {"onboarding": "http://127.0.0.1:8000/", "preparing": "http://127.0.0.1:8000/preparing"}.items():
            await page.goto(url)
            await page.screenshot(path=str(output / f"{name}.png"), full_page=True)
        await page.goto("http://127.0.0.1:8000/demo/login/featured")
        for name, url in {
            "edition": "http://127.0.0.1:8000/edition/today",
            "archive": "http://127.0.0.1:8000/archive",
            "profile": "http://127.0.0.1:8000/profile",
            "charts": "http://127.0.0.1:8000/demo/charts",
            "stats": "http://127.0.0.1:8000/demo/stats",
        }.items():
            await page.goto(url)
            await page.screenshot(path=str(output / f"{name}.png"), full_page=True)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
