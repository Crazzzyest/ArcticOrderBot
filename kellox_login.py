import os
import sys
import time
from typing import List, Dict

from dotenv import load_dotenv
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, ElementClickInterceptedException, NoSuchElementException
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager


KELLOX_URL = "https://kellox.no/my-account/"

# Eksempelordre for Kellox – utvid/fjern etter behov.
ORDERS: List[Dict[str, object]] = [
    {"leverandor": "Kellox", "varenr": "00000023050", "antall": 2},
    {"leverandor": "Kellox", "varenr": "00001113192", "antall": 2},
]


def create_driver() -> webdriver.Chrome:
    options = webdriver.ChromeOptions()
    options.add_argument("--start-maximized")
    # Stabilitet i Linux-container (Sliplane/Docker)
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    if os.getenv("HEADLESS", "").strip() in {"1", "true", "True", "yes", "YES"}:
        options.add_argument("--headless=new")
    driver = webdriver.Chrome(
        service=ChromeService(ChromeDriverManager().install()),
        options=options,
    )
    driver.implicitly_wait(2)
    return driver


def load_kellox_credentials() -> dict:
    load_dotenv()
    username = os.getenv("KELLOX_USERNAME")
    password = os.getenv("KELLOX_PASSWORD")

    missing = [name for name, value in [("KELLOX_USERNAME", username), ("KELLOX_PASSWORD", password)] if not value]
    if missing:
        print(f"Mangler følgende miljøvariabler i .env: {', '.join(missing)}")
        print("Legg dem inn basert på .env.example og kjør scriptet på nytt.")
        sys.exit(1)

    return {"username": username, "password": password}


def login_kellox(driver: webdriver.Chrome, username: str, password: str) -> None:
    driver.get(KELLOX_URL)

    wait = WebDriverWait(driver, 20)

    try:
        user_input = wait.until(
            EC.presence_of_element_located((By.ID, "username")),
        )
        pass_input = wait.until(
            EC.presence_of_element_located((By.ID, "password")),
        )
    except TimeoutException:
        print("Fant ikke brukernavn/passord-felt på Kellox-siden.")
        raise

    user_input.clear()
    user_input.send_keys(username)

    pass_input.clear()
    pass_input.send_keys(password)

    # Klikk på Logg inn-knappen
    try:
        login_button = wait.until(
            EC.element_to_be_clickable(
                (
                    By.CSS_SELECTOR,
                    "button.woocommerce-form-login__submit",
                ),
            ),
        )
        login_button.click()
    except TimeoutException:
        # Fallback: send ENTER i passordfeltet
        pass_input.send_keys(Keys.ENTER)
    except ElementClickInterceptedException:
        # Typisk at cookie-banner eller lignende ligger over knappen.
        # Bruk JavaScript-click for å trigge innloggingen likevel.
        driver.execute_script("arguments[0].click();", login_button)

    # Enkel sjekk: vent på at "Min konto" eller lignende dukker opp
    try:
        wait.until(
            EC.presence_of_element_located(
                (
                    By.XPATH,
                    "//*[contains(text(), 'Min konto') or contains(text(), 'Account')]",
                ),
            ),
        )
        print("Kellox-innlogging ser vellykket ut (fant Min konto / Account).")
    except TimeoutException:
        print("Usikker på om Kellox-innlogging lyktes – fant ikke Min konto / Account.")


def navigate_to_quickorder(driver: webdriver.Chrome) -> None:
    """Klikker Min side -> Hurtigordre (quickbuy)."""
    wait = WebDriverWait(driver, 20)

    # Min side (kan allerede være aktiv, men dette er ufarlig)
    try:
        min_side_link = wait.until(
            EC.element_to_be_clickable(
                (By.XPATH, "//a[@href='https://kellox.no/my-account/' and contains(., 'Min side')]"),
            ),
        )
        min_side_link.click()
    except TimeoutException:
        # Hvis vi ikke finner lenken, er vi kanskje allerede på Min side.
        pass

    # Hurtigordre
    try:
        quick_link = wait.until(
            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    "//a[@href='https://kellox.no/my-account/maksimer-quickbuy/' and contains(., 'Hurtigordre')]",
                ),
            ),
        )
        quick_link.click()
    except TimeoutException:
        print("Fant ikke lenken til Hurtigordre på Kellox.")
        raise


def search_and_add_item_kellox(driver: webdriver.Chrome, order: Dict[str, object]) -> None:
    """Søker opp varenummer på Kellox Hurtigordre-siden og legger i handlekurv."""
    varenr = str(order.get("varenr", "")).strip()
    antall = int(order.get("antall", 0))
    leverandor = str(order.get("leverandor", ""))

    if not varenr or antall <= 0:
        print(f"Hopper over Kellox-ordre med ugyldige data: {order}")
        return

    print(f"Kellox: behandler vare '{varenr}' (leverandør: {leverandor}, antall: {antall})...")

    wait = WebDriverWait(driver, 20)

    # Søkefelt
    try:
        search_input = wait.until(
            EC.element_to_be_clickable(
                (By.NAME, "quick_buy_search"),
            ),
        )
    except TimeoutException:
        print("Fant ikke Hurtigordre-søkefeltet (quick_buy_search).")
        return

    search_input.clear()
    search_input.send_keys(varenr)

    # Søkeknapp
    try:
        search_button = wait.until(
            EC.element_to_be_clickable(
                (By.XPATH, "//input[@type='submit' and @value='Søk']"),
            ),
        )
        search_button.click()
    except TimeoutException:
        print(f"Kellox: fant ikke Søk-knappen for vare {varenr}.")
        return

    # Vent til resultatet kommer opp
    time.sleep(5)

    # QTY-felt
    try:
        qty_input = wait.until(
            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    "//input[@type='number' and contains(@class,'qty')]",
                ),
            ),
        )
    except TimeoutException:
        print(f"Kellox: fant ikke QTY-felt for vare {varenr}.")
        return

    qty_input.clear()
    qty_input.send_keys(str(antall))

    # Legg til i handlekurv
    try:
        add_to_cart_link = wait.until(
            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    "//a[contains(@class,'maksimer_qnt') and contains(@class,'add_to_cart_button')]",
                ),
            ),
        )
        add_to_cart_link.click()
    except TimeoutException:
        print(f"Kellox: fant ikke 'Legg til i handlekurv'-lenken for vare {varenr}.")
        return

    print(f"Kellox: vare {varenr} forsøkt lagt i handlekurv.")


def process_kellox_orders(driver: webdriver.Chrome, orders: List[Dict[str, object]]) -> None:
    """Kjører gjennom alle Kellox-ordre i en liste."""
    if not orders:
        print("Kellox: ingen ordre å prosessere (tom liste).")
        return

    for order in orders:
        try:
            search_and_add_item_kellox(driver, order)
        except Exception as exc:  # noqa: BLE001
            print(f"Feil under Kellox-ordre {order}: {exc}")


def run_kellox(orders: List[Dict[str, object]], *, interactive: bool = False) -> None:
    creds = load_kellox_credentials()
    driver = create_driver()

    try:
        login_kellox(driver, creds["username"], creds["password"])
        navigate_to_quickorder(driver)
        process_kellox_orders(driver, orders)
        print("Kellox: ferdig med alle ordre.")
        if interactive:
            input("Kellox: Trykk Enter i terminalen for å lukke nettleseren...")
    finally:
        driver.quit()


def main() -> None:
    if not ORDERS:
        print("Kellox ORDERS-listen er tom. Legg inn bestillinger i kellox_login.py.")
        return

    run_kellox(ORDERS, interactive=True)


if __name__ == "__main__":
    main()

