"""Script generator — calls Claude API to produce a 4-segment French radio bulletin."""
import logging
import os
from datetime import datetime
from typing import Dict, List

import anthropic

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = """\
Tu es un journaliste radio professionnel. Tu rédiges des bulletins d'information audio en français pour la radio.

STYLE :
- Neutre, factuel, direct. Zéro opinion personnelle. Zéro sensationnalisme.
- Phrases courtes (15 mots maximum). Vocabulaire clair, accessible.
- Le texte sera lu à voix haute : aucun symbole, aucune URL, aucune abréviation obscure.
- Évite les titres en majuscules et les caractères spéciaux.

STRUCTURE pour chaque segment :
1. Une phrase d'introduction du segment (annonce le thème).
2. Un paragraphe par article (3 à 4 phrases maximum) : présente le fait, son contexte immédiat, son importance.
3. Une phrase de transition naturelle entre chaque article.
4. Une phrase de clôture neutre en fin de segment.

CONTRAINTES :
- Couvre chaque article fourni dans son segment, sans en omettre.
- Cible globale : environ 4 500 mots pour les 4 segments réunis.
- Ne mentionne pas les URLs dans le texte lu.
- Ne commence pas par une méta-introduction (pas de "Voici votre bulletin…").
- Commence directement par le premier segment.\
"""

SEGMENT_LABELS = {
    "ia_tech_maroc": "SEGMENT 1 — IA & TECH MAROC",
    "ia_tech_international": "SEGMENT 2 — IA & TECH INTERNATIONAL",
    "casablanca": "SEGMENT 3 — CASABLANCA & RÉGION CASA-SETTAT",
    "nationales": "SEGMENT 4 — GRANDES LIGNES NATIONALES",
}


def _format_context(segments: Dict[str, List]) -> str:
    today = datetime.now().strftime("%A %d %B %Y")
    lines = [f"Date du bulletin : {today}\n"]

    for seg_key, label in SEGMENT_LABELS.items():
        articles = segments.get(seg_key, [])
        if not articles:
            continue
        lines.append(f"### {label}")
        for i, art in enumerate(articles, 1):
            lines.append(f"{i}. Titre    : {art['title']}")
            lines.append(f"   Source   : {art['source']}")
            lines.append(f"   Résumé   : {art['summary']}")
            lines.append(f"   URL      : {art['url']}")
            lines.append("")
        lines.append("")

    return "\n".join(lines)


def generate_script(segments: Dict[str, List]) -> str:
    """Call Claude to generate the full radio script. Uses prompt caching on system prompt."""
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    context = _format_context(segments)

    active_segments = [k for k, v in segments.items() if v]
    segment_list = ", ".join(SEGMENT_LABELS[k] for k in active_segments)

    user_message = (
        f"Rédige le bulletin radio d'aujourd'hui. "
        f"Segments à couvrir : {segment_list}.\n\n"
        f"Articles sources :\n\n{context}"
    )

    response = client.messages.create(
        model=MODEL,
        max_tokens=8192,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_message}],
    )

    script = response.content[0].text
    word_count = len(script.split())
    logger.info(
        "Script generated: %d words, %d chars | cache read=%s write=%s",
        word_count,
        len(script),
        getattr(response.usage, "cache_read_input_tokens", "n/a"),
        getattr(response.usage, "cache_creation_input_tokens", "n/a"),
    )
    return script
