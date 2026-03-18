import os
import sys
import time
from typing import List, Dict

from dotenv import load_dotenv
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager


BASE_URL = "https://intl.polarisportal.com/mainmenu.asp"

# Strukturen på denne listen kan du endre etter behov.
ORDERS: List[Dict[str, object]] = [
    {"leverandor": "Polaris", "varenr": "3130020", "antall": 2}, 
    {"leverandor": "Polaris", "varenr": "5415230", "antall": 1},
    {"leverandor": "Polaris", "varenr": "7556553", "antall": 3},
]


def create_driver() -> webdriver.Chrome:
    """Initialiserer Chrome WebDriver med fornuftige standarder."""
    options = webdriver.ChromeOptions()
    options.add_argument("--start-maximized")
    if os.getenv("HEADLESS", "").strip() in {"1", "true", "True", "yes", "YES"}:
        options.add_argument("--headless=new")

    driver = webdriver.Chrome(
        service=ChromeService(ChromeDriverManager().install()),
        options=options,
    )
    driver.implicitly_wait(2)
    return driver


def load_credentials() -> Dict[str, str]:
    """Leser innloggingsdata fra .env eller miljøvariabler."""
    load_dotenv()
    username = os.getenv("POLARIS_USERNAME")
    password = os.getenv("POLARIS_PASSWORD")
    user_id = os.getenv("POLARIS_USER_ID")

    missing = [name for name, value in [("POLARIS_USERNAME", username), ("POLARIS_PASSWORD", password), ("POLARIS_USER_ID", user_id)] if not value]
    if missing:
        print(f"Mangler følgende miljøvariabler i .env: {', '.join(missing)}")
        print("Fyll inn verdiene i .env (basert på .env.example) og kjør scriptet på nytt.")
        sys.exit(1)

    return {"username": username, "password": password, "user_id": user_id}


def login(driver: webdriver.Chrome, username: str, password: str, user_id: str) -> None:
    """Logger inn på Polaris-portalen og håndterer eventuell brukerID-dialog."""
    driver.get(BASE_URL)

    wait = WebDriverWait(driver, 20)

    # Prøv flere strategier for å finne brukernavn/passord-feltene.
    def find_username_and_password():
        # 1) Vanlige ID/name-verdier (enkelt å tilpasse om du vet dem)
        common_user_ids = ["username", "userName", "UserName", "txtUser", "txtUsername", "Login1_UserName"]
        common_pass_ids = ["password", "Password", "txtPass", "txtPassword", "Login1_Password"]

        for uid in common_user_ids:
            try:
                el = driver.find_element(By.ID, uid)
                if el.is_displayed():
                    username_el = el
                    break
            except NoSuchElementException:
                continue
        else:
            username_el = None

        for pid in common_pass_ids:
            try:
                el = driver.find_element(By.ID, pid)
                if el.is_displayed():
                    password_el = el
                    break
            except NoSuchElementException:
                continue
        else:
            password_el = None

        if username_el and password_el:
            return username_el, password_el

        # 2) Litt bredere XPath-søk som tidligere
        try:
            username_el = wait.until(
                EC.presence_of_element_located(
                    (
                        By.XPATH,
                        "//input[@type='text' and (contains(translate(@name,'USER','user'),'user') or contains(translate(@id,'USER','user'),'user'))]",
                    )
                )
            )
        except TimeoutException:
            username_el = None

        try:
            password_el = wait.until(
                EC.presence_of_element_located(
                    (
                        By.XPATH,
                        "//input[@type='password' or contains(translate(@name,'PASS','pass'),'pass') or contains(translate(@id,'PASS','pass'),'pass')]",
                    )
                )
            )
        except TimeoutException:
            password_el = None

        if username_el and password_el and username_el.is_displayed() and password_el.is_displayed():
            return username_el, password_el

        # 3) Fallback: første synlige tekstfelt + første synlige passordfelt på siden
        try:
            all_text_inputs = driver.find_elements(By.XPATH, "//input[@type='text' or @type='email']")
            username_el = next(el for el in all_text_inputs if el.is_displayed())
        except StopIteration:
            username_el = None

        try:
            all_pass_inputs = driver.find_elements(By.XPATH, "//input[@type='password']")
            password_el = next(el for el in all_pass_inputs if el.is_displayed())
        except StopIteration:
            password_el = None

        if username_el and password_el:
            return username_el, password_el

        return None, None

    username_input, password_input = find_username_and_password()
    if not username_input or not password_input:
        print("Fant fortsatt ikke feltene for brukernavn/passord.")
        print("Tips: Høyreklikk i nettleseren -> Inspect på begge feltene og noter ID eller name,")
        print("og legg dem inn i listene common_user_ids / common_pass_ids i login().")
        raise TimeoutException("Kunne ikke lokalisere brukernavn/passord-felt.")

    username_input.clear()
    username_input.send_keys(username)

    password_input.clear()
    password_input.send_keys(password)
    password_input.send_keys(Keys.ENTER)

    # Håndter eventuelt ekstra steg: "Vi gjenkjenner ikke datamaskinen ... kundenr ID"
    handle_device_verification(driver, user_id)

    # Vent til hovedmenyen er lastet (for eksempel ved å lete etter menyen Hjem)
    try:
        wait.until(
            EC.presence_of_element_located(
                (By.XPATH, "//*[contains(text(), 'Hjem') or contains(text(), 'Home')]")
            )
        )
    except TimeoutException:
        print("Innloggingen ser ikke ut til å ha fullført korrekt (fant ikke Hjem/Home).")
        raise


def handle_device_verification(driver: webdriver.Chrome, user_id: str) -> None:
    """
    Håndterer dialogen:
    "Vi gjenkjenner ikke datamaskinen, vennligst skriv inn din kundenr ID for validering".
    """
    wait = WebDriverWait(driver, 15)

    # Vent kort for å se om denne meldingen dukker opp i det hele tatt.
    try:
        wait.until(
            EC.presence_of_element_located(
                (
                    By.XPATH,
                    "//*[contains(text(), 'Vi gjenkjenner ikke datamaskinen') or "
                    "contains(text(), 'kundenr ID') or "
                    "contains(translate(text(),'CUSTOMER','customer'),'customer')]",
                )
            )
        )
    except TimeoutException:
        # Meldingen kom ikke – da er det ingen ekstra verifisering å gjøre.
        return

    # Når vi vet at verifiserings-siden er oppe, prøver vi å finne et passende inputfelt.
    user_id_input = None

    # 1) Prøv etter typiske id/name-verdier
    candidate_ids = [
        "CustomerId",
        "CustomerID",
        "KundeId",
        "Kundenr",
        "CustomerNumber",
        "CustId",
    ]
    for cid in candidate_ids:
        try:
            el = driver.find_element(By.ID, cid)
            if el.is_displayed():
                user_id_input = el
                break
        except NoSuchElementException:
            continue

    # 2) Bredere XPath på id/name
    if user_id_input is None:
        try:
            user_id_input = wait.until(
                EC.presence_of_element_located(
                    (
                        By.XPATH,
                        "//input[not(@type='hidden') and "
                        "("
                        "contains(translate(@name,'ID','id'),'id') or "
                        "contains(translate(@id,'ID','id'),'id') or "
                        "contains(translate(@name,'KUND','kund'),'kund') or "
                        "contains(translate(@id,'KUND','kund'),'kund')"
                        ")]",
                    )
                )
            )
        except TimeoutException:
            user_id_input = None

    # 3) Fallback: første synlige text/number/tel-input på siden
    if user_id_input is None:
        try:
            candidates = driver.find_elements(
                By.XPATH,
                "//input[not(@type='hidden') and (@type='text' or @type='number' or @type='tel')]",
            )
            user_id_input = next(el for el in candidates if el.is_displayed())
        except StopIteration:
            user_id_input = None

    if user_id_input is None:
        print(
            "Fant ikke feltet for kundenr ID på verifiseringssiden. "
            "Bruk Inspect i nettleseren for å finne ID/name og gi meg gjerne verdien.",
        )
        return

    user_id_input.clear()
    user_id_input.send_keys(user_id)

    # Forsøk å sende skjemaet – enten med ENTER eller ved å trykke en knapp.
    user_id_input.send_keys(Keys.ENTER)

    try:
        submit_btn = wait.until(
            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    "//button[contains(., 'OK') or contains(., 'Fortsett') or contains(., 'Neste')]"
                    " | //input[@type='submit' or @type='button'][contains(@value, 'OK') or contains(@value, 'Fortsett') or contains(@value, 'Neste')]",
                )
            )
        )
        submit_btn.click()
    except TimeoutException:
        # Hvis vi ikke finner en knapp, håper vi ENTER var nok.
        pass


def open_innkjopsportal(driver: webdriver.Chrome) -> None:
    """Navigerer til Hjem -> Innkjøpsportal og bytter til ny fane."""
    wait = WebDriverWait(driver, 20)

    # Klikk på Hjem hvis nødvendig (kan være valgfritt)
    try:
        home_link = wait.until(
            EC.element_to_be_clickable(
                (By.XPATH, "//a[contains(text(), 'Hjem') or contains(text(), 'Home')]")
            )
        )
        home_link.click()
    except TimeoutException:
        # Om vi ikke finner Hjem, prøver vi likevel å finne Innkjøpsportal direkte.
        pass

    original_handles = driver.window_handles

    # Finn og klikk Innkjøpsportal (kan være norsk/engelsk eller uten ø)
    try:
        innkjop_link = wait.until(
            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    "//a[contains(translate(text(),'Øø','Oo'), 'Innkjopsportal') or contains(text(), 'Innkjøpsportal') or contains(text(), 'Purchasing Portal')]",
                )
            )
        )
        innkjop_link.click()
    except TimeoutException:
        print("Fant ikke lenken til Innkjøpsportal. Juster XPath-lokatoren i open_innkjopsportal().")
        raise

    # Vent til ny fane åpnes og bytt til den
    try:
        WebDriverWait(driver, 15).until(lambda d: len(d.window_handles) > len(original_handles))
        new_handles = driver.window_handles
        new_tab = [h for h in new_handles if h not in original_handles][0]
        driver.switch_to.window(new_tab)
    except (TimeoutException, IndexError):
        print("Fant ikke ny fane for Innkjøpsportal etter klikk.")
        raise


def search_and_add_item(driver: webdriver.Chrome, order: Dict[str, object]) -> None:
    """Søker opp varenummer, fyller antall og legger i handlekurv."""
    varenr = str(order.get("varenr", "")).strip()
    antall = int(order.get("antall", 0))
    leverandor = str(order.get("leverandor", ""))

    if not varenr or antall <= 0:
        print(f"Hopper over ordre med ugyldige data: {order}")
        return

    print(f"Behandler vare '{varenr}' (leverandør: {leverandor}, antall: {antall})...")

    wait = WebDriverWait(driver, 20)

    try:
        # Bruker konkret info fra HTML-en:
        # <input placeholder="Search" data-test-selector="headerSearchInputTextField" ...>
        search_input = wait.until(
            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    "//input[@data-test-selector='headerSearchInputTextField']",
                )
            )
        )
    except TimeoutException:
        # Fallback: forsøk på placeholder / klasse dersom data-test-selector endres
        try:
            search_input = wait.until(
                EC.element_to_be_clickable(
                    (
                        By.XPATH,
                        "//input[@type='text' and ("
                        "contains(@placeholder, 'Search') or "
                        "contains(@class, 'search-input')"
                        ")]",
                    )
                )
            )
        except TimeoutException:
            print("Fant ikke søkefeltet for varenummer. Juster XPath-lokatoren i search_and_add_item().")
            return

    search_input.clear()
    search_input.send_keys(varenr)
    search_input.send_keys(Keys.ENTER)

    # Vent til søkeresultatene er klare. 10 sekunder ekstra som ønsket.
    time.sleep(10)

    try:
        # Bruker konkret info: data-test-selector="product_qtyOrdered"
        qty_input = wait.until(
            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    "//input[@data-test-selector='product_qtyOrdered']",
                )
            )
        )
    except TimeoutException:
        # Fallback dersom data-test-selector endres:
        try:
            qty_input = wait.until(
                EC.element_to_be_clickable(
                    (
                        By.XPATH,
                            "//input[@type='number' and @min='0' and @max='999999']",
                    )
                )
            )
        except TimeoutException:
            print(f"Fant ikke QTY-felt for varenummer {varenr}.")
            return

    qty_input.clear()
    qty_input.send_keys(str(antall))

    try:
        # Teksten "Add to Cart" ligger i et <span>; klikk på nærmeste klikkbare parent (ofte en knapp)
        add_to_cart_span = wait.until(
            EC.presence_of_element_located(
                (
                    By.XPATH,
                    "//span[contains(@class,'TypographyStyle') and normalize-space(text())='Add to Cart']",
                )
            )
        )
        # Forsøk å klikke parent hvis mulig, ellers selve span
        add_to_cart_button = add_to_cart_span
        try:
            parent = add_to_cart_span.find_element(By.XPATH, "./ancestor::button[1]")
            add_to_cart_button = parent
        except NoSuchElementException:
            # Ingen knapp som parent, bruk span direkte
            pass

        wait.until(EC.element_to_be_clickable(add_to_cart_button))
        add_to_cart_button.click()
    except TimeoutException:
        print(f"Fant ikke 'Add to Cart'-knappen for varenummer {varenr}.")
        return

    handle_sales_order_class_dialog(driver)

    print(f"Vare {varenr} lagt til i handlekurv (forsøkt).")


def handle_sales_order_class_dialog(driver: webdriver.Chrome) -> None:
    """Håndterer dialogen 'Select sales order class' ved å velge Standard og OK."""
    wait = WebDriverWait(driver, 10)

    try:
        wait.until(
            EC.presence_of_element_located(
                (By.XPATH, "//*[contains(text(), 'Select sales order class')]"),
            ),
        )
    except TimeoutException:
        # Dialogen dukket ikke opp – det er greit, vi fortsetter bare.
        return

    try:
        # Bruker konkret info: input med data-test-selector="changeSalesOrderClassSelector-input"
        class_input = wait.until(
            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    "//input[@data-test-selector='changeSalesOrderClassSelector-input']",
                ),
            ),
        )
        class_input.click()

        # Vent på at nedtrekkslisten vises, og velg Standard
        standard_option = wait.until(
            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    "//div[contains(@class,'Option') and normalize-space(text())='Standard']",
                ),
            ),
        )
        standard_option.click()
    except NoSuchElementException:
        # Hvis vi ikke finner selve Standard-valget, forsøker vi bare å trykke OK.
        pass
    except TimeoutException:
        print("Fant ikke nedtrekksfeltet / Standard-valget i 'Select sales order class'-dialogen.")

    try:
        # Bruker konkret info: data-test-selector="salesOrderClassSubmit"
        ok_button = wait.until(
            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    "//button[@data-test-selector='salesOrderClassSubmit']",
                ),
            ),
        )
        ok_button.click()
    except TimeoutException:
        # Klarer vi ikke å trykke OK, fortsetter vi likevel.
        pass


def process_orders(driver: webdriver.Chrome, orders: List[Dict[str, object]]) -> None:
    """Kjører gjennom alle ordre i en liste."""
    if not orders:
        print("Ingen ordre å prosessere (tom liste).")
        return

    for order in orders:
        try:
            search_and_add_item(driver, order)
        except Exception as exc:  # noqa: BLE001
            print(f"Feil under behandling av ordre {order}: {exc}")


def run_polaris(orders: List[Dict[str, object]], *, interactive: bool = False) -> None:
    """Kjører Polaris-flyten for en gitt ordre-liste."""
    creds = load_credentials()
    driver = create_driver()

    try:
        login(driver, creds["username"], creds["password"], creds["user_id"])
        open_innkjopsportal(driver)
        process_orders(driver, orders)
        print("Polaris: ferdig med alle ordre.")
        if interactive:
            input("Polaris: Trykk Enter i terminalen for å lukke nettleseren...")
    finally:
        driver.quit()


def main() -> None:
    if not ORDERS:
        print("ORDERS-listen er tom. Legg inn bestillinger i polaris_automat.py.")
        return

    run_polaris(ORDERS, interactive=True)


if __name__ == "__main__":
    main()

