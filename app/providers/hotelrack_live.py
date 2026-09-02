from pathlib import Path

from playwright.async_api import (
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)

from app.settings import settings

PROJECT_DIR = Path(__file__).resolve().parents[2]
BROWSER_DATA_DIR = PROJECT_DIR / "browser-data" / "hotelrack"


class HotelrackLiveBrowser:
    def __init__(self) -> None:
        self.playwright: Playwright | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None

    async def start(self) -> None:
        BROWSER_DATA_DIR.mkdir(parents=True, exist_ok=True)

        self.playwright = await async_playwright().start()

        self.context = await self.playwright.chromium.launch_persistent_context(
            user_data_dir=str(BROWSER_DATA_DIR),
            headless=settings.hotelrack_headless,
            viewport={"width": 1440, "height": 900},
        )

        self.page = (
            self.context.pages[0]
            if self.context.pages
            else await self.context.new_page()
        )

        await self.page.goto(
            settings.hotelrack_start_url,
            wait_until="domcontentloaded",
            timeout=60_000,
        )

        print("[Hotelrack] Browser opened.")
        print("[Hotelrack] Administrator should log in in the browser window.")
        print("[Hotelrack] Keep this browser window open.")

    async def status(self) -> dict[str, object]:
        if self.page is None or self.page.is_closed():
            return {
                "running": False,
                "authenticated": False,
                "message": "Hotelrack browser is not running.",
            }

        url = self.page.url
        title = await self.page.title()

        login_detected = (
            "login" in url.lower()
            or "login" in title.lower()
            or "sign in" in title.lower()
        )

        return {
            "running": True,
            "authenticated": not login_detected,
            "title": title,
            "url": url,
            "message": (
                "Hotelrack session appears authenticated."
                if not login_detected
                else "Administrator login is required."
            ),
        }

    async def stop(self) -> None:
        if self.context is not None:
            await self.context.close()

        if self.playwright is not None:
            await self.playwright.stop()

        self.page = None
        self.context = None
        self.playwright = None
