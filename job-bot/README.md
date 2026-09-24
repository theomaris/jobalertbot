# Bot alerte joburi pe Telegram

Verifica automat, la fiecare oră, joburi noi pe Hipo.ro (care agregă joburi din
toată țara — eJobs, BestJobs, angajatori direcți) după cuvintele cheie și
orașele tale, și îți trimite un mesaj pe Telegram pentru fiecare job nou.

Rulează gratuit, în cloud, prin GitHub Actions — nu trebuie să ții nimic
pornit pe calculatorul tău.

## Pasul 1 — Creează botul de Telegram

1. Deschide Telegram, caută **@BotFather** și dă-i `/start`.
2. Trimite-i comanda `/newbot`, alege un nume și un username (trebuie să se
   termine în `bot`, ex: `IonMecatronicaJobsBot`).
3. BotFather îți dă un **token**, ceva de forma:
   `123456789:AAHdq7bVeM...` — **salvează-l**, ai nevoie de el la pasul 3.
4. Caută botul tău nou creat în Telegram (după username-ul ales) și dă-i
   `/start` (altfel nu-ți poate trimite mesaje).

## Pasul 2 — Află-ți `chat_id`

1. Trimite orice mesaj botului tău (ex: "salut").
2. În browser, accesează (înlocuiește `<TOKEN>` cu tokenul tău):
   `https://api.telegram.org/bot<TOKEN>/getUpdates`
3. În JSON-ul afișat, caută `"chat":{"id":123456789,...}` — acel număr e
   `chat_id`-ul tău. Salvează-l.

## Pasul 3 — Pune codul pe GitHub

1. Creează un cont gratuit pe [github.com](https://github.com) dacă nu ai deja.
2. Creează un **repository nou, privat** (ex: `job-alert-bot`).
3. Încarcă toate fișierele din acest folder în repo (poți trage-și-lăsa
   fișierele direct din interfața web GitHub, "Add file" → "Upload files").

## Pasul 4 — Adaugă token-ul și chat_id-ul ca "Secrets"

1. În repo, mergi la **Settings → Secrets and variables → Actions**.
2. Apasă **New repository secret** și adaugă:
   - Nume: `TELEGRAM_BOT_TOKEN` → valoare: tokenul de la Pasul 1
   - Nume: `TELEGRAM_CHAT_ID` → valoare: chat_id-ul de la Pasul 2

## Pasul 5 — Activează Actions

1. Mergi la tab-ul **Actions** din repo.
2. Dacă apare un buton "I understand my workflows, go ahead and enable them",
   apasă-l.
3. Botul va rula automat, o dată pe oră. Pentru primul test, poți rula manual:
   Actions → "Job Alert Bot" → **Run workflow**.

## Pasul 6 — Adaugă și LinkedIn, eJobs, BestJobs (prin alertele lor de email)

Aceste trei site-uri nu pot fi "citite" automat direct (LinkedIn blochează
activ orice acces automatizat, iar eJobs/BestJobs sunt aplicații JavaScript
greu de citit fără browser). În schimb, folosim funcția lor **oficială** de
alertă pe email — 100% permisă, pentru că te abonezi chiar tu, ca utilizator.

### 6.1 — Abonează-te la alerte pe fiecare site

- **LinkedIn**: fă o căutare de joburi cu cuvintele tale cheie (mecatronică,
  robotică etc.) + locație București, apoi activează switch-ul **"Alertă
  joburi"** din partea de sus a rezultatelor.
- **eJobs.ro**: fă o căutare similară, apoi apasă **"Abonează-te"** /
  **"Activează alertă job"** (buton vizibil sub rezultate).
- **BestJobs.eu**: la fel, caută și activează alerta / notificarea pentru
  căutarea respectivă.

Toate trei îți vor trimite emailuri (de obicei zilnic sau instant) cu joburi
noi, pe adresa ta de Gmail.

### 6.2 — Creează o parolă de aplicație pentru Gmail

(Ai nevoie de verificare în doi pași activată pe cont — dacă n-o ai, activeaz-o
mai întâi din **myaccount.google.com → Securitate**.)

1. Mergi la **myaccount.google.com → Securitate → Parole pentru aplicații**
   (sau caută direct "App Passwords" în Google).
2. Creează o parolă nouă (orice nume, ex: "job-alert-bot").
3. Google îți dă un cod de 16 caractere — **salvează-l**, e diferit de parola
   ta normală de Gmail și e singura dată când îl vezi.

### 6.3 — Adaugă încă două Secrets în GitHub

La fel ca la Pasul 4 (Settings → Secrets and variables → Actions):

- Nume: `GMAIL_ADDRESS` → valoare: adresa ta de Gmail
- Nume: `GMAIL_APP_PASSWORD` → valoare: codul de 16 caractere de la 6.2

Gata — la următoarea rulare, botul va citi și emailurile de alertă de la
LinkedIn/eJobs/BestJobs și le va retrimite pe Telegram, alături de cele
găsite pe Hipo.ro.

### Notă despre precizie

Detectarea automată a emailurilor de alertă (vs. alte emailuri de la același
site) se face după expeditor + cuvinte din subiect, configurabile în
`email_config.json`. Dacă observi că unele emailuri de alertă nu sunt
prinse, deschide un email de-al lor în Gmail, verifică exact adresa de
expeditor și subiectul, și ajustează `subiect_contine_unul_din` din
`email_config.json`.

## Personalizare

Editează `config.json` direct din GitHub (click pe fișier → creion pentru
editare):
- `keywords`: cuvintele cheie căutate (ex: `"Mecatronica"`, `"Automatizari"`,
  `"Marketing"` — adaugă orice domeniu te interesează)
- `orase`: orașele din care vrei joburi
- `pagini_de_verificat`: câte pagini de rezultate să verifice per căutare

După ce salvezi modificarea, se aplică automat la următoarea rulare.

## Notă

Acesta e un instrument de **alertă**, nu aplică automat pentru tine — îți
trimite link-ul, tu decizi dacă aplici și aplici manual (candidaturile
generice, trimise fără citirea anunțului, au oricum șanse mici). Dacă vrei
ulterior și generare automată de CV/scrisoare de intenție adaptate per
anunț, pot să adaug și asta.
