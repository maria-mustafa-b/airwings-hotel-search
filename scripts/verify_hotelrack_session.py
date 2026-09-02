from playwright.sync_api import sync_playwright

from app.providers.hotelrack_browser import HotelrackBrowserProvider


def main() -> None:
    print("Opening the saved Hotelrack backend session...")

    with sync_playwright() as playwright:
        provider = HotelrackBrowserProvider(playwright)
        provider.open()

        try:
            result = provider.verify_session()

            print("\nBrowser opened successfully.")
            print(f"Page title: {result['title']}")
            print(f"Current URL: {result['url']}")
            print(
                "\nCheck the browser window. If the Hotelrack dashboard or search "
                "page is visible, the saved session works."
            )
            print(
                "If the login page is visible, rerun "
                "scripts/setup_hotelrack_session.py as the administrator."
            )

            input("\nPress Enter to close the browser...")
        finally:
            provider.close()


if __name__ == "__main__":
    main()
