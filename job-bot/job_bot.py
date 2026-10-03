"""
Bot de alerta joburi -> Telegram (Hipo.ro)
Cauta joburi entry-level (Student/Absolvent, 0-1 an experienta)
in domeniul Inginerie, pe orasele din config.json.
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

HIPO_BASE = "https://www.hipo.ro/locuri-de-munca/cautajobfiltre"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

JOB_LINK_RE = re.compile(r"/locuri_de_munca/(\d+)/")

# Titluri care nu sunt joburi reale (butoane de "Aplica", etc.)
TITLU_INVALID = {
    "aplica", "aplica acum", "aplica fara cv", "aplică",
    "aplică acum", "aplică fără cv", "vezi job", "vezi detalii",
    "detalii", "trimite cv", "trimite cv-ul", "candidat",
    "salveaza", "salvează", "share", "distribuie", "afla mai multe",
    "află mai multe", "citeste mai mult", "citește mai mult",
    "joburi similare", "vezi toate",
}

CUVINTE_GENERICE = {
    "aplica", "aplică", "fara", "fără", "cv", "acum", "job", "joburi",
    "vezi", "detalii", "trimite", "candidat", "salveaza", "salvează",
    "share", "distribuie", "toate", "similare", "mai", "mult", "multe",
}


def titlu_e_valid(title):
    t = title.strip().lower()
    if not t or len(t) < 4:
        return False
    if t in TITLU_INVALID:
        return False
    if all(w in CUVINTE_GENERICE for w in t.split()):
        return False
    return True


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


def build_url(domeniu, oras, filtru_experienta, page):
    """Construieste URL-ul de cautare Hipo cu filtre."""
    url = f"{HIPO_BASE}/{domeniu}/{oras}/{filtru_experienta}/"
    if page > 1:
        url += f"?pagina={page}"
    return url


def fetch_jobs(domeniu, oras, filtru_experienta, page):
    url = build_url(domeniu, oras, filtru_experienta, page)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  [!] Eroare la {url}: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    jobs = []

    for link in soup.select("a[href*='/locuri_de_munca/']"):
        href = link.get("href", "")
        match = JOB_LINK_RE.search(href)
        if not match:
            continue
        job_id = match.group(1)

        title = link.get_text(strip=True)
        if not title:
            continue
        if not titlu_e_valid(title):
            continue

        full_url = href if href.startswith("http") else f"https://www.hipo.ro{href}"

        jobs.append({
            "id": job_id,
            "title": title,
            "url": full_url,
        })

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

    domenii = config.get("domenii", ["Inginerie"])
    orase = config["orase"]
    filtru_experienta = config.get(
        "filtru_experienta",
        "Student--Absolvent,0-1-an-experienta"
    )
    max_pages = config.get("pagini_de_verificat", 2)

    print(f"Domenii: {domenii}")
    print(f"Orase: {orase}")
    print(f"Filtru experienta: {filtru_experienta}")
    print(f"Joburi cunoscute deja: {len(seen)}")

    new_jobs = {}

    for domeniu in domenii:
        for oras in orase:
            for page in range(1, max_pages + 1):
                print(f"-> Caut '{domeniu}' in '{oras}', pagina {page}...")
                jobs = fetch_jobs(domeniu, oras, filtru_experienta, page)
                if not jobs:
                    break
                for job in jobs:
                    if job["id"] not in seen:
                        new_jobs[job["id"]] = job
                time.sleep(1)

    print(f"Joburi noi gasite: {len(new_jobs)}")

    for job in new_jobs.values():
        message = f"🆕 <b>{job['title']}</b>\n{job['url']}"
        ok = send_telegram_message(message)
        if ok:
            print(f"  [OK] Trimis: {job['title']}")
        seen.add(job["id"])
        time.sleep(0.5)

    save_seen(seen)
    print("Gata.")


if __name__ == "__main__":
    sys.exit(main() or 0)
