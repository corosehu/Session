from playwright.sync_api import sync_playwright

def verify_ui():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            # Navigate to the app (Frontend served by Backend)
            page.goto("http://127.0.0.1:8000")

            # Wait for Alpine to initialize and rendering to complete
            page.wait_for_selector("text=NEXUS SESSION", state="visible")

            # Verify Login Form
            page.wait_for_selector("text=AUTHENTICATION", state="visible")
            page.wait_for_selector("input[placeholder='Instagram Username']", state="visible")

            # Take a screenshot of the Login Page
            page.screenshot(path="verification/merged_login.png")
            print("Login page verified and screenshot taken.")

        except Exception as e:
            print(f"Verification failed: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    verify_ui()
