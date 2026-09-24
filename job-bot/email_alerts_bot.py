"""
Bot de alerta joburi -> Telegram, PARTEA 2: din email (LinkedIn, eJobs, BestJobs)
==================================================================================
LinkedIn, eJobs si BestJobs nu pot fi "scrapuite" direct (LinkedIn blocheaza
activ, celelalte doua sunt aplicatii JavaScript greu de citit automat).
In schimb, toate trei au propriul sistem de "alerta job pe email" -- te
abonezi o data, cu cuvintele tale cheie, pe fiecare site, iar ei iti trimit
un email cand apare ceva nou.

Acest script:
  1. se conecteaza la o casuta Gmail (prin IMAP, cu o "parola de aplicatie")
  2. citeste email-urile necitite de la LinkedIn / eJobs / BestJobs
  3. extrage link-urile catre joburi din acele email-uri
  4. trimite pe Telegram doar cele noi (pe care nu le-a mai trimis)
  5. marcheaza email-urile ca citite

Necesita, pe langa TELEGRAM_BOT_TOKEN si TELEGRAM_CHAT_ID:
  GMAIL_ADDRESS       -> adresa de gmail folosita pentru alertele de job
  GMAIL_APP_PASSWORD  -> parola de aplicatie (NU parola normala de cont, vezi README)
"""

import email
import imaplib
import json
import os
import re
import sys
import time
from email.header import decode_header
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE_DIR = Path(__file__).parent
EMAIL_CONFIG_PATH = BASE_DIR / "email_config.json"
SEEN_PATH = BASE_DIR / "seen_email_jobs.json"

GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

IMAP_HOST = "imap.gmail.com"


def load_email_config():
    with open(EMAIL_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_seen():
    if SEEN_PATH.exists():
        with open(SEEN_PATH, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_seen(seen_ids):
    with open(SEEN_PATH, "w", encoding="utf-8") as f:
        json.dump(sorted(seen_ids), f, ensure_ascii=False, indent=2)


def decode_mime_words(s):
    if not s:
        return ""
    parts = decode_header(s)
    decoded = ""
    for text, enc in parts:
        if isinstance(text, bytes):
            decoded += text.decode(enc or "utf-8", errors="ignore")
        else:
            decoded += text
    return decoded


def get_email_body_html(msg):
    """Extrage partea HTML (preferata) sau text a unui mesaj email."""
    html_body = None
    text_body = None
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition") or "")
            if "attachment" in disp:
                continue
            try:
                payload = part.get_payload(decode=True)
                if not payload:
                    continue
                charset = part.get_content_charset() or "utf-8"
                decoded = payload.decode(charset, errors="ignore")
            except Exception:
                continue
            if ctype == "text/html" and html_body is None:
                html_body = decoded
            elif ctype == "text/plain" and text_body is None:
                text_body = decoded
    else:
        try:
            payload = msg.get_payload(decode=True)
            charset = msg.get_content_charset() or "utf-8"
            decoded = payload.decode(charset, errors="ignore") if payload else ""
        except Exception:
            decoded = ""
        if msg.get_content_type() == "text/html":
            html_body = decoded
        else:
            text_body = decoded
    return html_body, text_body


def extract_job_links(html_body, domenii_job_valide):
    """Extrage (titlu, link) din HTML-ul unui email, pastrand doar linkurile
    catre domeniile de joburi cunoscute."""
    if not html_body:
        return []
    soup = BeautifulSoup(html_body, "html.parser")
    results = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not any(domain in href for domain in domenii_job_valide):
            continue
        title = a.get_text(strip=True)
        if not title or len(title) < 3:
            # unele linkuri au doar o imagine, fara text -> ignoram
            continue
        results.append((title, href))
    # deduplica dupa link
    seen_links = set()
    unique = []
    for title, href in results:
        if href in seen_links:
            continue
        seen_links.add(href)
        unique.append((title, href))
    return unique


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


def matches_source(from_header, subject, sursa):
    from_lower = from_header.lower()
    if not any(domain in from_lower for domain in sursa["domenii_expeditor"]):
        return False
    keywords = sursa.get("subiect_contine_unul_din") or []
    if not keywords:
        return True
    subject_lower = subject.lower()
    return any(kw.lower() in subject_lower for kw in keywords)


def main():
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        print("[!] GMAIL_ADDRESS sau GMAIL_APP_PASSWORD lipsesc din mediu -- sar peste pasul de email.")
        return

    config = load_email_config()
    seen = load_seen()
    surse = config["surse_email"]
    domenii_job_valide = config["domenii_job_valide"]

    print("Conectare la Gmail...")
    imap = imaplib.IMAP4_SSL(IMAP_HOST)
    imap.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
    imap.select("INBOX")

    status, data = imap.search(None, "UNSEEN")
    if status != "OK":
        print("[!] Nu am putut citi inbox-ul.")
        imap.logout()
        return

    email_ids = data[0].split()
    print(f"Email-uri necitite gasite: {len(email_ids)}")

    new_jobs = []  # (titlu, link)
    processed_email_ids = []

    for eid in email_ids:
        status, msg_data = imap.fetch(eid, "(RFC822)")
        if status != "OK" or not msg_data or not msg_data[0]:
            continue
        raw_email = msg_data[0][1]
        msg = email.message_from_bytes(raw_email)

        from_header = decode_mime_words(msg.get("From", ""))
        subject = decode_mime_words(msg.get("Subject", ""))

        matched_source = None
        for sursa in surse:
            if matches_source(from_header, subject, sursa):
                matched_source = sursa["nume"]
                break

        if not matched_source:
            continue  # nu e o alerta de job cunoscuta -> lasam necitit, nu ne atingem de el

        print(f"-> Procesez email de la {matched_source}: {subject!r}")
        html_body, _ = get_email_body_html(msg)
        job_links = extract_job_links(html_body, domenii_job_valide)

        for title, href in job_links:
            job_key = f"{matched_source}:{href}"
            if job_key not in seen:
                new_jobs.append((f"[{matched_source}] {title}", href))
                seen.add(job_key)

        processed_email_ids.append(eid)

    print(f"Joburi noi gasite in email: {len(new_jobs)}")

    for title, href in new_jobs:
        message = f"🆕 <b>{title}</b>\n{href}"
        ok = send_telegram_message(message)
        if ok:
            print(f"  [OK] Trimis: {title}")
        time.sleep(0.5)

    # marcheaza ca citite doar email-urile pe care le-am procesat cu succes
    for eid in processed_email_ids:
        imap.store(eid, "+FLAGS", "\\Seen")

    imap.logout()
    save_seen(seen)
    print("Gata.")


if __name__ == "__main__":
    sys.exit(main() or 0)
