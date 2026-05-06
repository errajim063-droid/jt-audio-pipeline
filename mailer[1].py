"""Email sender — Gmail SMTP with MP3 attachment and per-segment article digest."""
import logging
import os
import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

RECIPIENT = "errajim063@gmail.com"
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465

DAYS_FR = {
    "Monday": "Lundi", "Tuesday": "Mardi", "Wednesday": "Mercredi",
    "Thursday": "Jeudi", "Friday": "Vendredi", "Saturday": "Samedi",
    "Sunday": "Dimanche",
}
MONTHS_FR = {
    "January": "janvier", "February": "février", "March": "mars",
    "April": "avril", "May": "mai", "June": "juin",
    "July": "juillet", "August": "août", "September": "septembre",
    "October": "octobre", "November": "novembre", "December": "décembre",
}
SEGMENT_LABELS = {
    "ia_tech_maroc": "Segment 1 — IA & Tech Maroc",
    "ia_tech_international": "Segment 2 — IA & Tech International",
    "casablanca": "Segment 3 — Casablanca & région Casa-Settat",
    "nationales": "Segment 4 — Grandes lignes nationales",
}


def _subject(dt: datetime) -> str:
    day = DAYS_FR[dt.strftime("%A")]
    month = MONTHS_FR[dt.strftime("%B")]
    return f"JT – {day} {dt.day} {month} {dt.year}"


def _body(segments: Dict[str, List], fallback: bool) -> str:
    lines = []
    if fallback:
        lines.append(
            "⚠️  Génération audio indisponible aujourd'hui.\n"
            "Voici la liste complète des articles sélectionnés :\n"
        )
    else:
        lines.append("Votre bulletin audio du jour est en pièce jointe.\n")

    for seg_key, label in SEGMENT_LABELS.items():
        arts = segments.get(seg_key, [])
        if not arts:
            continue
        lines.append(f"\n{label}")
        lines.append("─" * len(label))
        for art in arts:
            snippet = art.get("summary", "")[:140].strip()
            if snippet and not snippet.endswith((".", "…")):
                snippet += "…"
            lines.append(
                f"• {art['title']} — {art['source']} — {art['url']}"
                + (f"\n  {snippet}" if snippet else "")
            )

    lines.append(
        "\n\nBonne écoute.\n"
        "Script complet disponible dans ~/jt_audio/"
    )
    return "\n".join(lines)


def send_email(
    segments: Dict[str, List],
    mp3_path: Optional[Path] = None,
    fallback: bool = False,
):
    """Send the daily briefing. Attaches MP3 if the file exists."""
    gmail_user = os.environ["GMAIL_USER"]
    gmail_password = os.environ["GMAIL_APP_PASSWORD"]

    now = datetime.now()
    subject = _subject(now)
    body = _body(segments, fallback=fallback)

    msg = MIMEMultipart()
    msg["From"] = gmail_user
    msg["To"] = RECIPIENT
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    if mp3_path and mp3_path.exists():
        with open(mp3_path, "rb") as fh:
            part = MIMEBase("audio", "mpeg")
            part.set_payload(fh.read())
        encoders.encode_base64(part)
        part.add_header(
            "Content-Disposition",
            f'attachment; filename="{mp3_path.name}"',
        )
        msg.attach(part)
        logger.info("MP3 attached: %s (%.1f MB)", mp3_path.name,
                    mp3_path.stat().st_size / 1_048_576)
    else:
        logger.warning("No MP3 attached — sending text-only email")

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
        server.login(gmail_user, gmail_password)
        server.sendmail(gmail_user, RECIPIENT, msg.as_string())

    logger.info("Email sent: '%s' to %s", subject, RECIPIENT)
