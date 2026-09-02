import json
from pathlib import Path

from playwright.sync_api import sync_playwright

from app.settings import settings

PROJECT_DIR = Path(__file__).resolve().parents[1]
BROWSER_DATA_DIR = PROJECT_DIR / "browser-data" / "hotelrack"


def main() -> None:
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(BROWSER_DATA_DIR),
            headless=False,
            viewport={"width": 1440, "height": 900},
        )

        page = context.pages[0] if context.pages else context.new_page()
        page.goto(
            settings.hotelrack_start_url,
            wait_until="domcontentloaded",
            timeout=60_000,
        )

        print("\nLog in as the administrator.")
        print("Then open Hotelrack's hotel-search form.")

        input(
            "\nOnce the complete search form is visible, "
            "return here and press Enter..."
        )

        controls = page.locator(
            "input:not([type='password']), select, textarea, button"
        ).evaluate_all(
            """
            elements => elements.map((element, index) => ({
                index: index,
                tag: element.tagName.toLowerCase(),
                type: element.type || null,
                name: element.name || null,
                id: element.id || null,
                placeholder: element.placeholder || null,
                ariaLabel: element.getAttribute("aria-label"),
                value: element.value || null,
                text: (element.innerText || "").trim().slice(0, 100),
                readOnly: Boolean(element.readOnly),
                disabled: Boolean(element.disabled)
            }))
            """
        )

        print("\n--- HOTELRACK FORM CONTROLS ---")
        print(json.dumps(controls, indent=2))

        input("\nPress Enter to close the browser...")
        context.close()


if __name__ == "__main__":
    main()
