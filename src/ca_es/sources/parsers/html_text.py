"""Extraccion determinista de texto y anclas desde documentos HTML.

No interpreta: convierte bytes a texto normalizado y permite localizar
fragmentos exactos (ancla) para que la provenance apunte a un fragmento
verificable del documento real.
"""
from __future__ import annotations

import html
import re

_ENCODINGS = ("utf-8", "cp1252", "latin-1")


def decode(payload: bytes) -> str:
    for encoding in _ENCODINGS:
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    return payload.decode("utf-8", errors="replace")


def html_to_text(raw_html: str) -> str:
    text = re.sub(r"(?is)<script.*?</script>|<style.*?</style>", " ", raw_html)
    text = re.sub(r"(?is)<br\s*/?>|</p>|</div>|</tr>|</li>|</h[1-6]>", "\n", text)
    text = re.sub(r"(?s)<[^>]+>", "", text)
    text = html.unescape(text)
    lines = [re.sub(r"[ \t\u00a0]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def anchor(
    text: str, pattern: str, *, group: int = 1, flags: int = 0
) -> dict | None:
    match = re.search(pattern, text, flags)
    if match is None:
        return None
    try:
        value = match.group(group)
    except IndexError:
        value = match.group(0)
    return {
        "value": value,
        "matched": match.group(0),
        "offset": match.start(),
        "pattern": pattern,
    }


_MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10, "noviembre": 11,
    "diciembre": 12,
}


def spanish_date_to_iso(value: str) -> str | None:
    match = re.match(r"(\d{1,2}) de (\w+) de (\d{4})", value.strip())
    if not match:
        return None
    day, month_name, year = match.groups()
    month = _MONTHS.get(month_name.lower())
    if month is None:
        return None
    return f"{int(year):04d}-{month:02d}-{int(day):02d}"
