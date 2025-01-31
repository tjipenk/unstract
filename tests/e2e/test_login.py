from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


class TestLogin:
    def setup_method(self, method):
        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--no-sandbox")
        self.driver = webdriver.Chrome(options=options)

    def teardown_method(self, method):
        self.driver.quit()

    def _check_page_load(self):
        try:
            self.driver.get("http://frontend.unstract.localhost")
        except Exception as e:
            print(f"Page load exception: {e}")
            return False
        else:
            return True

    def test_login(self):
        # Wait for the page to load
        WebDriverWait(self.driver, timeout=30, poll_frequency=2).until(
            lambda _: self._check_page_load(),
            "Page load failed",
        )

        # Set the window size
        self.driver.set_window_size(960, 615)

        # Explicit wait for the button to be clickable
        WebDriverWait(self.driver, timeout=10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "button")),
            "Button not clickable.",
        ).click()

        # Explicit wait for the username field to be visible
        username_field = WebDriverWait(self.driver, timeout=10).until(
            EC.visibility_of_element_located((By.ID, "username")),
            "Username field not visible.",
        )
        username_field.click()
        username_field.send_keys("unstract")

        # Explicit wait for the password field to be visible
        password_field = WebDriverWait(self.driver, timeout=10).until(
            EC.visibility_of_element_located((By.ID, "password")),
            "Password field not visible.",
        )
        password_field.send_keys("unstract")

        # Explicit wait for the login button to be clickable
        WebDriverWait(self.driver, timeout=10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "input:nth-child(11)")),
            "Login button not clickable.",
        ).click()

        # Wait for the URL to change to indicate successful login
        WebDriverWait(self.driver, timeout=10).until(
            lambda _: self.driver.current_url.endswith("/mock_org/onboard"),
            "Login failed or URL did not change.",
        )

        # Close the browser
        self.driver.close()
