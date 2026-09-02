from pathlib import Path
from playwright.sync_api import sync_playwright

BROWSER_DATA_DIR = Path("browser-data/hotelrack")


def main() -> None:
    login_url = input("Enter the official Hotelrack login URL: ").strip()

    if not login_url.startswith(("https://", "http://")):
        print("Invalid URL. It must start with https:// or http://")
        return

    BROWSER_DATA_DIR.mkdir(parents=True, exist_ok=True)

    print("\nOpening the secured Hotelrack browser...")
    print("Log in using the authorized administrator account.")
    print("Do not close the browser after logging in.\n")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch_persistent_context(
            user_data_dir=str(BROWSER_DATA_DIR),
            headless=False,
            viewport={"width": 1440, "height": 900},
        )

        page = browser.pages[0] if browser.pages else browser.new_page()
        page.goto(login_url, wait_until="domcontentloaded")

        input(
            "After Hotelrack has fully logged in and you can see its dashboard, "
            "return here and press Enter..."
        )

        print(f"Session saved. Current page: {page.url}")
        browser.close()

    print("\nHotelrack browser session saved successfully.")
    print("Website users will not need the Hotelrack credentials.")


if __name__ == "__main__":
    main()
