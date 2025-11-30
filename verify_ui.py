from playwright.sync_api import sync_playwright

def verify_session_manager():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Navigate to the locally running app
        page.goto("http://localhost:8000")

        # Wait for the main UI to load
        page.wait_for_selector("text=Session Forger")

        # Verify Tabs exist
        page.wait_for_selector("text=NEW SESSION")
        page.wait_for_selector("text=SAVED FILES")

        # Take a screenshot of the initial state
        page.screenshot(path="verification_ui_initial.png")
        print("Initial UI screenshot taken.")

        # Fill in dummy credentials to trigger error (simulate login)
        page.fill("input[placeholder='username']", "testuser")
        page.fill("input[placeholder='••••••••']", "password")
        page.click("button:has-text('Initialize Session')")

        # Wait for the Log/Error box to appear (simulating the 'Live Log' feature)
        # Since backend is not actually verifying credentials (or will fail), we expect a log entry
        # But this requires the backend to be running.
        # We will wait a bit.
        page.wait_for_timeout(3000)

        # Take a screenshot of the error state / terminal log
        page.screenshot(path="verification_ui_error.png")
        print("Error UI screenshot taken.")

        browser.close()

if __name__ == "__main__":
    verify_session_manager()
