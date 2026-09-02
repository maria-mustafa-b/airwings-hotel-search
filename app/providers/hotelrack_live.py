import asyncio
import json
from datetime import date
from pathlib import Path
from typing import Any

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

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
        self.search_lock = asyncio.Lock()

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

        search_field = self.page.locator("#txt_CitySearch")

        if await search_field.count() > 0 and await search_field.is_visible():
            print("[Hotelrack] Existing authenticated session is ready.")
            return

        sign_in_button = self.page.get_by_role(
            "button",
            name="Sign in",
        )

        if (
            await sign_in_button.count() > 0
            and await sign_in_button.is_visible()
        ):
            print("[Hotelrack] Attempting automatic sign-in.")

            await self.page.wait_for_timeout(1500)
            await sign_in_button.click()

            try:
                await self.page.locator("#txt_CitySearch").wait_for(
                    state="visible",
                    timeout=60_000,
                )

                print("[Hotelrack] Automatic sign-in succeeded.")
                return

            except PlaywrightTimeoutError:
                print(
                    "[Hotelrack] Automatic sign-in was not completed. "
                    "Administrator action may be required."
                )
                return

        print(
            "[Hotelrack] Administrator login is required on the "
            "backend machine."
        )

    async def status(self) -> dict[str, object]:
        if self.page is None or self.page.is_closed():
            return {
                "running": False,
                "authenticated": False,
                "message": "Hotelrack browser is not running.",
            }

        search_form_visible = await self.page.locator(
            "#txt_CitySearch"
        ).count() > 0

        return {
            "running": True,
            "authenticated": search_form_visible,
            "title": await self.page.title(),
            "url": self.page.url,
            "message": (
                "Hotelrack search form is available."
                if search_form_visible
                else "Administrator login is required."
            ),
        }

    async def search_hotels(
        self,
        city: str,
        hotel_name: str | None,
        check_in: date,
        check_out: date,
        adults: int,
        children: int,
    ) -> list[dict[str, Any]]:
        if self.page is None or self.page.is_closed():
            raise RuntimeError("Hotelrack browser is not running.")

        async with self.search_lock:
            page = self.page

            destination = hotel_name or city

            city_input = page.locator("#txt_CitySearch")

            if not await city_input.is_visible():
                raise RuntimeError(
                    "Hotelrack is not logged in or its search form is unavailable."
                )

            # Dismiss a warning left by a previous failed search.
            warning_ok = page.locator("#HQ_ShowBTNOk")

            if await warning_ok.is_visible():
                await warning_ok.click()

            await city_input.click()
            await city_input.fill("")
            await city_input.fill(destination)

            # Wait for Hotelrack's autocomplete results.
            suggestion = page.locator(".area-sec").filter(
                has_text=destination
            ).first

            await suggestion.wait_for(
                state="visible",
                timeout=15_000,
            )

            await suggestion.click()

            # Hotelrack stores the selected destination in a hidden field.
            # Typing text alone does not populate this field.
            await page.wait_for_function(
                """
                () => {
                    const field = document.querySelector("#hdnCityId");
                    return field &&
                           field.value &&
                           field.value !== "undefined" &&
                           field.value !== "null";
                }
                """,
                timeout=10_000,
            )

            check_in_text = check_in.strftime("%d %b %Y")
            check_out_text = check_out.strftime("%d %b %Y")

            await page.locator("#txtChkInDate").fill(check_in_text)
            await page.locator("#txtChkInDate").dispatch_event("change")
            await page.locator("#txtChkOutDate").fill(check_out_text)
            await page.locator("#txtChkOutDate").dispatch_event("input")
            await page.locator("#txtChkOutDate").dispatch_event("change")


            # Close the calendar without touching the selected destination.
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(300)

            # Hotelrack visually replaces these select elements with custom
            # controls, so the original HTML selects are present but hidden.
            adult_select = page.locator("#ddlAdult_1")
            children_select = page.locator("#selectdrop")

            await adult_select.select_option(
                str(adults),
                force=True,
            )

            await adult_select.dispatch_event("change")

            await children_select.select_option(
                str(children),
                force=True,
            )

            await children_select.dispatch_event("change")

            print(
                f"[Hotelrack] Guests set: "
                f"{adults} adult(s), {children} child(ren)."
            )

            selected_city_id = await page.locator(
                "#hdnCityId"
            ).input_value()

            if selected_city_id in ("", "undefined", "null"):
                raise RuntimeError(
                    "Hotelrack did not register the selected destination."
                )
            if "SearchResult" in page.url:
                raise RuntimeError(
                    "Hotelrack navigated before the Search button was clicked."
                )
            if self.context is None:
                raise RuntimeError("Hotelrack browser context is unavailable.")

            # Find the visible Search control located in the main search form.
            search_button = None
            search_candidates = await page.get_by_text(
                "Search",
                exact=True,
            ).all()

            for candidate in search_candidates:
                if not await candidate.is_visible():
                    continue

                box = await candidate.bounding_box()

                # Hotelrack's main Search button is on the right side.
                if box is not None and box["x"] > 400:
                    search_button = candidate
                    break

            if search_button is None:
                raise RuntimeError(
                    "Could not find Hotelrack's visible Search button."
                )

            print("[Hotelrack] Visible Search button found.")

            # Listen across the entire browser context, including navigations
            # and any newly created pages.
            loop = asyncio.get_running_loop()
            response_future = loop.create_future()

            def capture_search_response(response):
                if (
                    "getsearchresult" in response.url.lower()
                    and not response_future.done()
                ):
                    response_future.set_result(response)

            self.context.on("response", capture_search_response)

            try:
                await search_button.scroll_into_view_if_needed()
                await page.keyboard.press("Escape")
                await page.wait_for_timeout(300)

                # The visible "Search" text is inside Hotelrack's actual
                # clickable button/link. Click its clickable parent directly.
                click_result = await search_button.evaluate(
                    """
                    element => {
                        const clickable = element.closest(
                            "button, a, [role='button'], input[type='submit']"
                        ) || element;

                        const details = {
                            tag: clickable.tagName,
                            id: clickable.id || null,
                            className:
                                typeof clickable.className === "string"
                                    ? clickable.className
                                    : null
                        };

                        clickable.click();
                        return details;
                    }
                    """
                )

                print(
                    f"[Hotelrack] Search control clicked: {click_result}"
                )
                print("[Hotelrack] Waiting for GetSearchResult...")

                response = await asyncio.wait_for(
                    response_future,
                    timeout=120,
                )

                print(
                    f"[Hotelrack] Captured response: {response.url}"
                )
            finally:
                self.context.remove_listener(
                    "response",
                    capture_search_response,
                )            
            payload = await response.json()

            # Hotelrack sometimes returns JSON encoded inside a string.
            if isinstance(payload, str):
                payload = json.loads(payload)

            raw_results = payload.get("SearchResults", [])
            currency = payload.get("Currency", "AED")
            print(
                f"[Hotelrack] Received {len(raw_results)} hotel result(s)."
            )
            return [
                {
                    "hotel_id": item.get("HId"),
                    "hotel_name": item.get("HName"),
                    "address": item.get("Address"),
                    "location": item.get("Loc"),
                    "stars": item.get("Star"),
                    "image": item.get("Img"),
                    "price_from": item.get("SCost"),
                    "currency": currency,
                    "available": bool(item.get("Avail")),
                }
                for item in raw_results
            ]

    async def stop(self) -> None:
        if self.context is not None:
            await self.context.close()

        if self.playwright is not None:
            await self.playwright.stop()

        self.page = None
        self.context = None
        self.playwright = None
