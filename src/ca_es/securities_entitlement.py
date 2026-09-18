"""P8.1 — CA_ES_SECURITIES_ENTITLEMENT_V1.

docs/p8/p81-split.md:

    CA_ES_EVENT_TERMS_V1 + CA_ES_POSITIONS_V1
        -> compute_securities_entitlements()
        -> CA_ES_SECURITIES_ENTITLEMENT_V1

Misma disciplina P2.0: Decimal exclusivamente, fail-closed,
POSITION_AT_RECORD_DATE contra basis_date del terms, estados
propagados verbatim, ningun input mutado.

V1 implementa la transformacion SPLIT (forward y REVERSE_SPLIT —
la direccion ya viene probada por el CAEV del mensaje):

    delivered  = posicion completa del source_isin
    receivable = qty x new/old, residuo resuelto por DISF

DISF (preregistrado, nunca estimado):
    RDDN -> floor          RDUP -> ceil
    STAN -> round-half-up  SECU/DIST -> cantidad exacta (fraccion
                            en valores)
    BUYU -> ceil + cash leg solo con precio afirmado
    CINL -> floor + cash leg solo con precio afirmado
    UKNW/ausente -> si hay fraccion real, INDETERMINATE
                    (FRACTION_DISPOSITION_UNKNOWN); si el resultado
                    es entero, la DISF es irrelevante -> ENTITLED
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING, \
    ROUND_FLOOR, ROUND_HALF_UP

TERMS_SCHEMA = "CA_ES_EVENT_TERMS_V1"
SEC_ENT_SCHEMA = "CA_ES_SECURITIES_ENTITLEMENT_V1"
POSITIONS_SCHEMA = "CA_ES_POSITIONS_V1"

ENTITLED = "ENTITLED"
NOT_ENTITLED = "NOT_ENTITLED"
INDETERMINATE = "INDETERMINATE"
UNSUPPORTED = "UNSUPPORTED"

RULE_SPLIT = "SPLIT_POSITION_X_NEW_FOR_OLD_DISF"
RULE_RIGHTS_DIST = "RIGHTS_DISTRIBUTION_POSITION_X_NEWO"
RULE_RIGHTS_EXER = "RIGHTS_EXERCISE_ELECTED_X_NEWO_X_PRICE"
RULE_STOCK_DIV = "STOCK_DIVIDEND_POSITION_X_NEWO"
RULE_SCRIP = "SCRIP_ELECTION_CASH_OR_SECU"
RULE_BONUS = "BONUS_ISSUE_POSITION_X_NEWO"

_DISF_FLOOR = {"RDDN", "CINL"}
_DISF_CEIL = {"RDUP", "BUYU"}
_DISF_EXACT = {"SECU", "DIST"}
_DISF_CASH_LEG = {"BUYU", "CINL"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _decimal(raw) -> Decimal | None:
    if raw is None or isinstance(raw, float):
        return None
    try:
        value = Decimal(str(raw).replace(",", "."))
    except (InvalidOperation, ValueError):
        return None
    return value if value.is_finite() else None


def _money(normalized: Decimal, currency: str) -> dict:
    return {
        "normalized": format(normalized, "f"),
        "currency": currency,
        "scale": -normalized.as_tuple().exponent,
    }


def _apply_disf(raw: Decimal, disf: str | None) -> tuple:
    """(resolved_qty, fraction, cash_leg_required, reason).

    cash_leg_required=True cuando la politica genera pago cash que
    requiere precio afirmado (BUYU/CINL)."""
    if raw == raw.to_integral_value():
        return raw, Decimal(0), False, None
    if disf is None or disf == "UKNW":
        return None, None, False, "FRACTION_DISPOSITION_UNKNOWN"
    if disf in _DISF_EXACT:
        return raw, raw - raw.to_integral_value(), False, None
    if disf in _DISF_FLOOR:
        resolved = raw.to_integral_value(rounding=ROUND_FLOOR)
        return resolved, raw - resolved, disf in _DISF_CASH_LEG, None
    if disf == "STAN":
        resolved = raw.to_integral_value(rounding=ROUND_HALF_UP)
        return resolved, raw - resolved, False, None
    if disf in _DISF_CEIL:
        resolved = raw.to_integral_value(rounding=ROUND_CEILING)
        return resolved, raw - resolved, disf in _DISF_CASH_LEG, None
    return None, None, False, f"UNSUPPORTED_DISF:{disf}"


_RULE_BY_MECHANISM = {
    None: RULE_SPLIT,
    "REVERSE_SPLIT": RULE_SPLIT,
    "RIGHTS_DISTRIBUTION": RULE_RIGHTS_DIST,
    "RIGHTS_EXERCISE": RULE_RIGHTS_EXER,
    "STOCK_DIVIDEND": RULE_STOCK_DIV,
    "SCRIP_DIVIDEND": RULE_SCRIP,
    "BONUS_ISSUE": RULE_BONUS,
}

_SUPPORTED_EVENT_TYPES = {"SPLIT", "RIGHTS_ISSUE", "STOCK_DIVIDEND",
                          "SCRIP_DIVIDEND", "CAPITAL_INCREASE"}


def _entitlement(terms: dict, position: dict,
                 default_as_of: str | None,
                 election: dict | None) -> dict:
    reasons: list[str] = []
    account_id = position.get("account_id")
    isin = position.get("isin")
    quantity = _decimal(position.get("quantity"))
    position_as_of = position.get("as_of") or default_as_of
    mechanism = terms.get("mechanism")
    rule = _RULE_BY_MECHANISM.get(mechanism, RULE_SPLIT)

    base = {
        "account_id": account_id,
        "isin": isin,
        "position_quantity": (
            format(quantity, "f") if quantity is not None else None),
        "position_as_of": position_as_of,
        "reasons": reasons,
        "evidence": {
            "rule": rule,
            "basis_date_kind": "RECORD_DATE",
        },
    }

    def fail(status: str, reason: str) -> dict:
        reasons.append(reason)
        return {**base, "status": status}

    if terms.get("terms_status") != "PROVEN":
        return fail(UNSUPPORTED,
                    f"TERMS_{terms.get('terms_status')}")
    if terms.get("event_type") not in _SUPPORTED_EVENT_TYPES:
        return fail(UNSUPPORTED, "UNSUPPORTED_EVENT_TYPE")
    if mechanism not in _RULE_BY_MECHANISM:
        return fail(UNSUPPORTED, f"UNSUPPORTED_MECHANISM:{mechanism}")
    if account_id is None:
        return fail(INDETERMINATE, "MISSING_ACCOUNT_ID")
    if not isin:
        return fail(INDETERMINATE, "MISSING_ISIN")
    if quantity is None:
        return fail(INDETERMINATE, "INVALID_QUANTITY")
    if quantity < 0:
        return fail(INDETERMINATE, "NEGATIVE_QUANTITY_UNSUPPORTED")
    if position_as_of is None:
        return fail(INDETERMINATE, "MISSING_POSITION_AS_OF")
    if isin != terms.get("source_isin"):
        return fail(INDETERMINATE, "NO_POSITION_FOR_INSTRUMENT")
    if quantity == 0:
        return fail(NOT_ENTITLED, "ZERO_QUANTITY")

    basis_value = (terms.get("basis_date") or {}).get("value")
    try:
        basis_day = date.fromisoformat(basis_value)
        snapshot_day = date.fromisoformat(position_as_of)
    except (ValueError, TypeError):
        return fail(INDETERMINATE, "INVALID_BASIS_OR_POSITION_DATE")
    if snapshot_day != basis_day:
        return fail(
            INDETERMINATE,
            "POSITION_SNAPSHOT_BEFORE_RECORD"
            if snapshot_day < basis_day
            else "POSITION_SNAPSHOT_AFTER_RECORD")

    ratio = terms.get("ratio") or {}
    new_f = _decimal(ratio.get("new"))
    old_f = _decimal(ratio.get("old"))
    if new_f is None or old_f is None or old_f <= 0:
        return fail(INDETERMINATE, "INVALID_RATIO")

    disf = terms.get("fraction_disposition")
    ctx = {
        "base": base, "quantity": quantity, "ratio": (new_f, old_f),
        "disf": disf, "basis_value": basis_value, "fail": fail,
    }
    if mechanism in ("RIGHTS_DISTRIBUTION", "STOCK_DIVIDEND",
                     "BONUS_ISSUE"):
        return _rights_distribution(terms, ctx)
    if mechanism == "RIGHTS_EXERCISE":
        return _rights_exercise(terms, ctx, account_id, election)
    if mechanism == "SCRIP_DIVIDEND":
        return _scrip(terms, ctx, account_id, election)
    return _split(terms, ctx)


def _scrip(terms: dict, ctx: dict, account_id,
           election: dict | None) -> dict:
    """DVOP: la eleccion por cuenta decide la pierna.

    SECU -> receipt-only de acciones (misma math que RHDI/DVSE);
    CASH -> receivable_cash = posicion x gross_per_share.
    Nunca se aplica el DFLT de la fuente."""
    fail = ctx["fail"]
    quantity, (new_f, old_f) = ctx["quantity"], ctx["ratio"]

    if not election or account_id not in election:
        return fail(INDETERMINATE, "PENDING_ELECTION")
    option = election.get(account_id)
    if option not in ("CASH", "SECU"):
        return fail(INDETERMINATE, f"INVALID_ELECTION:{option}")

    if option == "SECU":
        disf = ctx["disf"]
        raw_qty = quantity * new_f / old_f
        resolved, fraction, cash_leg, reason = _apply_disf(
            raw_qty, disf)
        if reason is not None:
            return fail(INDETERMINATE, reason)
        cash_in_lieu = None
        if cash_leg:
            ctx["terms"] = terms
            cash_in_lieu, failure = _cash_in_lieu(ctx, fraction)
            if failure is not None:
                return failure
        return {
            **ctx["base"],
            "status": ENTITLED,
            "elected_option": "SECU",
            "delivered": None,
            "receivable": {
                "isin": terms["target_isin"],
                "quantity": format(resolved, "f"),
            },
            "raw_quantity": format(raw_qty, "f"),
            "fraction": {
                "amount": format(fraction, "f"),
                "disposition": disf or "NOT_REQUIRED",
                "cash_in_lieu": cash_in_lieu,
            },
            "calculation":
                "position_quantity x new_for_old + DISF "
                "(elected SECU)",
            "basis": {
                "record_date": ctx["basis_value"],
                "position_eligibility": "POSITION_AT_RECORD_DATE",
            },
        }

    # pierna CASH
    gross = _decimal(terms.get("gross_per_share"))
    currency = terms.get("currency")
    if gross is None or not currency:
        return fail(INDETERMINATE, "INVALID_GROSS_OR_CURRENCY")
    return {
        **ctx["base"],
        "status": ENTITLED,
        "elected_option": "CASH",
        "delivered": None,
        "receivable": None,
        "receivable_cash": _money(quantity * gross, currency),
        "calculation":
            "position_quantity x gross_per_share (elected CASH)",
        "basis": {
            "record_date": ctx["basis_value"],
            "position_eligibility": "POSITION_AT_RECORD_DATE",
        },
    }


def _cash_in_lieu(ctx, fraction):
    fail = ctx["fail"]
    price = ctx["terms"].get("cash_in_lieu_price")
    if not price or price.get("normalized") is None:
        return None, fail(INDETERMINATE, "CASH_IN_LIEU_PRICE_MISSING")
    amount = _decimal(price["normalized"])
    if amount is None:
        return None, fail(INDETERMINATE, "INVALID_CASH_IN_LIEU_PRICE")
    return _money(amount * abs(fraction), price.get("currency")), None


def _split(terms: dict, ctx: dict) -> dict:
    quantity, (new_f, old_f) = ctx["quantity"], ctx["ratio"]
    disf = ctx["disf"]
    raw_qty = quantity * new_f / old_f
    resolved, fraction, cash_leg, reason = _apply_disf(raw_qty, disf)
    if reason is not None:
        return ctx["fail"](INDETERMINATE, reason)

    cash_in_lieu = None
    if cash_leg:
        ctx["terms"] = terms
        cash_in_lieu, failure = _cash_in_lieu(ctx, fraction)
        if failure is not None:
            return failure

    return {
        **ctx["base"],
        "status": ENTITLED,
        "delivered": {
            "isin": terms["source_isin"],
            "quantity": format(quantity, "f"),
        },
        "receivable": {
            "isin": terms["target_isin"],
            "quantity": format(resolved, "f"),
        },
        "raw_quantity": format(raw_qty, "f"),
        "fraction": {
            "amount": format(fraction, "f"),
            "disposition": disf or "NOT_REQUIRED",
            "cash_in_lieu": cash_in_lieu,
        },
        "calculation": "position_quantity x new_for_old + DISF",
        "basis": {
            "record_date": ctx["basis_value"],
            "position_eligibility": "POSITION_AT_RECORD_DATE",
        },
    }


def _rights_distribution(terms: dict, ctx: dict) -> dict:
    """RHDI: receipt de derechos sin delivery del subyacente."""
    quantity, (new_f, old_f) = ctx["quantity"], ctx["ratio"]
    disf = ctx["disf"]
    raw_qty = quantity * new_f / old_f
    resolved, fraction, cash_leg, reason = _apply_disf(raw_qty, disf)
    if reason is not None:
        return ctx["fail"](INDETERMINATE, reason)

    cash_in_lieu = None
    if cash_leg:
        ctx["terms"] = terms
        cash_in_lieu, failure = _cash_in_lieu(ctx, fraction)
        if failure is not None:
            return failure

    return {
        **ctx["base"],
        "status": ENTITLED,
        "delivered": None,
        "receivable": {
            "isin": terms["target_isin"],
            "quantity": format(resolved, "f"),
        },
        "raw_quantity": format(raw_qty, "f"),
        "fraction": {
            "amount": format(fraction, "f"),
            "disposition": disf or "NOT_REQUIRED",
            "cash_in_lieu": cash_in_lieu,
        },
        "calculation": "position_quantity x new_for_old + DISF",
        "basis": {
            "record_date": ctx["basis_value"],
            "position_eligibility": "POSITION_AT_RECORD_DATE",
        },
    }


def _rights_exercise(terms: dict, ctx: dict, account_id,
                     election: dict | None) -> dict:
    """EXRI: elected rights -> nuevas acciones + cash payable;
    derechos no ejercidos hacen lapse (delivery sin receipt)."""
    fail = ctx["fail"]
    quantity, (new_f, old_f) = ctx["quantity"], ctx["ratio"]

    if not election or account_id not in election:
        return fail(INDETERMINATE, "PENDING_ELECTION")
    elected = _decimal(election.get(account_id))
    if elected is None or elected < 0:
        return fail(INDETERMINATE, "INVALID_ELECTED_QUANTITY")
    if elected != elected.to_integral_value():
        return fail(INDETERMINATE, "NON_INTEGRAL_ELECTION")
    if elected > quantity:
        return fail(INDETERMINATE, "ELECTED_EXCEEDS_RIGHTS")
    if elected == 0:
        return {**ctx["base"], "status": NOT_ENTITLED,
                "reasons": ctx["base"]["reasons"] +
                ["ZERO_ELECTION_LAPSE"]}

    price = terms.get("subscription_price") or {}
    amount = _decimal(price.get("normalized"))
    if amount is None or not price.get("currency"):
        return fail(INDETERMINATE, "INVALID_SUBSCRIPTION_PRICE")

    disf = ctx["disf"]
    raw_qty = elected * new_f / old_f
    resolved, fraction, cash_leg, reason = _apply_disf(raw_qty, disf)
    if reason is not None:
        return fail(INDETERMINATE, reason)

    cash_in_lieu = None
    if cash_leg:
        ctx["terms"] = terms
        cash_in_lieu, failure = _cash_in_lieu(ctx, fraction)
        if failure is not None:
            return failure

    return {
        **ctx["base"],
        "status": ENTITLED,
        "elected": format(elected, "f"),
        "delivered": {
            "isin": terms["source_isin"],
            "quantity": format(quantity, "f"),
            "exercised": format(elected, "f"),
            "lapsed": format(quantity - elected, "f"),
        },
        "receivable": {
            "isin": terms["target_isin"],
            "quantity": format(resolved, "f"),
        },
        "raw_quantity": format(raw_qty, "f"),
        "payable": _money(resolved * amount, price["currency"]),
        "fraction": {
            "amount": format(fraction, "f"),
            "disposition": disf or "NOT_REQUIRED",
            "cash_in_lieu": cash_in_lieu,
        },
        "calculation":
            "elected x new_for_old + DISF; payable = receivable x "
            "subscription_price",
        "basis": {
            "record_date": ctx["basis_value"],
            "position_eligibility": "POSITION_AT_RECORD_DATE",
        },
    }


def compute_securities_entitlements(
        terms_doc: dict, positions_doc: dict,
        election: dict | None = None,
        now: str | None = None) -> dict:
    """terms + positions -> CA_ES_SECURITIES_ENTITLEMENT_V1.

    `election`: {account_id: elected_quantity} explicito — requerido
    solo para RIGHTS_EXERCISE (EXRI); ausente -> PENDING_ELECTION.

    Puro y read-only: ningun input se muta."""
    if terms_doc.get("schema") != TERMS_SCHEMA:
        raise ValueError(
            f"terms schema debe ser {TERMS_SCHEMA}, "
            f"recibido {terms_doc.get('schema')!r}")
    if positions_doc.get("schema") != POSITIONS_SCHEMA:
        raise ValueError(
            f"positions schema debe ser {POSITIONS_SCHEMA}, "
            f"recibido {positions_doc.get('schema')!r}")
    if election is not None and not isinstance(election, dict):
        raise ValueError("election debe ser {account_id: qty}")

    default_as_of = positions_doc.get("as_of")
    entitlements = [
        _entitlement(terms_doc, position, default_as_of, election)
        for position in positions_doc.get("positions", [])
    ]
    summary = {"positions": len(entitlements)}
    for status in (ENTITLED, NOT_ENTITLED, INDETERMINATE, UNSUPPORTED):
        summary[status.casefold()] = sum(
            1 for e in entitlements if e["status"] == status)

    return {
        "schema": SEC_ENT_SCHEMA,
        "generated_at": now or _now(),
        "event_basis": terms_doc.get("event_basis"),
        "canonical_event_id": terms_doc.get("canonical_event_id"),
        "message_identifier": terms_doc.get("message_identifier"),
        "input_sha256": terms_doc.get("input_sha256"),
        "caev": terms_doc.get("caev"),
        "event_type": terms_doc.get("event_type"),
        "mechanism": terms_doc.get("mechanism"),
        "terms_status": terms_doc.get("terms_status"),
        "positions_as_of": default_as_of,
        "entitlements": entitlements,
        "summary": summary,
    }
