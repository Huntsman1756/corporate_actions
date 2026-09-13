from __future__ import annotations

from ca_es.sources.parsers.html_text import (
    anchor,
    decode,
    html_to_text,
    spanish_date_to_iso,
)


def test_html_to_text_strips_tags_and_unescapes():
    raw = "<html><body><p>Hola&nbsp;<b>mundo</b></p><script>x=1</script></body></html>"
    assert html_to_text(raw) == "Hola mundo"


def test_decode_prefers_utf8():
    assert decode("precio 0,80 €".encode("utf-8")) == "precio 0,80 €"


def test_anchor_returns_exact_snippet():
    text = "El tipo unitario de emisión es de 0,80 euros por acción."
    found = anchor(text, r"tipo unitario de emisión es de ([\d.]+(?:,\d+)?) euros")
    assert found is not None
    assert found["value"] == "0,80"
    assert found["matched"].startswith("tipo unitario")


def test_anchor_without_group_falls_back_to_match():
    found = anchor("abc DEF", r"[A-Z]+", group=1)
    assert found["value"] == "DEF"


def test_spanish_date_to_iso():
    assert spanish_date_to_iso("8 de septiembre de 2026") == "2026-09-08"
    assert spanish_date_to_iso("basura") is None
