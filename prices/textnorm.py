"""Forgiving text normalisation used for product search.

normalize_text("Mol Go'shti") == normalize_text("MOLGʻOSHTI") == normalize_text("мол гўшти") == "molgoshti"

What it forgives: upper/lower case, spaces and punctuation anywhere, every apostrophe style
(' ʻ ʼ ‘ ’ ` ´), accents, and Cyrillic (Uzbek/Russian) typed instead of Latin.
Python's str.lower() handles Unicode; SQLite's LIKE does not (ASCII only) - that is why we
search a pre-normalised column instead of relying on `icontains` over the raw name.
"""
import re
import unicodedata

_CYR = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo", "ж": "j", "з": "z",
    "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
    "с": "s", "т": "t", "у": "u", "ф": "f", "х": "x", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sh",
    "ъ": "", "ы": "i", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    "ў": "o", "қ": "q", "ғ": "g", "ҳ": "h",
}
_NON_ALNUM = re.compile(r"[\W_]+", re.UNICODE)


def normalize_text(value):
    if not value:
        return ""
    text = unicodedata.normalize("NFKD", str(value)).casefold()
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = "".join(_CYR.get(ch, ch) for ch in text)
    return _NON_ALNUM.sub("", text)  # drops spaces, apostrophes, hyphens, punctuation


def search_tokens(query):
    """Split a raw query on whitespace and normalise each word; empty words are dropped."""
    return [t for t in (normalize_text(w) for w in str(query or "").split()) if t]
