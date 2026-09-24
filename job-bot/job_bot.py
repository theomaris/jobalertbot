"""
Bot de alerta joburi -> Telegram
=================================
Cauta periodic joburi noi pe Hipo.ro (care agrega joburi din toata tara,
inclusiv eJobs, BestJobs si angajatori directi) dupa cuvintele cheie si
orasele definite in config.json, si trimite un mesaj pe Telegram pentru
fiecare job NOU gasit (pe care nu l-a mai trimis inainte).

Rulare locala:
    pip install -r requirements.txt
    export TELEGRAM_BOT_TOKEN="123456:ABC-your-token"
    export TELEGRAM_CHAT_ID="123456789"
    python job_bot.py

In GitHub Actions, cele doua variabile de mediu vin din Secrets (vezi README).
"""

import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.json"
SEEN_PATH = BASE_DIR / "seen_jobs.json"

HIPO_BASE = "https://www.hipo.ro/locuri-de-munca/cautajob/Toate-Domeniile"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Regex care extrage ID-ul jobului din link-ul Hipo:
# https://www.hipo.ro/locuri-de-munca/locuri_de_munca/271572/Companie/Titlu-Job
JOB_LINK_RE = re.compile(r"/locuri_de_munca/(\d+)/")


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_seen():
    if SEEN_PATH.exists():
        with open(SEEN_PATH, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_seen(seen_ids):
    with open(SEEN_PATH, "w", encoding="utf-8") as f:
        json.dump(sorted(seen_ids), f, ensure_ascii=False, indent=2)


def build_url(keyword, oras, page):
    kw = quote(keyword)
    url = f"{HIPO_BASE}/{oras}/{kw}"
    if page > 1:
        url += f"/{page}"
    return url


def fetch_jobs(keyword, oras, page):
    """Descarca si parseaza o pagina de rezultate Hipo.ro. Returneaza lista de joburi."""
    url = build_url(keyword, oras, page)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  [!] Eroare la {url}: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    jobs = []

    # Fiecare job e intr-un <h5> sau <h6>/<a> cu link catre /locuri_de_munca/ID/...
    for link in soup.select("a[href*='/locuri_de_munca/']"):
        href = link.get("href", "")
        match = JOB_LINK_RE.search(href)
        if not match:
            continue
        job_id = match.group(1)

        title = link.get_text(strip=True)
        if not title:
            continue

        full_url = href if href.startswith("http") else f"https://www.hipo.ro{href}"

        jobs.append({
            "id": job_id,
            "title": title,
            "url": full_url,
        })

    # Deduplica in cadrul aceleiasi pagini (titlul apare de obicei de 2 ori: in imagine si in text)
    unique = {}
    for j in jobs:
        unique[j["id"]] = j
    return list(unique.values())


def send_telegram_message(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("  [!] TELEGRAM_BOT_TOKEN sau TELEGRAM_CHAT_ID lipsesc din mediu.")
        return False
    api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    try:
        r = requests.post(api_url, data=payload, timeout=15)
        r.raise_for_status()
        return True
    except requests.RequestException as e:
        print(f"  [!] Eroare la trimiterea pe Telegram: {e}")
        return False


def main():
    config = load_config()
    seen = load_seen()
    keywords = config["keywords"]
    orase = config["orase"]
    max_pages = config.get("pagini_de_verificat", 2)

    print(f"Cuvinte cheie: {keywords}")
    print(f"Orase: {orase}")
    print(f"Joburi cunoscute deja: {len(seen)}")

    new_jobs = {}  # id -> job dict (deduplicat global, un job poate aparea la mai multe cautari)

    for keyword in keywords:
        for oras in orase:
            for page in range(1, max_pages + 1):
                print(f"-> Caut '{keyword}' in '{oras}', pagina {page}...")
                jobs = fetch_jobs(keyword, oras, page)
                if not jobs:
                    break  # nu mai sunt rezultate / pagina goala -> trecem la urmatoarea combinatie
                found_new_on_page = False
                for job in jobs:
                    if job["id"] not in seen:
                        new_jobs[job["id"]] = job
                        found_new_on_page = True
                # daca pagina asta n-a adus nimic nou fata de ce stim deja, oprim paginarea
                # (evitam sa cerem prea multe pagini degeaba)
                time.sleep(1)  # politete fata de server
                if page >= max_pages:
                    break

    print(f"Joburi noi gasite: {len(new_jobs)}")

    for job in new_jobs.values():
        message = f"🆕 <b>{job['title']}</b>\n{job['url']}"
        ok = send_telegram_message(message)
        if ok:
            print(f"  [OK] Trimis: {job['title']}")
        seen.add(job["id"])
        time.sleep(0.5)  # nu spamam API-ul Telegram

    save_seen(seen)
    print("Gata.")


if __name__ == "__main__":
    sys.exit(main() or 0)
