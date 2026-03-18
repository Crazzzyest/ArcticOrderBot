# Polaris innkjøpsportal – automatisk bestilling

Dette prosjektet inneholder et Python-script som:

- **Logger inn** på `https://intl.polarisportal.com/mainmenu.asp`.
- **Åpner** `Hjem -> Innkjøpsportal` (ny fane).
- **Legger varer i handlekurv** basert på en enkel liste med:
  - leverandør (kun til logging),
  - antall,
  - leverandør-varenummer.

## Forutsetninger

- Windows 10/11.
- Installert **Python 3.9+** (sjekk med `python --version`).
- Google **Chrome** installert.

## Installasjon

1. Åpne en terminal i prosjektmappen (`c:\KOOOODE\AFKI\Arctic`).
2. (Anbefalt) Opprett og aktiver et virtuelt miljø:

   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   ```

3. Installer avhengigheter:

   ```bash
   pip install -r requirements.txt
   ```

## Konfigurasjon av innlogging (.env)

Lag en fil `.env` i prosjektmappen basert på `.env.example`:

```bash
copy .env.example .env
```

Åpne `.env` og fyll inn dine faktiske verdier:

```text
POLARIS_USERNAME=lasse@arcticmotor.no
POLARIS_PASSWORD=Lettmelk2234!
POLARIS_USER_ID=19026291
```

> **Merk**: Oppbevar `.env` privat, og ikke del den videre.

## Rediger bestillingslisten

I `polaris_automat.py` finnes en liste `ORDERS`. Rediger denne før kjøring, for eksempel:

```python
ORDERS = [
    {"leverandor": "Leverandor1", "varenr": "123456", "antall": 2},
    {"leverandor": "Leverandor2", "varenr": "ABC789", "antall": 5},
]
```

## Kjøring av scriptet

Fra prosjektmappen:

```bash
python polaris_automat.py
```

Scriptet vil:

- åpne Chrome,
- logge inn,
- åpne innkjøpsportalen i ny fane,
- for hver linje i `ORDERS`:
  - søke på varenummer,
  - vente på at siden er lastet,
  - fylle QTY,
  - trykke «Add to cart»,
  - velge «Standard» i «Select sales order class»-vinduet (hvis det dukker opp) og bekrefte.

## Justering av lokatorer

HTML-strukturen i Polaris-portalen kan endre seg. Hvis noe ikke fungerer (for eksempel at felt ikke blir funnet), må du justere lokatorene (XPath/CSS) i `polaris_automat.py`. Kommentarene i koden peker på hvilke steder som er mest sannsynlig å måtte justeres.

## Ordrebot (Gmail -> PDF -> handlekurver)

Prosjektet inneholder også en `ordrebot` som kan:

- Poll’e Gmail (Gmail API) for nye e‑poster som matcher `has:attachment filename:pdf`
- Laste ned PDF‑vedlegg
- Ekstrahere `leverandor`, `varenr` og `antall`
- Rute ordrelinjer til `run_polaris/run_kellox/run_ktm` (Selenium) og legge i handlekurv
- Label’e e‑posten som prosessert (`processed-afki`)

### Konfig (env vars)

I tillegg til leverandør-credentials i `.env`, må du ha Google OAuth secrets:

- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `GOOGLE_REFRESH_TOKEN`
- (valgfritt) `GOOGLE_TOKEN_URI` (default er `https://oauth2.googleapis.com/token`)

Andre nyttige env vars:

- `POLL_INTERVAL_SECONDS` (default 60)
- `MAX_MESSAGES_PER_POLL` (default 10)
- `RUN_ONCE` (1 for single-run)
- `GMAIL_QUERY` (default `has:attachment filename:pdf`)
- `GMAIL_PROCESSED_LABEL` (default `processed-afki`)

### Hent refresh token (kjøres lokalt én gang)

1. Last ned Google OAuth **Desktop app** client secrets JSON.
2. Kjør:

```bash
set GOOGLE_CLIENT_SECRETS_JSON=C:\path\to\client_secret.json
python -m ordrebot.auth_init
```

Scriptet skriver ut verdier du kan lime inn som secrets i Sliplane.

### Test parsing lokalt

```bash
python -m ordrebot.pdf_parser ordre.pdf
```

### Kjør ordrebot lokalt (for test)

```bash
set RUN_ONCE=1
python -m ordrebot.runner
```

### Docker / Sliplane

Det finnes en `Dockerfile` som kjører `python -m ordrebot.runner` som standard.\n

