import asyncio
import json
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from playwright.async_api import (
    BrowserContext,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)

from app.settings import settings


PROJECT_DIR = Path(__file__).resolve().parents[2]
BROWSER_DATA_DIR = PROJECT_DIR / "browser-data" / "hotelrack"


def calculate_airwings_price(
    raw_price: object,
) -> str | None:
    if raw_price is None:
        return None

    try:
        base_price = Decimal(str(raw_price))
        final_price = (
            base_price
            + settings.airwings_markup_aed
        )

        return f"{final_price:.2f}"

    except (
        InvalidOperation,
        TypeError,
        ValueError,
    ):
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
        BROWSER_DATA_DIR.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.playwright = (
            await async_playwright().start()
        )

        self.context = (
            await self.playwright.chromium
            .launch_persistent_context(
                user_data_dir=str(
                    BROWSER_DATA_DIR
                ),
                headless=(
                    settings.hotelrack_headless
                ),
                viewport={
                    "width": 1440,
                    "height": 900,
                },
            )
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

        search_field = self.page.locator(
            "#txt_CitySearch"
        )

        if (
            await search_field.count() > 0
            and await search_field.is_visible()
        ):
            self.search_page_url = self.page.url

            print(
                "[Hotelrack] Existing authenticated "
                "session is ready."
            )

            return

        sign_in_button = self.page.get_by_role(
            "button",
            name="Sign in",
        )

        if (
            await sign_in_button.count() > 0
            and await sign_in_button.is_visible()
        ):
            print(
                "[Hotelrack] Attempting automatic "
                "sign-in."
            )

            await self.page.wait_for_timeout(1500)
            await sign_in_button.click()

            try:
                await self.page.locator(
                    "#txt_CitySearch"
                ).wait_for(
                    state="visible",
                    timeout=60_000,
                )

                self.search_page_url = self.page.url

                print(
                    "[Hotelrack] Automatic sign-in "
                    "succeeded."
                )

                return

            except PlaywrightTimeoutError:
                print(
                    "[Hotelrack] Automatic sign-in was "
                    "not completed. Administrator action "
                    "may be required."
                )

                return

        print(
            "[Hotelrack] Administrator login is "
            "required on the backend machine."
        )

    async def status(
        self,
    ) -> dict[str, object]:
        if (
            self.page is None
            or self.page.is_closed()
        ):
            return {
                "running": False,
                "authenticated": False,
                "message": (
                    "Hotelrack browser is not running."
                ),
            }

        search_field = self.page.locator(
            "#txt_CitySearch"
        )

        search_form_visible = (
            await search_field.count() > 0
            and await search_field.is_visible()
        )

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

    async def refresh_current_page(
        self,
    ) -> bool:
        """
        Refresh the Hotelrack page when the Airwings
        website requests a synchronized refresh.
        """
        if (
            self.page is None
            or self.page.is_closed()
        ):
            return False

        async with self.search_lock:
            print(
                "[Hotelrack] Refresh requested by "
                "Airwings."
            )

            await self.page.reload(
                wait_until="domcontentloaded",
                timeout=60_000,
            )

            search_field = self.page.locator(
                "#txt_CitySearch"
            )

            if (
                await search_field.count() > 0
                and await search_field.is_visible()
            ):
                self.search_page_url = self.page.url

            print("[Hotelrack] Page refreshed.")

            return True

    async def _find_child_age_selects(
        self,
        page: Page,
    ) -> list[Any]:
        """
        Locate Hotelrack child-age select elements.

        Hotelrack creates these dynamically after the
        number of children is changed.
        """
        excluded_ids = {
            "ddlAdult_1",
            "selectdrop",
            "ddlNoOfNts",
            "ddlCurrency",
            "ddlStar",
            "ddlAvailable",
            "ddlSortBy",
            "ddlAgMarkup",
        }

        required_values = {
            str(age)
            for age in range(1, 18)
        }

        candidates: list[
            tuple[int, int, Any]
        ] = []

        all_selects = page.locator("select")
        select_count = await all_selects.count()

        for index in range(select_count):
            candidate = all_selects.nth(index)

            try:
                candidate_id = (
                    await candidate.get_attribute("id")
                    or ""
                )

                if candidate_id in excluded_ids:
                    continue

                option_values = (
                    await candidate.locator(
                        "option"
                    ).evaluate_all(
                        """
                        options => options.map(
                            option =>
                                String(
                                    option.value
                                ).trim()
                        )
                        """
                    )
                )

                if not required_values.issubset(
                    set(option_values)
                ):
                    continue

                # Prefer visible child-age selectors.
                visible_priority = (
                    0
                    if await candidate.is_visible()
                    else 1
                )

                candidates.append(
                    (
                        visible_priority,
                        index,
                        candidate,
                    )
                )

            except Exception:
                # Ignore unrelated or detached selects.
                continue

        candidates.sort(
            key=lambda item: (
                item[0],
                item[1],
            )
        )

        return [
            item[2]
            for item in candidates
        ]

    async def _set_guest_details(
        self,
        page: Page,
        adults: int,
        children: int,
        children_ages: list[int],
    ) -> None:
        if len(children_ages) != children:
            raise ValueError(
                "An age is required for every child."
            )

        # Open Hotelrack's guest controls.
        guest_control = page.locator(
            "#js-addGuestRoom"
        )

        if await guest_control.count() > 0:
            try:
                if await guest_control.is_visible():
                    await guest_control.click(
                        force=True
                    )

                    await page.wait_for_timeout(
                        300
                    )
            except Exception:
                # Native select elements can still be
                # updated if the custom control fails.
                pass

        adult_select = page.locator(
            "#ddlAdult_1"
        )

        children_select = page.locator(
            "#selectdrop"
        )

        await adult_select.wait_for(
            state="attached",
            timeout=10_000,
        )

        await children_select.wait_for(
            state="attached",
            timeout=10_000,
        )

        try:
            await adult_select.select_option(
                str(adults),
                force=True,
            )

            await adult_select.dispatch_event(
                "input"
            )

            await adult_select.dispatch_event(
                "change"
            )

        except Exception as error:
            raise ValueError(
                f"Hotelrack does not support "
                f"{adults} adult(s) for this room."
            ) from error

        try:
            await children_select.select_option(
                str(children),
                force=True,
            )

            await children_select.dispatch_event(
                "input"
            )

            await children_select.dispatch_event(
                "change"
            )

        except Exception as error:
            raise ValueError(
                f"Hotelrack does not support "
                f"{children} child(ren) for this room."
            ) from error

        if children > 0:
            print(
                f"[Hotelrack] Waiting for {children} "
                "child-age field(s)."
            )

            age_selects: list[Any] = []

            # Wait up to ten seconds for Hotelrack to
            # generate every child-age dropdown.
            for _ in range(40):
                age_selects = (
                    await self
                    ._find_child_age_selects(page)
                )

                if len(age_selects) >= children:
                    break

                await page.wait_for_timeout(250)

            if len(age_selects) < children:
                raise RuntimeError(
                    "Hotelrack did not display all "
                    "required child-age fields."
                )

            for index, age in enumerate(
                children_ages
            ):
                if age < 1 or age > 17:
                    raise ValueError(
                        "Child ages must be between "
                        "1 and 17."
                    )

                # Find the current elements again because
                # Angular may recreate the dropdowns
                # after an age is selected.
                current_age_selects = (
                    await self
                    ._find_child_age_selects(page)
                )

                if (
                    len(current_age_selects)
                    <= index
                ):
                    raise RuntimeError(
                        "A Hotelrack child-age field "
                        "disappeared while setting ages."
                    )

                age_select = (
                    current_age_selects[index]
                )

                await age_select.select_option(
                    str(age),
                    force=True,
                )

                await age_select.dispatch_event(
                    "input"
                )

                await age_select.dispatch_event(
                    "change"
                )

                print(
                    f"[Hotelrack] Child "
                    f"{index + 1} age set to {age}."
                )

            # Hotelrack shows a Done button after child
            # ages have been selected.
            done_buttons = page.get_by_text(
                "Done",
                exact=True,
            )

            done_clicked = False

            for index in range(
                await done_buttons.count()
            ):
                done_button = (
                    done_buttons.nth(index)
                )

                if await done_button.is_visible():
                    await done_button.click(
                        force=True
                    )

                    done_clicked = True
                    break

            if not done_clicked:
                # Close the guest panel if Hotelrack did
                # not render a usable Done button.
                await page.keyboard.press("Escape")

        else:
            # Close the guest selector when there are no
            # child-age fields and therefore no Done
            # button.
            await page.keyboard.press("Escape")

        await page.wait_for_timeout(500)

        print(
            f"[Hotelrack] Guests set: "
            f"{adults} adult(s), "
            f"{children} child(ren), "
            f"ages={children_ages}."
        )

    async def _click_hotelrack_search(
        self,
        page: Page,
    ) -> dict[str, Any]:
        """
        Locate and click Hotelrack's visible main Search
        control using the actual clickable element.
        """
        click_result = await page.evaluate(
            """
            () => {
                const elements = Array.from(
                    document.querySelectorAll(
                        [
                            "button",
                            "a",
                            "[role='button']",
                            "input[type='submit']",
                            "input[type='button']"
                        ].join(",")
                    )
                );

                const searchButton = elements.find(
                    element => {
                        const label = (
                            element.innerText ||
                            element.textContent ||
                            element.value ||
                            ""
                        )
                        .trim()
                        .toLowerCase();

                        const rectangle =
                            element
                            .getBoundingClientRect();

                        const visible =
                            rectangle.width > 0 &&
                            rectangle.height > 0 &&
                            window.getComputedStyle(
                                element
                            ).visibility !==
                                "hidden" &&
                            window.getComputedStyle(
                                element
                            ).display !==
                                "none";

                        return (
                            label === "search" &&
                            visible &&
                            rectangle.left > 400
                        );
                    }
                );

                if (!searchButton) {
                    return {
                        clicked: false
                    };
                }

                searchButton.scrollIntoView({
                    block: "center",
                    inline: "center"
                });

                searchButton.click();

                return {
                    clicked: true,
                    tag: searchButton.tagName,
                    id: searchButton.id || null,
                    className:
                        typeof searchButton.className
                            === "string"
                            ? searchButton.className
                            : null
                };
            }
            """
        )

        if not click_result.get("clicked"):
            raise RuntimeError(
                "Could not find Hotelrack's visible "
                "Search button."
            )

        return click_result

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
        if (
            self.page is None
            or self.page.is_closed()
        ):
            raise RuntimeError(
                "Hotelrack browser is not running."
            )

        async with self.search_lock:
            page = self.page

            city_input = page.locator(
                "#txt_CitySearch"
            )

            # Return from a previous results page to the
            # authenticated Hotelrack search form.
            if not await city_input.is_visible():
                if self.search_page_url is None:
                    raise RuntimeError(
                        "The authenticated Hotelrack "
                        "search URL is unavailable."
                    )

                print(
                    "[Hotelrack] Returning to the "
                    "search form."
                )

                await page.goto(
                    self.search_page_url,
                    wait_until="domcontentloaded",
                    timeout=60_000,
                )

                city_input = page.locator(
                    "#txt_CitySearch"
                )

                await city_input.wait_for(
                    state="visible",
                    timeout=30_000,
                )

            # Remember the current dynamic authenticated
            # Hotelrack search URL.
            self.search_page_url = page.url

            city = city.strip()

            cleaned_hotel_name = (
                hotel_name.strip()
                if hotel_name
                else None
            )

            destination = (
                f"{cleaned_hotel_name}, {city}"
                if cleaned_hotel_name
                else city
            )

            print(
                f"[Hotelrack] Destination query: "
                f"{destination}"
            )

            # Dismiss a warning from a previous failed
            # search if it is still displayed.
            warning_ok = page.locator(
                "#HQ_ShowBTNOk"
            )

            if (
                await warning_ok.count() > 0
                and await warning_ok.is_visible()
            ):
                await warning_ok.click(
                    force=True
                )

            await city_input.click()
            await city_input.fill("")
            await city_input.fill(destination)

            suggestion_text = (
                cleaned_hotel_name or city
            )

            suggestion = page.locator(
                ".area-sec"
            ).filter(
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
                    "No matching Hotelrack destination "
                    "was found. Check the hotel spelling "
                    "and selected city."
                ) from error

            await suggestion.click()

            try:
                await page.wait_for_function(
                    """
                    () => {
                        const field =
                            document.querySelector(
                                "#hdnCityId"
                            );

                        return (
                            field &&
                            field.value &&
                            field.value !==
                                "undefined" &&
                            field.value !== "null"
                        );
                    }
                    """,
                    timeout=10_000,
                )

            except PlaywrightTimeoutError as error:
                raise InvalidDestinationError(
                    "Hotelrack did not accept this hotel "
                    "and city. Select a valid hotel and "
                    "city combination."
                ) from error

            check_in_text = (
                check_in.strftime("%d %b %Y")
            )

            check_out_text = (
                check_out.strftime("%d %b %Y")
            )

            check_in_field = page.locator(
                "#txtChkInDate"
            )

            check_out_field = page.locator(
                "#txtChkOutDate"
            )

            await check_in_field.fill(
                check_in_text
            )

            await check_in_field.dispatch_event(
                "input"
            )

            await check_in_field.dispatch_event(
                "change"
            )

            await check_out_field.fill(
                check_out_text
            )

            await check_out_field.dispatch_event(
                "input"
            )

            await check_out_field.dispatch_event(
                "change"
            )

            # Close Hotelrack's date picker before
            # opening its guest controls.
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(300)

            await self._set_guest_details(
                page=page,
                adults=adults,
                children=children,
                children_ages=children_ages,
            )

            selected_city_id = (
                await page.locator(
                    "#hdnCityId"
                ).input_value()
            )

            if selected_city_id in (
                "",
                "undefined",
                "null",
            ):
                raise InvalidDestinationError(
                    "Hotelrack did not register the "
                    "selected destination."
                )

            if "SearchResult" in page.url:
                raise RuntimeError(
                    "Hotelrack navigated before its "
                    "Search button was clicked."
                )

            if self.context is None:
                raise RuntimeError(
                    "Hotelrack browser context is "
                    "unavailable."
                )

            loop = asyncio.get_running_loop()
            response_future = (
                loop.create_future()
            )

            def capture_search_response(
                response: Any,
            ) -> None:
                if (
                    "getsearchresult"
                    in response.url.lower()
                    and not response_future.done()
                ):
                    response_future.set_result(
                        response
                    )

            self.context.on(
                "response",
                capture_search_response,
            )

            try:
                await page.keyboard.press("Escape")
                await page.wait_for_timeout(250)

                click_result = (
                    await self
                    ._click_hotelrack_search(page)
                )

                print(
                    "[Hotelrack] Search control "
                    f"clicked: {click_result}"
                )

                print(
                    "[Hotelrack] Waiting for "
                    "GetSearchResult..."
                )

                response = await asyncio.wait_for(
                    response_future,
                    timeout=120,
                )

                print(
                    "[Hotelrack] Captured response: "
                    f"{response.url}"
                )

            finally:
                self.context.remove_listener(
                    "response",
                    capture_search_response,
                )

            payload = await response.json()

            # Hotelrack sometimes returns JSON encoded
            # inside another JSON string.
            if isinstance(payload, str):
                payload = json.loads(payload)

            raw_results = payload.get(
                "SearchResults",
                [],
            )

            currency = payload.get(
                "Currency",
                "AED",
            )

            print(
                f"[Hotelrack] Received "
                f"{len(raw_results)} hotel result(s)."
            )

            return [
                {
                    "hotel_id": item.get("HId"),
                    "hotel_name": item.get(
                        "HName"
                    ),
                    "address": item.get(
                        "Address"
                    ),
                    "location": item.get(
                        "Loc"
                    ),
                    "stars": item.get("Star"),
                    "image": item.get("Img"),
                    "price_from": (
                        calculate_airwings_price(
                            item.get("SCost")
                        )
                    ),
                    "currency": currency,
                    "available": bool(
                        item.get("Avail")
                    ),
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
            raise RuntimeError(
                "Hotelrack browser is unavailable."
            )

        async with self.search_lock:
            page = self.page

            if "SearchResult" not in page.url:
                raise RuntimeError(
                    "Hotelrack is not currently "
                    "displaying hotel results."
                )

            hotel_text = page.get_by_text(
                hotel_name,
                exact=True,
            ).first

            try:
                await hotel_text.wait_for(
                    state="visible",
                    timeout=10_000,
                )

                hotel_card = (
                    hotel_text.locator(
                        "xpath=ancestor::*"
                        "[.//*[normalize-space(text())"
                        "='Select']][1]"
                    )
                )

                select_control = (
                    hotel_card.get_by_text(
                        "Select",
                        exact=True,
                    ).first
                )

                if (
                    await select_control.count()
                    == 0
                ):
                    select_control = (
                        page.get_by_text(
                            "Select",
                            exact=True,
                        ).first
                    )

            except Exception:
                select_control = (
                    page.get_by_text(
                        "Select",
                        exact=True,
                    ).first
                )

            await select_control.wait_for(
                state="visible",
                timeout=15_000,
            )

            loop = asyncio.get_running_loop()

            response_future = (
                loop.create_future()
            )

            def capture_room_response(
                response: Any,
            ) -> None:
                if (
                    "gethotelroomratesbyid"
                    in response.url.lower()
                    and not response_future.done()
                ):
                    response_future.set_result(
                        response
                    )

            self.context.on(
                "response",
                capture_room_response,
            )

            room_page: Page | None = None

            try:
                print(
                    "[Hotelrack] Opening room rates "
                    f"for {hotel_name}."
                )

                async with (
                    self.context.expect_page(
                        timeout=30_000
                    ) as popup_info
                ):
                    await select_control.click()

                room_page = await popup_info.value

                response = await asyncio.wait_for(
                    response_future,
                    timeout=180,
                )

                print(
                    "[Hotelrack] "
                    "GetHotelRoomRatesById captured."
                )

                payload = await response.json()

                if isinstance(payload, str):
                    payload = json.loads(
                        payload
                    )

            finally:
                self.context.remove_listener(
                    "response",
                    capture_room_response,
                )

            raw_rates: list[
                dict[str, Any]
            ] = []

            for hotel_group in payload.get(
                "SearchResult",
                [],
            ):
                for result in hotel_group.get(
                    "Results",
                    [],
                ):
                    for room_group in result.get(
                        "RRDetail",
                        [],
                    ):
                        raw_rates.extend(
                            room_group.get(
                                "RateDetail",
                                [],
                            )
                        )

            currency = payload.get(
                "Currency",
                "AED",
            )

            cheapest: dict[
                tuple[str, str, bool],
                dict[str, Any],
            ] = {}

            for rate in raw_rates:
                available = bool(
                    rate.get("IsAvailable")
                )

                status = str(
                    rate.get("status") or ""
                ).lower()

                if (
                    not available
                    and status != "available"
                ):
                    continue

                raw_sell_amount = rate.get(
                    "SellAmount"
                )

                try:
                    sell_amount = Decimal(
                        str(raw_sell_amount)
                    )

                except (
                    InvalidOperation,
                    TypeError,
                    ValueError,
                ):
                    continue

                room_name = (
                    rate.get(
                        "MasterRoomCategories"
                    )
                    or rate.get("RoomCategory")
                    or "Room"
                )

                meal_plan = (
                    rate.get("FixMealType")
                    or rate.get("MealType")
                    or "Not specified"
                )

                refundable = bool(
                    rate.get("Refundable")
                )

                key = (
                    " ".join(
                        str(room_name)
                        .lower()
                        .split()
                    ),
                    " ".join(
                        str(meal_plan)
                        .lower()
                        .split()
                    ),
                    refundable,
                )

                current = cheapest.get(key)

                if (
                    current is None
                    or sell_amount
                    < current["_sell_amount"]
                ):
                    cheapest[key] = {
                        "_sell_amount": (
                            sell_amount
                        ),
                        "room_name": room_name,
                        "meal_plan": meal_plan,
                        "refundable": refundable,
                        "available": True,
                        "status": (
                            rate.get("status")
                            or "Available"
                        ),
                        "offer": (
                            rate.get("Offer")
                            or None
                        ),
                        "value_adds": (
                            rate.get("ValueAdds")
                            or None
                        ),
                        "deadline": (
                            rate.get(
                                "DeadLineDate"
                            )
                            or None
                        ),
                        "currency": currency,
                        "final_price": (
                            sell_amount
                            + settings
                            .airwings_markup_aed
                        ),
                    }

            rooms = sorted(
                cheapest.values(),
                key=lambda room: (
                    room["_sell_amount"]
                ),
            )

            for room in rooms:
                room["final_price"] = (
                    f"{room['final_price']:.2f}"
                )

                del room["_sell_amount"]

            print(
                f"[Hotelrack] Returning "
                f"{len(rooms)} deduplicated "
                "room rate(s)."
            )

            if (
                room_page is not None
                and not room_page.is_closed()
            ):
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
