from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.service import Service
import time

# 👉 CHANGE THIS if your path is different
GECKO_PATH = r"C:\Users\megha\Downloads\geckodriver-v0.34.0-win64\geckodriver.exe"

# Setup Firefox driver
service = Service(GECKO_PATH)
driver = webdriver.Firefox(service=service)

def test_learnify():

    # Open your Flask app
    driver.get("http://localhost:5000")
    time.sleep(2)

    # ==========================
    # TEST 1: Go to Register
    # ==========================
    try:
        driver.find_element(By.LINK_TEXT, "Register").click()
        time.sleep(2)

        driver.find_element(By.NAME, "name").send_keys("TestUser")
        driver.find_element(By.NAME, "email").send_keys("testuser123@gmail.com")
        driver.find_element(By.NAME, "password").send_keys("TestUser@123")

        driver.find_element(By.TAG_NAME, "button").click()
        time.sleep(2)

        print("✅ Registration Test Passed")

    except Exception as e:
        print("❌ Registration Test Failed:", e)

    # ==========================
    # TEST 2: Login
    # ==========================
    try:
        driver.get("http://localhost:5000/login")
        time.sleep(2)

        driver.find_element(By.NAME, "email").send_keys("testuser123@gmail.com")
        driver.find_element(By.NAME, "password").send_keys("TestUser@123")

        driver.find_element(By.TAG_NAME, "button").click()
        time.sleep(3)

        assert "dashboard" in driver.current_url.lower()

        print("✅ Login Test Passed")

    except Exception as e:
        print("❌ Login Test Failed:", e)

    # ==========================
    # TEST 3: Add Topic
    # ==========================
    try:
        driver.get("http://localhost:5000/add-topic")
        time.sleep(2)

        driver.find_element(By.NAME, "title").send_keys("Automation Testing Topic")
        driver.find_element(By.TAG_NAME, "button").click()
        time.sleep(2)

        print("✅ Add Topic Test Passed")

    except Exception as e:
        print("❌ Add Topic Test Failed:", e)

    driver.quit()


# Run directly
if __name__ == "__main__":
    test_learnify()