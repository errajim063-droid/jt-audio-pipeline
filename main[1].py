#!/usr/bin/env python3
"""JT Radio Pipeline — daily orchestrator.

Run order: fetcher → processor → audio → mailer
Fallback email sent automatically if any step fails.
"""
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the same directory as this script
load_dotenv(Path(__file__).parent / ".env")

from fetcher import fetch_all_segments
from processor import generate_script
from audio import save_script, text_to_audio
from mailer import send_email

OUTPUT_DIR = Path.home() / "jt_audio"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("main")


def run() -> None:
    start = time.monotonic()
    date_str = datetime.now().strftime("%Y-%m-%d")
    logger.info("=" * 42)
    logger.info("JT Pipeline -- %s", date_str)
    logger.info("=" * 42)

    # ── Step 1 : Fetch ──────────────────────────────────────────────────────────
    logger.info("[1/4] Fetching RSS feeds...")
    try:
        segments = fetch_all_segments()
    except Exception as exc:
        logger.error("Fetch failed: %s — aborting", exc)
        send_email({}, mp3_path=None, fallback=True)
        return

    total = sum(len(v) for v in segments.values())
    if total == 0:
        logger.error("No articles fetched — sending fallback email")
        send_email(segments, mp3_path=None, fallback=True)
        return

    empty = [k for k, v in segments.items() if not v]
    for seg in empty:
        logger.warning("Segment '%s' has 0 articles -- will be skipped in script", seg)

    # ── Step 2 : Generate script ────────────────────────────────────────────────
    logger.info("[2/4] Generating radio script via Claude API...")
    script: str | None = None
    try:
        script = generate_script(segments)
        save_script(script, date_str)
    except Exception as exc:
        logger.error("Script generation failed: %s — sending fallback email", exc)
        send_email(segments, mp3_path=None, fallback=True)
        return

    # ── Step 3 : TTS audio ──────────────────────────────────────────────────────
    logger.info("[3/4] Converting script to audio (gTTS)...")
    mp3_path = None
    try:
        mp3_path = text_to_audio(script, date_str)
        if not mp3_path.exists():
            raise FileNotFoundError(f"MP3 not found after TTS: {mp3_path}")
    except Exception as exc:
        logger.error("Audio generation failed: %s — sending email without MP3", exc)
        send_email(segments, mp3_path=None, fallback=False)
        return

    # ── Step 4 : Send email ─────────────────────────────────────────────────────
    logger.info("[4/4] Sending email...")
    try:
        send_email(segments, mp3_path=mp3_path, fallback=False)
    except Exception as exc:
        logger.error("Email sending failed: %s", exc)

    elapsed = time.monotonic() - start
    logger.info("=" * 42)
    logger.info("Pipeline complete in %.0f s", elapsed)
    logger.info("=" * 42)


if __name__ == "__main__":
    run()
