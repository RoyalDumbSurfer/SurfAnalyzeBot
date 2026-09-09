"""Small request-local catalog. English source strings are stable message keys."""
import json
from pathlib import Path

from jinja2 import pass_context

SUPPORTED_LANGUAGES = ("ru", "en")
CATALOGS = {"ru": json.loads((Path(__file__).parent / "locales" / "ru.json").read_text(encoding="utf-8"))}


def language(request):
    selected = request.cookies.get("surfanalyze_language", "ru")
    return selected if selected in SUPPORTED_LANGUAGES else "ru"


def translate(request, message, **values):
    translated = CATALOGS.get(language(request), {}).get(message, message)
    return translated.format(**values) if values else translated


@pass_context
def template_translate(context, message, **values):
    return translate(context["request"], message, **values)
