"""Hebrew text normalization and query building for SQLite FTS5 (unicode61 tokenizer).

Design notes
- Gershayim inside abbreviations (תכ"ם, תכ''ם, תכ״ם) are removed, otherwise the
  tokenizer splits the word into two meaningless tokens.
- Prefix letters (ו/ה/ב/ל/מ/ש/כ) are never cut from the original word. Instead
  the stripped forms are indexed in a separate, lower-weighted column and added
  to queries as OR alternatives. Rule-based cutting alone would destroy words
  such as "משרד" -> "שרד"; as an alternative it only adds low-weight recall.
"""

from __future__ import annotations

import re

HEB = "א-ת"
_NIQQUD = re.compile("[֑-ׇ]")
# '' must come before ' so that double apostrophes are removed as one unit.
_GERSHAYIM = re.compile(rf"(?<=[{HEB}])(?:''|\"|״|׳|'|’|”)(?=[{HEB}])")
_TOKEN = re.compile(rf"[{HEB}A-Za-z0-9]+")

PREFIX_LETTERS = set("ובהלמשכ")
MIN_STEM = 3
MAX_PREFIX = 2
MAX_QUERY_TOKENS = 30

STOPWORDS = {
    "האם", "מה", "מהו", "מהי", "מי", "איך", "כיצד", "מתי", "למה", "מדוע", "כמה", "איפה", "היכן",
    "של", "את", "על", "עם", "אל", "או", "גם", "כי", "אם", "לא", "יש", "אין", "זה", "זו", "זאת",
    "הוא", "היא", "הם", "הן", "אני", "אנחנו", "אפשר", "ניתן", "צריך", "צריכה", "צריכים", "חייב",
    "לפי", "בין", "כל", "רק", "עד", "אחרי", "לפני", "מן", "כן", "יותר", "פחות", "אותו", "אותה",
    "שלי", "שלו", "שלה", "לגבי", "בנושא", "עליי", "לעשות", "עושים", "קורה",
}


def normalize(text: str) -> str:
    text = _NIQQUD.sub("", text)
    text = _GERSHAYIM.sub("", text)
    return text.lower()


def tokens(text: str) -> list[str]:
    return _TOKEN.findall(normalize(text))


def _is_hebrew(token: str) -> bool:
    return bool(re.fullmatch(rf"[{HEB}]+", token))


def prefix_variants(token: str) -> list[str]:
    """Forms of `token` with 1-2 leading prefix letters removed (never the token itself)."""
    if not _is_hebrew(token):
        return []
    out = []
    for i in range(1, MAX_PREFIX + 1):
        if len(token) - i < MIN_STEM:
            break
        if token[i - 1] not in PREFIX_LETTERS:
            break
        out.append(token[i:])
    return out


def variants_text(text: str) -> str:
    """Text for the low-weight 'variants' index column."""
    return " ".join(v for t in tokens(text) for v in prefix_variants(t))


def query_terms(query: str) -> list[str]:
    toks = tokens(query)[:MAX_QUERY_TOKENS]
    content = [t for t in toks if t not in STOPWORDS]
    return content or toks


def build_match_query(query: str) -> str | None:
    """FTS5 MATCH expression: OR over terms, each term OR-ed with its prefix variants.

    OR (not AND) because users type questions, not exact keywords; BM25 ranks
    documents matching more and rarer terms higher. Every alternative is quoted,
    so FTS5 operators typed by the user (AND, NEAR, *, ") cannot break the query.
    """
    terms = query_terms(query)
    if not terms:
        return None
    groups = []
    seen: set[str] = set()
    for term in terms:
        alts = [a for a in [term, *prefix_variants(term)] if a not in seen]
        seen.update(alts)
        if alts:
            groups.append("(" + " OR ".join(f'"{a}"' for a in alts) + ")")
    return " OR ".join(groups) if groups else None


def build_phrase_query(query: str) -> str | None:
    """FTS5 MATCH over adjacent term pairs as exact phrases ("חתימה דיגיטלית").

    The OR query ranks by individual words, so common words ("חתימה" appears in
    hundreds of chunks) can outrank the one chunk where the user's phrase actually
    appears. Chunks matching a phrase are ranked first. Both words may appear with
    or without their prefix letters ("בחתימה דיגיטלית" also matches).
    """
    terms = query_terms(query)
    if len(terms) < 2:
        return None
    phrases: list[str] = []
    for a, b in zip(terms, terms[1:]):
        for fa in [a, *prefix_variants(a)]:
            for fb in [b, *prefix_variants(b)]:
                phrase = f'"{fa} {fb}"'
                if phrase not in phrases:
                    phrases.append(phrase)
    return "body : (" + " OR ".join(phrases) + ")"
