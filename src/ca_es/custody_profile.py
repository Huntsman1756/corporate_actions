"""P13.18 — CA_ES_CUSTODY_PROFILE_V1.

Un profile declara mapping explicito para un custodio/banco: ids de
cuenta, referencias resolubles, fuentes autoritativas. Los adapters
generic0 funcionan sin profile; nada propietario entra al core.

Reglas:

- solo mapping explicito; ninguna seccion puede redefinir semantica
  estandar (un profile no convierte narrativa en identidad);
- claves desconocidas -> error (fail-closed);
- narrative_parsers es declarativo: un parser activo vive en un
  paquete externo; aqui solo se declara su id/version;
- account_map y reference_map son la unica via de identidad.
"""

from __future__ import annotations

from .canonical import load_strict_json_object

PROFILE_SCHEMA = "CA_ES_CUSTODY_PROFILE_V1"

_ALLOWED_KEYS = {
    "schema", "profile_id", "version", "account_map",
    "reference_map", "narrative_parsers", "authoritative_feeds",
    "freshness",
}
_AMOUNT_BASES = {"GROSS", "NET", "UNKNOWN"}
_FEED_KINDS = {"positions", "cash"}


def load_profile(path) -> dict:
    doc = load_strict_json_object(path)
    return validate_profile(doc)


def validate_profile(doc: dict) -> dict:
    if doc.get("schema") != PROFILE_SCHEMA:
        raise ValueError(
            f"profile schema debe ser {PROFILE_SCHEMA}, "
            f"recibido {doc.get('schema')!r}")
    unknown = set(doc) - _ALLOWED_KEYS
    if unknown:
        raise ValueError(f"profile claves desconocidas: {sorted(unknown)}")
    if not doc.get("profile_id"):
        raise ValueError("profile_id requerido")

    amap = doc.get("account_map") or {}
    if not isinstance(amap, dict) or any(
            not isinstance(k, str) or not isinstance(v, str)
            for k, v in amap.items()):
        raise ValueError("account_map debe ser {str: str}")
    targets = list(amap.values())
    if len(set(targets)) != len(targets):
        raise ValueError(
            "account_map con account_id duplicado: dos cuentas "
            "crudas no pueden mapear a la misma sin adjudicacion")

    rmap = doc.get("reference_map") or {}
    if not isinstance(rmap, dict):
        raise ValueError("reference_map debe ser objeto")
    for ref, target in rmap.items():
        if not isinstance(ref, str) or not isinstance(target, dict):
            raise ValueError(
                "reference_map entradas deben ser {str: objeto}")
        if not target.get("event_id"):
            raise ValueError(
                f"reference_map[{ref!r}] sin event_id")
        basis = target.get("amount_basis")
        if basis is not None and basis not in _AMOUNT_BASES:
            raise ValueError(
                f"reference_map[{ref!r}] amount_basis invalido: "
                f"{basis!r}")

    parsers = doc.get("narrative_parsers") or []
    if not isinstance(parsers, list) or any(
            not isinstance(p, dict) or not p.get("parser_id")
            for p in parsers):
        raise ValueError(
            "narrative_parsers debe ser lista de {parser_id, ...}")

    feeds = doc.get("authoritative_feeds") or {}
    if not isinstance(feeds, dict):
        raise ValueError("authoritative_feeds debe ser objeto")
    for kind, table in feeds.items():
        if kind not in _FEED_KINDS:
            raise ValueError(
                f"authoritative_feeds kind desconocido: {kind!r}")
        if not isinstance(table, dict):
            raise ValueError(
                f"authoritative_feeds[{kind}] debe ser objeto")

    return doc


def account_map(profile: dict | None) -> dict:
    return dict((profile or {}).get("account_map") or {})


def reference_map(profile: dict | None) -> dict:
    return dict((profile or {}).get("reference_map") or {})
