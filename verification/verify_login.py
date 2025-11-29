from playwright.sync_api import sync_playwright

def verify_ui():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            # Navigate to the app (Frontend served by Backend)
            page.goto("http://127.0.0.1:8000")

            # 1. Verify Title and Header
            page.wait_for_selector("text=NEXUS SESSION")

            # 2. Verify Login Form
            page.wait_for_selector("text=AUTHENTICATION")
            page.wait_for_selector("input[placeholder='Instagram Username']")

            # Take a screenshot of the Login Page
            page.screenshot(path="verification/login_page.png")
            print("Login page verified and screenshot taken.")

            # Note: We cannot easily verify the logged-in state without valid credentials,
            # but we can verify the UI structure and that the React app loads correctly.

        except Exception as e:
            print(f"Verification failed: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    verify_ui()
