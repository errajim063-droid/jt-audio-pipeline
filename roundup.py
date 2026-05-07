#!/usr/bin/env python3
"""Weekly roundup generator.

Reads the past 7 days of script_*.txt files, asks Claude to produce a
~500-word structured summary in French, saves it, and emails it.

Usage : python roundup.py
Output: ~/jt_audio/roundup_YYYY-WXX.txt  +  text email
"""
import logging
import os
import smtplib
import sys
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

OUTPUT_DIR = Path.home() / "jt_audio"
RECIPIENT = "errajim063@gmail.com"
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s -- %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("roundup")

MONTHS_FR = {
    "January": "janvier", "February": "février", "March": "mars",
    "April": "avril", "May": "mai", "June": "juin",
    "July": "juillet", "August": "août", "September": "septembre",
    "October": "octobre", "November": "novembre", "December": "décembre",
}
DAYS_FR = {
    "Monday": "lundi", "Tuesday": "mardi", "Wednesday": "mercredi",
    "Thursday": "jeudi", "Friday": "vendredi", "Saturday": "samedi",
    "Sunday": "dimanche",
}

SYSTEM_PROMPT = """\
Tu es un journaliste radio professionnel. Tu rédiges des récapitulatifs hebdomadaires en français.

STYLE : neutre, factuel, structuré. Phrases courtes. Aucune opinion. Pas de sensationnalisme.

TÂCHE : tu reçois plusieurs bulletins radio de la semaine écoulée. Produis un récapitulatif
structuré en 4 sections correspondant aux 4 segments habituels du JT :

1. IA & Tech Maroc
2. IA & Tech International
3. Casablanca & région Casa-Settat
4. Grandes lignes nationales

Pour chaque section :
- Présente les faits marquants de la semaine (2 à 4 points).
- Si un sujet est apparu plusieurs fois, garde la mention la plus complète et ne le cite qu'une seule fois.
- 1 à 2 phrases par point.

Cible : environ 500 mots au total.
Ne commence pas par une méta-introduction. Commence directement par la première section.\
"""


def _fmt_date(dt: datetime) -> str:
    return f"{dt.day} {MONTHS_FR[dt.strftime('%B')]} {dt.year}"


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
    logger.info("Found %d script(s) in the past %d days", len(scripts), days)
    return scripts


def generate_roundup(scripts: dict[str, str]) -> str:
    """Call Claude to produce the weekly summary."""
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    today = datetime.now()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    week_label = f"{_fmt_date(monday)} au {_fmt_date(sunday)}"

    parts = []
    for date_str, content in sorted(scripts.items()):
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        day_fr = DAYS_FR[dt.strftime("%A")].capitalize()
        parts.append(f"=== Bulletin du {day_fr} {_fmt_date(dt)} ===\n\n{content}")
    combined = "\n\n".join(parts)

    user_msg = (
        f"Voici les bulletins radio de la semaine du {week_label}.\n\n"
        f"Génère le récapitulatif hebdomadaire structuré en 4 sections.\n\n"
        f"{combined}"
    )

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_msg}],
    )

    text = response.content[0].text
    logger.info("Roundup generated: %d words", len(text.split()))
    return text


def save_roundup(text: str) -> Path:
    iso_year, iso_week, _ = datetime.now().isocalendar()
    path = OUTPUT_DIR / f"roundup_{iso_year}-W{iso_week:02d}.txt"
    path.write_text(text, encoding="utf-8")
    logger.info("Saved: %s", path)
    return path


def send_roundup_email(text: str) -> None:
    gmail_user = os.environ["GMAIL_USER"]
    gmail_password = os.environ["GMAIL_APP_PASSWORD"]

    today = datetime.now()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    subject = f"Recap semaine -- {_fmt_date(monday)} au {_fmt_date(sunday)}"

    msg = MIMEMultipart()
    msg["From"] = gmail_user
    msg["To"] = RECIPIENT
    msg["Subject"] = subject
    msg.attach(MIMEText(text, "plain", "utf-8"))

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
        server.login(gmail_user, gmail_password)
        server.sendmail(gmail_user, RECIPIENT, msg.as_string())

    logger.info("Email sent: '%s' to %s", subject, RECIPIENT)


def run() -> None:
    logger.info("=== Weekly Roundup ===")

    scripts = find_recent_scripts(days=7)
    if not scripts:
        logger.warning("No scripts found in the past 7 days -- aborting")
        return

    roundup_text = generate_roundup(scripts)
    save_roundup(roundup_text)
    send_roundup_email(roundup_text)

    logger.info("=== Done ===")


if __name__ == "__main__":
    run()
