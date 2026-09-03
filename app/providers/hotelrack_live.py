import asyncio
import json
from datetime import date
from pathlib import Path
from typing import Any

from decimal import Decimal, InvalidOperation

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

def calculate_airwings_price(raw_price: object) -> str | None:
    if raw_price is None:
        return None

    try:
        base_price = Decimal(str(raw_price))
        final_price = base_price + settings.airwings_markup_aed
        return f"{final_price:.2f}"
    except (InvalidOperation, TypeError, ValueError):
        return None

class InvalidDestinationError(ValueError):
    pass

class HotelrackLiveBrowser:
    def __init__(self) -> None:
        self.playwright: Playwright | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None
        self.search_page_url: str | None = None
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
            self.search_page_url = self.page.url
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
                self.search_page_url = self.page.url
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
        children_ages: list[int],
    ) -> list[dict[str, Any]]:
        if self.page is None or self.page.is_closed():
            raise RuntimeError("Hotelrack browser is not running.")

        async with self.search_lock:
            page = self.page
            city_input = page.locator("#txt_CitySearch")

            # After a previous search, Hotelrack remains on its results page.
            # Return to the authenticated search form before starting again.
            if not await city_input.is_visible():
                if self.search_page_url is None:
                    raise RuntimeError(
                        "The authenticated Hotelrack search URL is unavailable."
                    )

                print("[Hotelrack] Returning to the search form.")

                await page.goto(
                    self.search_page_url,
                    wait_until="domcontentloaded",
                    timeout=60_000,
                )

                city_input = page.locator("#txt_CitySearch")

                await city_input.wait_for(
                    state="visible",
                    timeout=30_000,
                )

            # Remember the current session-specific search URL.
            self.search_page_url = page.url

            # Hotel name is optional, but city is always included.
            destination = (
                f"{hotel_name}, {city}"
                if hotel_name
                else city
            )

            print(f"[Hotelrack] Destination query: {destination}")

            # Dismiss a warning left by a previous failed search.
            warning_ok = page.locator("#HQ_ShowBTNOk")

            if await warning_ok.is_visible():
                await warning_ok.click()

            await city_input.click()
            await city_input.fill("")
            await city_input.fill(destination)

            # Wait for Hotelrack's autocomplete results.
            suggestion_text = hotel_name or city

            suggestion = page.locator(".area-sec").filter(
                has_text=suggestion_text
            ).first

            try:
                await suggestion.wait_for(
                    state="visible",
                    timeout=12_000,
                )
            except PlaywrightTimeoutError as error:
                await city_input.fill("")

                raise InvalidDestinationError(
                    "No matching Hotelrack destination was found. "
                    "Check the hotel spelling and selected city."
                ) from error

            await suggestion.click()

            try:
                await page.wait_for_function(
                    """
                    () => {
                        const field =
                            document.querySelector("#hdnCityId");

                        return field &&
                               field.value &&
                               field.value !== "undefined" &&
                               field.value !== "null";
                    }
                    """,
                    timeout=10_000,
                )
            except PlaywrightTimeoutError as error:
                raise InvalidDestinationError(
                    "Hotelrack did not accept this hotel and city. "
                    "Select a valid hotel/city combination."
                ) from error

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

            if len(children_ages) != children:
                raise ValueError(
                    "An age is required for every child."
                )

            if children > 0:
                print(
                    f"[Hotelrack] Setting {children} child age(s)."
                )

                await page.wait_for_timeout(700)

                age_label = page.get_by_text(
                    "Children Age",
                    exact=True,
                ).first

                try:
                    await age_label.wait_for(
                        state="visible",
                        timeout=10_000,
                    )
                except PlaywrightTimeoutError as error:
                    raise RuntimeError(
                        "Hotelrack did not display its child-age fields."
                    ) from error

                container = age_label
                age_selects = []

                # Move upward until the container holding the generated
                # child-age dropdowns is found.
                for _ in range(5):
                    container = container.locator("xpath=..")
                    selects = container.locator("select")
                    candidates = []

                    for index in range(await selects.count()):
                        candidate = selects.nth(index)
                        candidate_id = (
                            await candidate.get_attribute("id") or ""
                        )

                        if candidate_id in {
                            "ddlAdult_1",
                            "selectdrop",
                            "ddlNoOfNts",
                            "ddlCurrency",
                            "ddlStar",
                            "ddlAvailable",
                            "ddlSortBy",
                            "ddlAgMarkup",
                        }:
                            continue

                        option_values = await candidate.locator(
                            "option"
                        ).evaluate_all(
                            """
                            options => options.map(
                                option => option.value
                            )
                            """
                        )

                        if "1" in option_values and "17" in option_values:
                            candidates.append(candidate)

                    if len(candidates) >= children:
                        age_selects = candidates[:children]
                        break

                if len(age_selects) != children:
                    raise RuntimeError(
                        "Hotelrack child-age dropdowns could not be identified."
                    )

                for index, age in enumerate(children_ages):
                    await age_selects[index].select_option(
                        str(age),
                        force=True,
                    )

                    await age_selects[index].dispatch_event("change")

                done_button = page.get_by_text(
                    "Done",
                    exact=True,
                ).first

                if (
                    await done_button.count() > 0
                    and await done_button.is_visible()
                ):
                    await done_button.click()

                print(
                    f"[Hotelrack] Child ages set: {children_ages}"
                )

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
                    "price_from": calculate_airwings_price(item.get("SCost")),
                    "currency": currency,
                    "available": bool(item.get("Avail")),
                }
                for item in raw_results
            ]

    async def get_room_rates(
        self,
        hotel_name: str,
    ) -> list[dict[str, Any]]:
        if (
            self.page is None
            or self.page.is_closed()
            or self.context is None
        ):
            raise RuntimeError("Hotelrack browser is unavailable.")

        async with self.search_lock:
            page = self.page

            if "SearchResult" not in page.url:
                raise RuntimeError(
                    "Hotelrack is not currently displaying hotel results."
                )

            # Find the requested hotel and its associated Select control.
            hotel_text = page.get_by_text(
                hotel_name,
                exact=True,
            ).first

            try:
                await hotel_text.wait_for(
                    state="visible",
                    timeout=10_000,
                )

                hotel_card = hotel_text.locator(
                    "xpath=ancestor::*"
                    "[.//*[normalize-space(text())='Select']][1]"
                )

                select_control = hotel_card.get_by_text(
                    "Select",
                    exact=True,
                ).first

                if await select_control.count() == 0:
                    select_control = page.get_by_text(
                        "Select",
                        exact=True,
                    ).first

            except Exception:
                select_control = page.get_by_text(
                    "Select",
                    exact=True,
                ).first

            await select_control.wait_for(
                state="visible",
                timeout=15_000,
            )

            loop = asyncio.get_running_loop()
            response_future = loop.create_future()

            def capture_room_response(response):
                if (
                    "gethotelroomratesbyid" in response.url.lower()
                    and not response_future.done()
                ):
                    response_future.set_result(response)

            self.context.on("response", capture_room_response)

            room_page = None

            try:
                print(
                    f"[Hotelrack] Opening room rates for {hotel_name}."
                )

                async with self.context.expect_page(
                    timeout=30_000
                ) as popup_info:
                    await select_control.click()

                room_page = await popup_info.value

                response = await asyncio.wait_for(
                    response_future,
                    timeout=180,
                )

                print(
                    "[Hotelrack] GetHotelRoomRatesById captured."
                )

                payload = await response.json()

                if isinstance(payload, str):
                    payload = json.loads(payload)

            finally:
                self.context.remove_listener(
                    "response",
                    capture_room_response,
                )

            raw_rates: list[dict[str, Any]] = []

            for hotel_group in payload.get("SearchResult", []):
                for result in hotel_group.get("Results", []):
                    for room_group in result.get("RRDetail", []):
                        raw_rates.extend(
                            room_group.get("RateDetail", [])
                        )

            currency = payload.get("Currency", "AED")
            cheapest: dict[tuple[str, str, bool], dict[str, Any]] = {}

            for rate in raw_rates:
                available = bool(rate.get("IsAvailable"))
                status = str(rate.get("status") or "").lower()

                if not available and status != "available":
                    continue

                raw_sell_amount = rate.get("SellAmount")

                try:
                    sell_amount = Decimal(str(raw_sell_amount))
                except (InvalidOperation, TypeError, ValueError):
                    continue

                room_name = (
                    rate.get("MasterRoomCategories")
                    or rate.get("RoomCategory")
                    or "Room"
                )

                meal_plan = (
                    rate.get("FixMealType")
                    or rate.get("MealType")
                    or "Not specified"
                )

                refundable = bool(rate.get("Refundable"))

                # Equivalent room, meal and refundability options are grouped.
                key = (
                    " ".join(str(room_name).lower().split()),
                    " ".join(str(meal_plan).lower().split()),
                    refundable,
                )

                current = cheapest.get(key)

                if (
                    current is None
                    or sell_amount < current["_sell_amount"]
                ):
                    cheapest[key] = {
                        "_sell_amount": sell_amount,
                        "room_name": room_name,
                        "meal_plan": meal_plan,
                        "refundable": refundable,
                        "available": True,
                        "status": rate.get("status") or "Available",
                        "offer": rate.get("Offer") or None,
                        "value_adds": rate.get("ValueAdds") or None,
                        "deadline": rate.get("DeadLineDate") or None,
                        "currency": currency,
                        "final_price": (
                            sell_amount
                            + settings.airwings_markup_aed
                        ),
                    }

            rooms = sorted(
                cheapest.values(),
                key=lambda room: room["_sell_amount"],
            )

            for room in rooms:
                room["final_price"] = (
                    f"{room['final_price']:.2f}"
                )
                del room["_sell_amount"]

            print(
                f"[Hotelrack] Returning {len(rooms)} "
                "deduplicated room rate(s)."
            )

            if room_page is not None and not room_page.is_closed():
                await room_page.close()

            return rooms

    async def stop(self) -> None:
        if self.context is not None:
            await self.context.close()

        if self.playwright is not None:
            await self.playwright.stop()

        self.page = None
        self.context = None
        self.playwright = None
