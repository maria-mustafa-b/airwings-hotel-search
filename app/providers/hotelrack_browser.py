from pathlib import Path

from playwright.sync_api import BrowserContext, Playwright

from app.settings import settings

PROJECT_DIR = Path(__file__).resolve().parents[2]
BROWSER_DATA_DIR = PROJECT_DIR / "browser-data" / "hotelrack"


class HotelrackBrowserProvider:
    def __init__(self, playwright: Playwright):
        self.playwright = playwright
        self.context: BrowserContext | None = None

    def open(self) -> BrowserContext:
        BROWSER_DATA_DIR.mkdir(parents=True, exist_ok=True)

        self.context = self.playwright.chromium.launch_persistent_context(
            user_data_dir=str(BROWSER_DATA_DIR),
            headless=settings.hotelrack_headless,
            viewport={"width": 1440, "height": 900},
        )

        return self.context

    def verify_session(self) -> dict[str, str]:
        if self.context is None:
            raise RuntimeError("Browser context has not been opened.")

        page = self.context.pages[0] if self.context.pages else self.context.new_page()

        page.goto(
            settings.hotelrack_start_url,
            wait_until="domcontentloaded",
            timeout=60_000,
        )

        page.wait_for_timeout(3000)

        return {
            "url": page.url,
            "title": page.title(),
        }

    def close(self) -> None:
        if self.context is not None:
            self.context.close()
            self.context = None
