"""TTS converter — turns the French radio script into an MP3 via gTTS."""
import logging
import re
import tempfile
from pathlib import Path
from typing import List

from gtts import gTTS

logger = logging.getLogger(__name__)

OUTPUT_DIR = Path.home() / "jt_audio"
CHUNK_CHAR_LIMIT = 4000  # gTTS is reliable up to ~5 000 chars; stay safe


def _clean_for_tts(text: str) -> str:
    """Strip markdown, URLs, and TTS-unfriendly characters."""
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"[*_`~]{1,3}", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"[^\w\s.,;:!?'«»\"()%-]", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r" {2,}", " ", text)
    return text.strip()


def _split_into_chunks(text: str, limit: int = CHUNK_CHAR_LIMIT) -> List[str]:
    """Split text at paragraph boundaries to stay within gTTS limits."""
    paragraphs = [p.strip() for p in re.split(r"\n\n+", text) if p.strip()]
    chunks, current = [], ""
    for para in paragraphs:
        if len(current) + len(para) + 2 <= limit:
            current = (current + "\n\n" + para).lstrip()
        else:
            if current:
                chunks.append(current)
            # Paragraph itself exceeds limit — split by sentence
            if len(para) > limit:
                sentences = re.split(r"(?<=[.!?])\s+", para)
                current = ""
                for sent in sentences:
                    if len(current) + len(sent) + 1 <= limit:
                        current = (current + " " + sent).lstrip()
                    else:
                        if current:
                            chunks.append(current)
                        current = sent
            else:
                current = para
    if current:
        chunks.append(current)
    return chunks


def _tts_single(text: str, path: Path):
    """Convert text to MP3 (single chunk, no pydub needed)."""
    gTTS(text=text, lang="fr", slow=False).save(str(path))


def _tts_chunked(chunks: List[str], path: Path):
    """Convert multiple chunks, concatenate with pydub."""
    from pydub import AudioSegment  # lazy — not available on Python 3.14+

    combined = AudioSegment.empty()
    silence = AudioSegment.silent(duration=600)  # 0.6 s pause between chunks

    with tempfile.TemporaryDirectory() as tmp:
        for i, chunk in enumerate(chunks):
            chunk_path = Path(tmp) / f"chunk_{i:03d}.mp3"
            gTTS(text=chunk, lang="fr", slow=False).save(str(chunk_path))
            combined += AudioSegment.from_mp3(str(chunk_path)) + silence

    combined.export(str(path), format="mp3")


def text_to_audio(script: str, date_str: str) -> Path:
    """Convert the radio script to MP3, save to ~/jt_audio/jt_YYYY-MM-DD.mp3."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    mp3_path = OUTPUT_DIR / f"jt_{date_str}.mp3"

    clean = _clean_for_tts(script)
    logger.info("Cleaned script: %d chars for TTS", len(clean))

    if len(clean) <= CHUNK_CHAR_LIMIT:
        _tts_single(clean, mp3_path)
    else:
        chunks = _split_into_chunks(clean)
        logger.info("Script split into %d chunks for gTTS", len(chunks))
        try:
            _tts_chunked(chunks, mp3_path)
        except ImportError:
            # pydub not available — concatenate text and send as one call (may truncate)
            logger.warning("pydub not installed; sending full text in one gTTS call")
            _tts_single(clean[:CHUNK_CHAR_LIMIT * 3], mp3_path)

    size_mb = mp3_path.stat().st_size / 1_048_576
    logger.info("Audio saved: %s (%.1f MB)", mp3_path, size_mb)
    return mp3_path


def save_script(script: str, date_str: str) -> Path:
    """Save the raw script to ~/jt_audio/script_YYYY-MM-DD.txt."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    txt_path = OUTPUT_DIR / f"script_{date_str}.txt"
    txt_path.write_text(script, encoding="utf-8")
    logger.info("Script saved: %s", txt_path)
    return txt_path
