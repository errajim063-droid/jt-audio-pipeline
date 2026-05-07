#!/usr/bin/env python3
"""AI vocabulary tracker.

Reads the past 7 days of script_*.txt, asks Claude to extract new AI/tech terms,
syncs them to a Google Sheet named "Vocabulaire AI", then sends a digest email.

Usage : python vocab_tracker.py
Requires: credentials/service_account.json + GOOGLE_SHEET_ID in .env
"""
import json
import logging
import os
import smtplib
import sys
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

import anthropic
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

OUTPUT_DIR = Path.home() / "jt_audio"
CREDS_PATH = Path(__file__).parent / "credentials" / "service_account.json"
WORKSHEET_NAME = "Vocabulaire AI"
SHEET_HEADERS = ["Terme", "Définition", "Contexte", "Date", "Statut"]
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

RECIPIENT = "errajim063@gmail.com"
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s -- %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("vocab")

MONTHS_FR = {
    "January": "janvier", "February": "février", "March": "mars",
    "April": "avril", "May": "mai", "June": "juin",
    "July": "juillet", "August": "août", "September": "septembre",
    "October": "octobre", "November": "novembre", "December": "décembre",
}

EXTRACT_SYSTEM_PROMPT = """\
Tu es un expert en terminologie de l'intelligence artificielle et des technologies numériques.
Tu analyses des scripts radio en français pour en extraire les termes techniques spécifiques.

CRITÈRES DE SÉLECTION (sélectif — qualité avant quantité) :
- Termes techniques précis : architectures IA, protocoles, paradigmes (LLM, RAG, RLHF, etc.)
- Noms propres de modèles ou outils IA notables (GPT-4, Mistral, Gemini, etc.)
- Anglicismes techniques qui n'ont pas d'équivalent français courant
- Concepts émergents cités dans les scripts
EXCLURE : mots génériques comme "données", "technologie", "numérique", "cloud" seul, "startup".

FORMAT DE RÉPONSE : JSON uniquement, tableau d'objets, aucun texte autour.
Si aucun terme qualifié n'est trouvé, retourne : []

Schéma de chaque objet :
{
  "terme_fr": "terme en français (ou translittération francisée)",
  "terme_en": "terme original en anglais si différent, sinon null",
  "definition": "définition en une phrase en français, claire et accessible à un non-spécialiste",
  "contexte": "phrase exacte du script où le terme apparaît (copie mot pour mot)",
  "date": "YYYY-MM-DD de la première apparition dans les scripts fournis",
  "youtube_query": "requête YouTube pour trouver une vidéo explicative en français (ex: 'LLM large language model explication français')"
}\
"""


# ── Script loading ────────────────────────────────────────────────────────────

def find_recent_scripts(days: int = 7) -> dict[str, str]:
    """Return {date_str: content} for script files dated within the past N days."""
    cutoff = datetime.now() - timedelta(days=days)
    scripts: dict[str, str] = {}
    for path in sorted(OUTPUT_DIR.glob("script_*.txt")):
        try:
            date_str = path.stem.replace("script_", "")
            file_date = datetime.strptime(date_str, "%Y-%m-%d")
            if file_date >= cutoff:
                scripts[date_str] = path.read_text(encoding="utf-8")
        except ValueError:
            continue
    logger.info("Found %d script(s) for vocab extraction", len(scripts))
    return scripts


# ── Term extraction via Claude ────────────────────────────────────────────────

def extract_terms(scripts: dict[str, str]) -> list[dict]:
    """Call Claude to extract AI/tech terms. Returns list of term dicts."""
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    parts = [f"[Script du {d}]\n{c}" for d, c in sorted(scripts.items())]
    combined = "\n\n".join(parts)

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=[{"type": "text", "text": EXTRACT_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        messages=[{
            "role": "user",
            "content": f"Extrais les termes techniques IA et tech de ces scripts :\n\n{combined}",
        }],
    )

    raw = response.content[0].text.strip()
    # Strip markdown code fences if Claude wraps the JSON
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    terms: list[dict] = json.loads(raw)
    logger.info("Extracted %d candidate term(s)", len(terms))
    return terms


# ── Google Sheets sync ────────────────────────────────────────────────────────

def _get_worksheet():
    """Return (or create) the 'Vocabulaire AI' worksheet."""
    import gspread
    from google.oauth2.service_account import Credentials

    creds = Credentials.from_service_account_file(str(CREDS_PATH), scopes=SCOPES)
    gc = gspread.authorize(creds)
    spreadsheet = gc.open_by_key(os.environ["GOOGLE_SHEET_ID"])

    try:
        ws = spreadsheet.worksheet(WORKSHEET_NAME)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(
            title=WORKSHEET_NAME, rows=1000, cols=len(SHEET_HEADERS)
        )
        ws.append_row(SHEET_HEADERS)
        logger.info("Created worksheet '%s' with headers", WORKSHEET_NAME)
    return ws


def _existing_terms(ws) -> set[str]:
    records = ws.get_all_records()
    return {r.get("Terme", "").lower().strip() for r in records if r.get("Terme")}


def sync_to_sheets(terms: list[dict]) -> tuple[list[dict], int]:
    """
    Add unseen terms to the Google Sheet.
    Returns (list_of_new_terms, total_row_count).
    """
    ws = _get_worksheet()
    existing = _existing_terms(ws)
    total_before = len(existing)

    new_terms: list[dict] = []
    rows_to_add: list[list] = []

    for term in terms:
        label = (term.get("terme_fr") or "").strip()
        if not label:
            continue
        if label.lower() in existing:
            logger.info("  skip (exists): %s", label)
            term["statut"] = "connu"
            continue

        rows_to_add.append([
            label,
            term.get("definition", ""),
            (term.get("contexte") or "")[:300],
            term.get("date", datetime.now().strftime("%Y-%m-%d")),
            "nouveau",
        ])
        existing.add(label.lower())
        term["statut"] = "nouveau"
        new_terms.append(term)
        logger.info("  added: %s", label)

    if rows_to_add:
        ws.append_rows(rows_to_add, value_input_option="USER_ENTERED")

    total_after = total_before + len(new_terms)
    logger.info("Sheet: +%d new / %d total", len(new_terms), total_after)
    return new_terms, total_after


# ── Digest email ──────────────────────────────────────────────────────────────

def _fmt_date(dt: datetime) -> str:
    return f"{dt.day} {MONTHS_FR[dt.strftime('%B')]} {dt.year}"


def send_vocab_email(new_terms: list[dict], total_count: int) -> None:
    gmail_user = os.environ["GMAIL_USER"]
    gmail_password = os.environ["GMAIL_APP_PASSWORD"]

    today = datetime.now()
    monday = today - timedelta(days=today.weekday())
    subject = f"Fiche vocabulaire IA -- semaine du {_fmt_date(monday)}"

    lines: list[str] = []

    # ── Section 1 ──
    lines.append("SECTION 1 — Nouveaux concepts cette semaine")
    lines.append("=" * 50)
    if new_terms:
        for t in new_terms:
            label = t["terme_fr"]
            if t.get("terme_en"):
                label += f"  ({t['terme_en']})"
            lines.append(f"\n{label}")
            lines.append(f"  Définition : {t.get('definition', '')}")
            ctx = t.get("contexte", "")
            if ctx:
                lines.append(f"  Contexte   : « {ctx} »")
    else:
        lines.append("\nAucun nouveau terme cette semaine.")

    # ── Section 2 ──
    lines.append("\n\nSECTION 2 — Pour aller plus loin")
    lines.append("=" * 50)
    if new_terms:
        for t in new_terms:
            query = t.get(
                "youtube_query",
                f"{t['terme_fr']} intelligence artificielle explication français",
            )
            lines.append(f"\n{t['terme_fr']}")
            lines.append(f"  Recherche YouTube : {query}")
    else:
        lines.append("\nAucun nouveau terme à explorer cette semaine.")

    # ── Section 3 ──
    lines.append("\n\nSECTION 3 — Ton glossaire")
    lines.append("=" * 50)
    lines.append(f"\nTotal : {total_count} terme(s) dans ton glossaire")
    lines.append(f"Nouveaux cette semaine : {len(new_terms)}")
    lines.append('\nGlossaire complet disponible sur Google Sheets : "Vocabulaire AI"')

    body = "\n".join(lines)

    msg = MIMEMultipart()
    msg["From"] = gmail_user
    msg["To"] = RECIPIENT
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
        server.login(gmail_user, gmail_password)
        server.sendmail(gmail_user, RECIPIENT, msg.as_string())

    logger.info("Vocab email sent: '%s' to %s", subject, RECIPIENT)


# ── Orchestration ─────────────────────────────────────────────────────────────

def run() -> None:
    logger.info("=== Vocabulary Tracker ===")

    scripts = find_recent_scripts(days=7)
    if not scripts:
        logger.warning("No scripts found in the past 7 days -- aborting")
        return

    # Extract terms via Claude
    try:
        terms = extract_terms(scripts)
    except Exception as exc:
        logger.error("Term extraction failed: %s", exc)
        return

    if not terms:
        logger.info("No qualifying AI/tech terms found this week")
        send_vocab_email([], 0)
        return

    # Sync to Google Sheets
    sheets_available = (
        CREDS_PATH.exists()
        and os.environ.get("GOOGLE_SHEET_ID", "").strip()
    )

    if sheets_available:
        try:
            new_terms, total = sync_to_sheets(terms)
        except Exception as exc:
            logger.error("Google Sheets sync failed: %s", exc)
            logger.warning("Falling back to email-only mode (all extracted terms treated as new)")
            new_terms = [t | {"statut": "nouveau"} for t in terms]
            total = len(new_terms)
    else:
        logger.warning(
            "Google Sheets not configured (missing credentials or GOOGLE_SHEET_ID). "
            "See README.md -- sending email with all extracted terms."
        )
        new_terms = [t | {"statut": "nouveau"} for t in terms]
        total = len(new_terms)

    send_vocab_email(new_terms, total)
    logger.info("=== Done ===")


if __name__ == "__main__":
    run()
