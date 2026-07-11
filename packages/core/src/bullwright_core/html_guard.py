"""Raw-HTML rejection for markdown fields (API security rule S5).

Report prose is markdown; embedded HTML is rejected at the API boundary so
nothing HTML-shaped ever reaches the blog build. The pattern is deliberately
conservative: it matches real tags (`<div>`, `</p>`, `<script ...>`,
`<!-- -->`) but not math like "x < 5" or "a <- b".
"""

import re

_TAG_RE = re.compile(r"</?[a-zA-Z][a-zA-Z0-9-]*(\s[^<>]*)?/?>|<!--")
# C0 control chars except \t \n \r; NUL in particular breaks Postgres text.
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def contains_raw_html(text: str) -> bool:
    return _TAG_RE.search(text) is not None


def contains_control_chars(text: str) -> bool:
    return _CONTROL_RE.search(text) is not None


def assert_no_raw_html(field: str, text: str) -> None:
    if contains_raw_html(text):
        raise ValueError(f"{field}: raw HTML is not allowed in markdown fields")
    if contains_control_chars(text):
        raise ValueError(f"{field}: control characters are not allowed")
