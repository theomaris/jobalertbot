"""
Bot de alerta joburi -> Telegram, PARTEA 2: din email (LinkedIn, eJobs, BestJobs)
==================================================================================
Citeste email-urile necitite de la LinkedIn / eJobs / BestJobs, extrage
linkurile catre joburi, verifica ca linkul e valid, si trimite pe Telegram
doar joburile noi (pe care nu le-a mai trimis).

Necesita, pe langa TELEGRAM_BOT_TOKEN si TELEGRAM_CHAT_ID:
  GMAIL_ADDRESS       -> adresa de gmail folosita pentru alertele de job
  GMAIL_APP_PASSWORD  -> parola de aplicatie (NU parola normala de cont)
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
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

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

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}


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
    """Extrage partea HTML (preferata) a unui mesaj email."""
    html_body = None
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition") or "")
            if "attachment" in disp:
                continue
            if ctype != "text/html":
                continue
            try:
                payload = part.get_payload(decode=True)
                if not payload:
                    continue
                charset = part.get_content_charset() or "utf-8"
                html_body = payload.decode(charset, errors="ignore")
                break
            except Exception:
                continue
    else:
        if msg.get_content_type() == "text/html":
            try:
                payload = msg.get_payload(decode=True)
                charset = msg.get_content_charset() or "utf-8"
                html_body = payload.decode(charset, errors="ignore") if payload else None
            except Exception:
                html_body = None
    return html_body


def normalize_url(url, tracking_params):
    """Curata parametrii de tracking din URL ca sa nu para joburi diferite
    acelasi job."""
    try:
        parsed = urlparse(url)
        if not parsed.query:
            return url
        q = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
             if k not in tracking_params]
        return urlunparse(parsed._replace(query=urlencode(q)))
    except Exception:
        return url


def link_is_excluded(url, link_exclude):
    url_lower = url.lower()
    return any(pat.lower() in url_lower for pat in link_exclude)


def link_is_valid(url, timeout=8):
    """Verifica daca linkul raspunde. Returneaza (ok, url_final).
    Urmareste redirect-urile. Accepta 200, 301, 302, 303, 307, 308."""
    try:
        r = requests.head(url, headers=HEADERS, timeout=timeout,
                          allow_redirects=True)
        if r.status_code < 400:
            return True, r.url
        # unele servere nu raspund la HEAD -> incercam GET
        r = requests.get(url, headers=HEADERS, timeout=timeout,
                         allow_redirects=True, stream=True)
        ok = r.status_code < 400
        return ok, r.url
    except requests.RequestException:
        # daca nu putem verifica, preferam sa trimitem decat sa pierdem jobul
        return True, url


def extract_job_links(html_body, config):
    """Extrage (titlu, link) din HTML-ul unui email."""
    if not html_body:
        return []
    soup = BeautifulSoup(html_body, "html.parser")

    domenii = config["domenii_job_valide"]
    link_exclude = config.get("link_exclude", [])
    tracking_params = set(config.get("link_tracking_parametri", []))

    results = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href.startswith("http"):
            continue
        if not any(d in href for d in domenii):
            continue
        if link_is_excluded(href, link_exclude):
            continue
        title = a.get_text(strip=True)
        if not title or len(title) < 3:
            continue
        # titluri care clar nu-s joburi
        if title.lower() in {"aplica", "aplica acum", "vezi job", "vezi detalii",
                              "unsubscribe", "dezabonare", "setari"}:
            continue
        normalized = normalize_url(href, tracking_params)
        results.append((title, normalized))

    # deduplica dupa link normalizat
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

    subject_lower = subject.lower()

    excl = sursa.get("subiect_exclude") or []
    if any(kw.lower() in subject_lower for kw in excl):
        return False

    keywords = sursa.get("subiect_contine_unul_din") or []
    if not keywords:
        return True
    return any(kw.lower() in subject_lower for kw in keywords)


def main():
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        print("[!] GMAIL_ADDRESS sau GMAIL_APP_PASSWORD lipsesc din mediu -- sar peste pasul de email.")
        return

    config = load_email_config()
    seen = load_seen()
    surse = config["surse_email"]

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

    new_jobs = []  # (sursa, titlu, link)
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
            continue

        print(f"-> Procesez email de la {matched_source}: {subject!r}")
        html_body = get_email_body_html(msg)
        job_links = extract_job_links(html_body, config)
        print(f"   Linkuri de job gasite in email: {len(job_links)}")

        for title, href in job_links:
            job_key = f"{matched_source}:{href}"
            if job_key not in seen:
                new_jobs.append((matched_source, title, href))
                seen.add(job_key)

        processed_email_ids.append(eid)

    print(f"Joburi noi gasite in email: {len(new_jobs)}")

    for sursa, title, href in new_jobs:
        # verificare link
        ok, final_url = link_is_valid(href)
        if not ok:
            print(f"  [SKIP] Link invalid (404/410): {title} -> {href}")
            continue

        # daca redirect-ul a schimbat linkul si noul link e deja vazut, sarim
        final_key = f"{sursa}:{final_url}"
        if final_key != f"{sursa}:{href}" and final_key in seen:
            print(f"  [SKIP] Deja trimis (dupa redirect): {title}")
            continue

        message = f"🆕 <b>[{sursa}] {title}</b>\n{final_url}"
        if send_telegram_message(message):
            print(f"  [OK] Trimis: {title}")
        time.sleep(0.5)

    for eid in processed_email_ids:
        imap.store(eid, "+FLAGS", "\\Seen")

    imap.logout()
    save_seen(seen)
    print("Gata.")


if __name__ == "__main__":
    sys.exit(main() or 0)
