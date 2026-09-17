"""Extraccion generica de fechas etiquetadas en avisos de corporate actions.

Cubre las variantes observadas en CNMV y Portfolio Stock Exchange:

- Etiquetas en ingles o espanol: ``Ex-Date``, ``record date``,
  ``payment date``, ``fecha de pago``, ``fecha valor``, ``fecha devengo``,
  ``last trading date``, ``ultimo dia de negociacion``...
- Fechas en formato numerico (``03/07/2026``, ``03 / 07 / 2026``) o
  espanol (``22 de julio de 2026``, ``se concreta en el dia 23 de junio de
  2025``).

Cada fecha promovida conserva el fragmento que la justifica; la funcion
devuelve el lexema y el offset para que el parser construya la evidencia.
"""
from __future__ import annotations

import re

from .html_text import spanish_date_to_iso

_NUMERIC = r"\d{1,2}\s*/\s*\d{1,2}\s*/\s*\d{4}"
_SPANISH = r"\d{1,2}\s+de\s+\w+\s+de\s+\d{4}"
ANY_DATE = rf"(?:{_NUMERIC}|{_SPANISH})"

# (patron, es_nombre_de_campo): los nombres de campo pueden aparecer como
# referencia descriptiva ("en la fecha de pago") y requieren el filtro de
# prefijo; las frases de contexto ("los titulares inscritos") no.
_LABELS: dict[str, tuple[tuple[str, bool], ...]] = {
    "EX_DATE": (
        (r"\bex\s*[-–—]?\s*date\b", True),
        (r"\bexdate\b", True),
        (r"negociar[aá]n?\s+sin\s+derecho", False),
    ),
    "RECORD_DATE": (
        (r"\brecord\s*[-–—]?\s*date\b", True),
        (r"fecha\s+de\s+registro\b", True),
        (r"titulares\s+inscritos", False),
    ),
    "PAYMENT_DATE": (
        (r"\bpayment\s*[-–—]?\s*date\b", True),
        (r"fecha\s+de\s+pago\b", True),
        (r"fecha\s+valor\b", True),
    ),
    "LAST_TRADING_DATE": (
        (r"\blast\s+trading\s+date\b", True),
        (r"[uú]ltim[ao]\s+(?:d[ií]a|fecha)\s+de\s+(?:negociaci[oó]n|contrataci[oó]n)", False),
    ),
}


def _to_iso(lexeme: str) -> str | None:
    lexeme = re.sub(r"\s+", " ", lexeme.strip())
    numeric = re.match(r"(\d{1,2})\s*/\s*(\d{1,2})\s*/\s*(\d{4})", lexeme)
    if numeric:
        day, month, year = numeric.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}"
    return spanish_date_to_iso(lexeme)


# Uso descriptivo de la etiqueta ("en la fecha de pago", "la fecha de
# reparto"): cuando el nombre del campo se menciona como concepto y no
# introduce un valor, la siguiente fecha del documento no le pertenece.
_DESCRIPTIVE_PREFIX = re.compile(
    r"\b(?:en|a|de|desde|por|para|hasta|del|la|el|los|las)"
    r"\s+(?:la\s+|el\s+)?$",
    re.I,
)


_FIELD_NAME_PATTERNS = tuple(
    pattern
    for entries in _LABELS.values()
    for pattern, is_field_name in entries
    if is_field_name
)
_ANY_FIELD_NAME = re.compile("|".join(_FIELD_NAME_PATTERNS), re.I)


def find_labeled_date(text: str, date_kind: str) -> dict | None:
    """Primera fecha publicada tras una etiqueta del tipo pedido.

    - Se prueban todas las ocurrencias de cada etiqueta (la primera puede
      ser una mencion delegada sin fecha, p.ej. "(payment date)").
    - El hueco de hasta 220 caracteres permite la forma "Fecha de pago:
      25 dias siguientes ... (se concreta en el dia 23 de junio de 2025)".
    - Una etiqueta precedida de articulo o preposicion ("en la fecha de
      pago", "comunicara la fecha de reparto") se considera referencia
      descriptiva y se descarta: promoveria una fecha ajena al campo.
    """
    for label, is_field_name in _LABELS.get(date_kind, ()):
        for label_match in re.finditer(label, text, re.I):
            if is_field_name and _DESCRIPTIVE_PREFIX.search(
                text[max(0, label_match.start() - 12):label_match.start()]
            ):
                continue
            window = text[label_match.end():label_match.end() + _BIND_WINDOW]
            date_match = re.search(ANY_DATE, window)
            if not date_match:
                continue
            # La fecha pertenece a esta etiqueta solo si no hay otra
            # etiqueta de campo interpuesta ("record date: X" entre
            # "ex date" y la fecha significaria captura cruzada).
            if _ANY_FIELD_NAME.search(window[: date_match.start()]):
                continue
            iso = _to_iso(date_match.group(0))
            if iso:
                matched = text[label_match.start():label_match.end() + date_match.end()]
                return {
                    "value": date_match.group(0),
                    "iso": iso,
                    "matched": matched,
                    "offset": label_match.start(),
                }
    return None


# --- Ligadura rol <-> fecha -------------------------------------------
#
# Los avisos publican varias fechas etiquetadas en el mismo parrafo o en
# bullets ("14 de mayo. ... cotizan 'ex-cupon' (ex date)"), con la fecha
# antes o despues de la etiqueta. La ligadura ingenua "primera fecha tras
# la etiqueta" captura la fecha del rol adyacente (record como ex, fin de
# plazo como ex). La ligadura correcta exige:
#
#   1. candidatos a ambos lados de la etiqueta (la fecha puede preceder
#      al nombre del rol: "el 16 de abril el ex-date");
#   2. una fecha esta "claimed" por la etiqueta de rol mas cercana a
#      ella; otra etiqueta no puede ligarla;
#   3. el par gana por predicado del rol en el span etiqueta<->fecha
#      ("cotizaran ex-dividendo a partir del", "registros de Iberclear")
#      y por proximidad.

_BIND_WINDOW = 240

_BIND_LABELS: dict[str, tuple[str, ...]] = {
    "EX_DATE": (
        r"\bex\s*[-–—]?\s*date\b",
        r"\bexdate\b",
        r"\bex\s*[-–—]?\s*dividendo\b",
        r"\bex\s*[-–—]?\s*cup[oó]n\b",
        r"negociar[aá]n?\s+sin\s+derecho",
    ),
    "RECORD_DATE": (
        r"\brecord\s*[-–—]?\s*date\b",
        r"fecha\s+de\s+registro",
        r"fecha\s+de\s+corte",
        r"titulares\s+inscritos",
        r"registros\s+de\s+iberclear",
    ),
    "PAYMENT_DATE": (
        r"\bpayment\s*[-–—]?\s*date\b",
        r"fecha\s+de\s+pago\b",
        r"fecha\s+valor\b",
    ),
}

_ROLE_PREDICATES: dict[str, re.Pattern] = {
    "EX_DATE": re.compile(
        r"cotiz|negoci|sin derecho|a partir|será|ser[íi]a|es el"
        r"|desde la cual",
        re.I,
    ),
    "RECORD_DATE": re.compile(
        r"registro|record|legitimad|inscrit|titulares|corte|figuren"
        r"|será|ser[íi]a|ser[aá]n?|corresponde|fijad",
        re.I,
    ),
    "PAYMENT_DATE": re.compile(
        r"pag|abono|liquida|tenga lugar|fecha valor|efectiv"
        r"|será|corresponde",
        re.I,
    ),
}


# Lexemas de fecha candidatos: con anio (DD/MM/YYYY o "D de mes de
# YYYY") o sin anio ("30 de abril"); los segundos promueven solo como
# DERIVED_BY_DEFINITION con el anio de la fecha de pago.
_CANDIDATE_DATE = re.compile(rf"{_NUMERIC}|{_SPANISH}|\d{{1,2}}\s+de\s+\w+")

# Sintaxis campo:valor tras la etiqueta ("Record date: 12 de agosto",
# "fecha ex date el 11"): la fecha inmediatamente posterior separada
# solo por dos puntos/articulo es el valor del campo.
_LABEL_VALUE = re.compile(
    r"^[\s:：\-–—]*(?:el|del|de|a partir del|el d[ií]a|ser[aá]"
    r"|ser[íi]a|son|sea)?\s*$",
    re.I,
)


# Limite de clausula: coma/punto/conjuncion coordinadora. Una fecha que
# precede a la etiqueta al otro lado de uno de estos limites cierra la
# clausula anterior; solo la liga la aposicion pura ("D, la fecha de
# corte"), la enumeracion de alias ("D, la fecha de corte o record
# date") o la fecha cabecera de item ("• 14 de mayo. ... cotizan
# 'ex-cupon' (ex date)").
_CLAUSE_BOUNDARY = re.compile(r"[,;.!?]|\by\b|\be\b|\bni\b")


# Una fecha anterior a la etiqueta cuyo span empieza por preposicion
# ("sobre la base de", "en virtud de") va dentro de un sintagma
# preposicional gobernado por el verbo previo: la etiqueta que le sigue
# es un glosario descriptivo, no su ancla.
_PP_START = re.compile(
    r"^\s*(?:sobre|en|a|de|desde|con|según|conforme|bajo|por|para|hasta"
    r"|mediante|virtud)\b",
    re.I,
)

# Mencion descriptiva del nombre del campo: preposicion que lo introduce
# ("en la fecha de pago", "a fecha de registro") o articulo + "fecha"
# ("la fecha de registro" como concepto). Un articulo solo delante del
# nombre del rol NO es descriptivo: "el ex - date", "el record date" son
# aposiciones que nombran la fecha.
_PREP_PREFIX = re.compile(
    r"\b(?:en|a|de|desde|por|para|hasta|del|al)\s+(?:la\s+|el\s+)?$", re.I
)
_ART_PREFIX = re.compile(r"\b(?:la|el|los|las)\s+$", re.I)


def _is_descriptive(text: str, start: int) -> bool:
    prefix = text[max(0, start - 12):start]
    if _PREP_PREFIX.search(prefix):
        return True
    if _ART_PREFIX.search(prefix):
        return bool(re.match(r"fecha\b", text[start:start + 6], re.I))
    return False


def _label_hits(text: str) -> list[tuple[int, int, str]]:
    hits: list[tuple[int, int, str]] = []
    for role, patterns in _BIND_LABELS.items():
        for pattern in patterns:
            for m in re.finditer(pattern, text, re.I):
                if _is_descriptive(text, m.start()):
                    continue
                hits.append((m.start(), m.end(), role))
    return hits


def _item_head(text: str, dstart: int) -> bool:
    """La fecha encabeza un item (bullet o inicio de linea)."""
    return bool(re.search(r"[•▪◦\n]", text[max(0, dstart - 4):dstart]))


def _before_acceptable(
    text: str,
    dstart: int,
    span: str,
    role: str,
    labels: list[tuple[int, int, str]],
    same_role: dict[str, re.Pattern],
) -> bool:
    """La fecha anterior a la etiqueta no cierra una clausula ajena."""
    if _item_head(text, dstart):
        predicate = _ROLE_PREDICATES.get(role)
        return bool(
            same_role[role].search(span)
            or (predicate and predicate.search(span))
        )
    if _PP_START.match(span):
        return False
    boundaries = list(_CLAUSE_BOUNDARY.finditer(span))
    if not boundaries:
        return True
    tail = span[boundaries[-1].end():]
    return bool(
        re.fullmatch(r"\s*(?:la|el|los|las|un|una|del|al)\s+", tail)
        or re.search(r"\b(?:o|u)\s*$", tail)
    )


def bind_role_dates(text: str) -> dict[str, dict]:
    """Asignacion global etiqueta <-> fecha por rol.

    Cada etiqueta toma como candidatas la fecha mas cercana a cada lado
    (hasta ``_BIND_WINDOW``). Cada par puntua por predicado del rol en el
    span, por corroboracion (el span contiene otra etiqueta del mismo
    rol, p.ej. "fecha de registro (record date) el 4 de mayo") y por
    proximidad. La asignacion es global y greedy: la fecha se la queda
    el par con mayor score; ni una etiqueta ni una fecha se usan dos
    veces. Devuelve ``rol -> {value, iso|None, explicit, matched,
    offset}``.
    """
    dates = [
        (m.start(), m.end(), m.group(0))
        for m in _CANDIDATE_DATE.finditer(text)
    ]
    labels = _label_hits(text)
    same_role = {
        role: re.compile("|".join(patterns), re.I)
        for role, patterns in _BIND_LABELS.items()
    }
    candidates: list[tuple[int, int, int, int, str]] = []
    for lidx, (lstart, lend, lrole) in enumerate(labels):
        predicate = _ROLE_PREDICATES.get(lrole)
        for side in (-1, 1):
            pick = None
            for didx, (dstart, dend, lexeme) in enumerate(dates):
                if side == -1 and dend <= lstart:
                    dist = lstart - dend
                elif side == 1 and dstart >= lend:
                    dist = dstart - lend
                else:
                    continue
                if dist > _BIND_WINDOW:
                    continue
                if pick is None or dist < pick[0]:
                    pick = (dist, didx)
            if pick is None:
                continue
            dist, didx = pick
            dstart, dend, lexeme = dates[didx]
            if dend <= lstart:
                span = text[dend:lstart]
                if not _before_acceptable(
                    text, dstart, span, lrole, labels, same_role
                ):
                    continue
            else:
                span = text[lend:dstart]
            score = _BIND_WINDOW - dist
            if dend > lstart and _LABEL_VALUE.match(span):
                score += 2 * _BIND_WINDOW
            if predicate and predicate.search(span):
                score += 2 * _BIND_WINDOW
            # Corroboracion: el span contiene otro lexema del mismo rol
            # que no sea un hit propio (un alias no puede darse puntos
            # a si mismo para ligar la fecha que sigue a su frase).
            corroborates = same_role[lrole].search(span) and not any(
                r == lrole
                and min(dend, lend) <= s
                and e <= max(lstart, dstart)
                for s, e, r in labels
                if (s, e) != (lstart, lend)
            )
            if corroborates:
                score += 2 * _BIND_WINDOW
            candidates.append((score, -lstart, lidx, didx, lrole))
    candidates.sort(reverse=True)
    used_labels: set[int] = set()
    used_dates: set[int] = set()
    bound: dict[str, dict] = {}
    for _score, _negl, lidx, didx, role in candidates:
        if lidx in used_labels or didx in used_dates or role in bound:
            continue
        used_labels.add(lidx)
        used_dates.add(didx)
        lstart, lend, _ = labels[lidx]
        dstart, dend, lexeme = dates[didx]
        bound[role] = {
            "value": lexeme,
            "iso": _to_iso(lexeme),
            "explicit": bool(re.search(r"\d{4}", lexeme)),
            "matched": text[
                min(lstart, dstart):max(lend, dend)
            ],
            "offset": lstart,
        }
    return bound


def best_role_date(text: str, role: str) -> dict | None:
    """Fecha canonica de un rol dentro de la asignacion global."""
    return bind_role_dates(text).get(role)
