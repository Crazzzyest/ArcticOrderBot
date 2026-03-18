import os
import sys
import time
from typing import Dict, List

from dotenv import load_dotenv
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, ElementClickInterceptedException
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager


KTM_URL = "https://shop.ktmdealer.net/"

# Legg inn KTM-deler her (leverandor, varenr/delenummer, antall).
ORDERS: List[Dict[str, object]] = [
    {"leverandor": "KTM", "varenr": "00050000068", "antall": 2},
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


def load_ktm_credentials() -> Dict[str, str]:
    load_dotenv()
    username = os.getenv("KTM_USERNAME")
    password = os.getenv("KTM_PASSWORD")

    missing = [name for name, value in [("KTM_USERNAME", username), ("KTM_PASSWORD", password)] if not value]
    if missing:
        print(f"Mangler følgende miljøvariabler i .env: {', '.join(missing)}")
        print("Legg dem inn basert på .env.example og kjør scriptet på nytt.")
        sys.exit(1)

    return {"username": username, "password": password}


def login_ktm(driver: webdriver.Chrome, username: str, password: str) -> None:
    """Logger inn på KTM Dealer via Microsoft-påloggingssiden."""
    driver.get(KTM_URL)

    wait = WebDriverWait(driver, 30)

    # 1) E-post / brukernavn
    try:
        email_input = wait.until(
            EC.element_to_be_clickable((By.ID, "i0116")),
        )
    except TimeoutException:
        print("Fant ikke e-postfeltet (i0116) på Microsoft-innloggingssiden.")
        raise

    email_input.clear()
    email_input.send_keys(username)

    # Neste-knapp (samme id brukes ofte i flere steg)
    try:
        next_button = wait.until(
            EC.element_to_be_clickable((By.ID, "idSIButton9")),
        )
        try:
            next_button.click()
        except ElementClickInterceptedException:
            driver.execute_script("arguments[0].click();", next_button)
    except TimeoutException:
        # Fallback: ENTER i e-postfeltet
        email_input.send_keys(Keys.ENTER)

    # 2) Passord
    try:
        password_input = wait.until(
            EC.element_to_be_clickable((By.ID, "i0118")),
        )
    except TimeoutException:
        print("Fant ikke passordfeltet (i0118) på Microsoft-innloggingen.")
        raise

    password_input.clear()
    password_input.send_keys(password)

    try:
        sign_in_button = wait.until(
            EC.element_to_be_clickable((By.ID, "idSIButton9")),
        )
        try:
            sign_in_button.click()
        except ElementClickInterceptedException:
            driver.execute_script("arguments[0].click();", sign_in_button)
    except TimeoutException:
        # Fallback: ENTER i passordfeltet
        password_input.send_keys(Keys.ENTER)

    # 3) Eventuell "Stay signed in?"-dialog – klikk "No" (idBtn_Back) hvis den dukker opp
    try:
        no_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.ID, "idBtn_Back")),
        )
        try:
            no_button.click()
        except ElementClickInterceptedException:
            driver.execute_script("arguments[0].click();", no_button)
    except TimeoutException:
        # Hvis dialogen ikke dukker opp, er det greit.
        pass


def search_and_add_item_ktm(driver: webdriver.Chrome, order: Dict[str, object]) -> None:
    """Søker etter delenummer på KTM shop og legger i handlekurv."""
    varenr = str(order.get("varenr", "")).strip()
    antall = int(order.get("antall", 0))
    leverandor = str(order.get("leverandor", ""))

    if not varenr or antall <= 0:
        print(f"Hopper over KTM-ordre med ugyldige data: {order}")
        return

    print(f"KTM: behandler vare '{varenr}' (leverandør: {leverandor}, antall: {antall})...")

    wait = WebDriverWait(driver, 20)

    # Søkefelt
    try:
        search_input = wait.until(
            EC.element_to_be_clickable((By.ID, "js-site-search-input")),
        )
    except TimeoutException:
        print("KTM: fant ikke søkefeltet (js-site-search-input).")
        return

    search_input.clear()
    search_input.send_keys(varenr)

    # Søkeknapp (kan være disabled til det er nok tegn; bruk JS-click om nødvendig)
    try:
        search_btn = wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "button.js_search_button")),
        )
        time.sleep(0.5)
        try:
            search_btn.click()
        except Exception:
            driver.execute_script("arguments[0].click();", search_btn)
    except TimeoutException:
        print(f"KTM: fant ikke søkeknappen for vare {varenr}.")
        return

    # Vent på at resultatsiden / antall-felt er lastet
    time.sleep(3)

    # Antall-felt
    try:
        qty_input = wait.until(
            EC.element_to_be_clickable(
                (By.CSS_SELECTOR, "input[name='qty'].form-control"),
            ),
        )
    except TimeoutException:
        print(f"KTM: fant ikke antall-felt (qty) for vare {varenr}.")
        return

    qty_input.clear()
    qty_input.send_keys(str(antall))

    # Legg til i handlekurv
    try:
        add_btn = wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "button.js-addTo-btn")),
        )
        try:
            add_btn.click()
        except ElementClickInterceptedException:
            driver.execute_script("arguments[0].click();", add_btn)
    except TimeoutException:
        print(f"KTM: fant ikke 'Legg til i handlekurv'-knappen for vare {varenr}.")
        return

    print(f"KTM: vare {varenr} forsøkt lagt i handlekurv.")


def process_ktm_orders(driver: webdriver.Chrome) -> None:
    """Kjører gjennom alle KTM-ordre i ORDERS-listen."""
    if not ORDERS:
        print("KTM ORDERS-listen er tom. Legg inn bestillinger i ktm_login.py.")
        return

    for order in ORDERS:
        try:
            search_and_add_item_ktm(driver, order)
        except Exception as exc:  # noqa: BLE001
            print(f"Feil under KTM-ordre {order}: {exc}")


def run_ktm(orders: List[Dict[str, object]], *, interactive: bool = False) -> None:
    creds = load_ktm_credentials()
    driver = create_driver()

    try:
        login_ktm(driver, creds["username"], creds["password"])
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.ID, "js-site-search-input")),
        )
        if not orders:
            print("KTM: ingen ordre å prosessere (tom liste).")
            return
        for order in orders:
            try:
                search_and_add_item_ktm(driver, order)
            except Exception as exc:  # noqa: BLE001
                print(f"Feil under KTM-ordre {order}: {exc}")
        print("KTM: ferdig med alle ordre.")
        if interactive:
            input("KTM: Trykk Enter i terminalen for å lukke nettleseren...")
    finally:
        driver.quit()


def main() -> None:
    if not ORDERS:
        print("KTM ORDERS-listen er tom. Legg inn bestillinger i ktm_login.py.")
        return

    run_ktm(ORDERS, interactive=True)


if __name__ == "__main__":
    main()

