# -*- coding: utf-8 -*-
"""Genera p1/smoke/previous-canon.json: snapshot "de ayer" para el
smoke humano de P1.2 (delta-state).

Escenario construido sobre g3/input/canon.json (canon actual):

- MFE: el mismo documento CNMV-OIR-40319 (revision gen1) afirmaba
  ayer ex/record/payment = 25/26/27 jul; hoy afirma 20/21/22.
  -> 3 x CHANGED_ASSERTION con evidencia real en ambos lados.
- MFE: ayer existia ademas una afirmacion date.election_deadline
  (mismo doc, gen1) que hoy ya no esta -> REMOVED_ASSERTION.
- BME Growth dividend: la afirmacion amount.net_per_share es nueva
  (ayer no estaba) -> NEW_ASSERTION.
- BME Growth capital increase: el evento entero es nuevo
  -> NEW_EVENT (sin cascada).
- Almirall: el conflicto date.announcement_date es nuevo
  -> NEW_CONFLICT.

El logical_sha256 se recalcula sobre el payload modificado para que
el fixture sea autoconsistente. Artefacto sintetico de smoke, no forma
parte del corpus ni de ningun gate.
"""
import hashlib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CANON = REPO / "g3/input/canon.json"
OUT = REPO / "p1/smoke/previous-canon.json"

MFE = "59303c3c-8be7-578f-bc59-8e5e43a1fdf3"
ALMIRALL = "035e32ca-ba61-5105-8756-e0234e5335fc"
BMEG_DIV = "6881d24a-ef46-5053-80ce-1743a1792f8b"
BMEG_CAP = "3c9270d8-76b3-5953-942c-b1f42c1cc56a"
MFE_GEN1 = "369e7813-7a15-5c1d-85cc-f1fe143a0e5e"

YESTERDAY_DATES = {
    "date.ex_date": "2026-07-25",
    "date.record_date": "2026-07-26",
    "date.payment_date": "2026-07-27",
}


def main() -> None:
    canon = json.loads(CANON.read_text(encoding="utf-8"))

    events = {e["canonical_event_id"]: e for e in canon["events"]}

    mfe = events[MFE]
    template = None
    for fact in mfe["facts"]:
        if fact["revision_id"] != MFE_GEN1:
            continue
        if fact["field_path"] in YESTERDAY_DATES:
            template = template or fact
            fact["value"] = YESTERDAY_DATES[fact["field_path"]]
    assert template is not None, "gen1 MFE facts not found"
    # ayer el mismo doc afirmaba tambien un election deadline que hoy
    # ya no esta en el canon
    retracted = dict(template)
    retracted["field_path"] = "date.election_deadline"
    retracted["date_kind"] = "ELECTION_DEADLINE"
    retracted["value"] = "2026-07-24"
    retracted["assertion_id"] = "p1smoke-retracted-election-deadline"
    mfe["facts"].append(retracted)

    events[BMEG_DIV]["facts"] = [
        f
        for f in events[BMEG_DIV]["facts"]
        if f["field_path"] != "amount.net_per_share"
    ]
    events[ALMIRALL]["conflicts"] = []
    canon["events"] = [
        e for e in canon["events"]
        if e["canonical_event_id"] != BMEG_CAP
    ]

    canon.pop("logical_sha256", None)
    from ca_es.export import canon_bytes

    canon["logical_sha256"] = hashlib.sha256(
        canon_bytes(canon)
    ).hexdigest()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(canon, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(OUT)


if __name__ == "__main__":
    main()
