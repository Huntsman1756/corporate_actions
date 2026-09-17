"""Reaplica adjudicaciones PROPOSED sobre missingness-review.jsonl.

Reglas: NOT_CA -> N/A. Lifecycle REGISTRATION/REGISTRY -> fechas
operativas N/A salvo que publiquen. Campos ausentes en la fuente
-> UNKNOWN/NOT_PUBLISHED. Ezentis event_type -> AMBIGUOUS (la pagina
de registro no declara el evento; la clasificacion CNMV si).
"""
import json

PATH = "g1/adjudication/missingness-review.jsonl"
TS = "2026-09-14"
REVIEWER = "devin-agent"

# (frame_item_id, field) -> (classification, published_status, applicability_override, locator)
ADJ = {
    # BMEG: la row oficial es la fuente; campos no presentes -> NOT_PUBLISHED
    ("BMEG-CapitalIncreases-ES0105425021-2026-02-23", "ex_date"): (
        "UNKNOWN", "NOT_PUBLISHED", None,
        'row BMEG: sin exDate; publica startingDate/finishDate de negociacion de derechos',
    ),
    ("BMEG-CapitalIncreases-ES0105425021-2026-02-23", "record_date"): (
        "UNKNOWN", "NOT_PUBLISHED", None,
        'row BMEG: sin recordDate',
    ),
    ("BMEG-CapitalIncreases-ES0105425021-2026-02-23", "payment_date"): (
        "UNKNOWN", "NOT_PUBLISHED", None,
        'row BMEG: sin paymentDate',
    ),
    ("BMEG-Dividends-ES0105318002-2026-07-03", "record_date"): (
        "UNKNOWN", "NOT_PUBLISHED", None,
        'row BMEG: publica exDate/paymentDate/gross/net; sin recordDate',
    ),
    ("BMEG-Dividends-ES0131172001-2026-07-07", "record_date"): (
        "UNKNOWN", "NOT_PUBLISHED", None,
        'row BMEG: sin recordDate',
    ),
    ("BMEG-NewListings-ES0105495008-2025-06-10", "ex_date"): (
        "NOT_APPLICABLE", "N/A", "NOT_APPLICABLE",
        'NEW_LISTING: row publica admissionDate; ex/record/payment no aplican',
    ),
    ("BMEG-NewListings-ES0105495008-2025-06-10", "record_date"): (
        "NOT_APPLICABLE", "N/A", "NOT_APPLICABLE",
        'NEW_LISTING: no aplica',
    ),
    ("BMEG-NewListings-ES0105495008-2025-06-10", "payment_date"): (
        "NOT_APPLICABLE", "N/A", "NOT_APPLICABLE",
        'NEW_LISTING: no aplica',
    ),
    ("BMEG-OtherPayments-ES0105421004-2025-03-18", "record_date"): (
        "UNKNOWN", "NOT_PUBLISHED", "APPLICABLE",
        'pago de prima de emision: record_date aplicable; row publica exDate pero no recordDate',
    ),
    ("BMEG-OtherPayments-ES0105685004-2026-05-25", "record_date"): (
        "UNKNOWN", "NOT_PUBLISHED", "APPLICABLE",
        'row BMEG: sin recordDate',
    ),
    # Ezentis: superficie de registro (stage REGISTRATION)
    ("CNMV-OIR-33627", "event_type"): (
        "AMBIGUOUS", "AMBIGUOUS", "APPLICABLE",
        'pagina oficial derechos de voto/capital: la clasificacion CNMV es inscripcion de aumento de capital, pero el artefacto no declara el evento como lexema',
    ),
    ("CNMV-OIR-33627", "ex_date"): (
        "NOT_APPLICABLE", "N/A", "NOT_APPLICABLE",
        'CAPITAL_INCREASE/REGISTRATION: el artefacto confirma inscripcion; ex_date no aplica a esta fase',
    ),
    ("CNMV-OIR-33627", "record_date"): (
        "NOT_APPLICABLE", "N/A", "NOT_APPLICABLE",
        'CAPITAL_INCREASE/REGISTRATION: no aplica',
    ),
    ("CNMV-OIR-33627", "payment_date"): (
        "NOT_APPLICABLE", "N/A", "NOT_APPLICABLE",
        'CAPITAL_INCREASE/REGISTRATION: no aplica',
    ),
    ("CNMV-OIR-33627", "amount_or_ratio"): (
        "UNKNOWN", "NOT_PUBLISHED", "APPLICABLE",
        'la pagina publica capital social/acciones como estado, no el importe del aumento',
    ),
    ("CNMV-OIR-33627", "currency"): (
        "UNKNOWN", "NOT_PUBLISHED", "APPLICABLE",
        'capital social en EUR implicito, no declarado como campo del evento',
    ),
    # BBVA amortizacion anticipada
    ("CNMV-OIR-34234", "ex_date"): (
        "NOT_APPLICABLE", "N/A", "NOT_APPLICABLE",
        'EARLY_REDEMPTION de cedulas: sin ex-date',
    ),
    ("CNMV-OIR-34234", "record_date"): (
        "NOT_APPLICABLE", "N/A", "NOT_APPLICABLE",
        'amortizacion total: no hay record date separada del valor',
    ),
    # CIE OPA sobre propias acciones (condicion cumplida)
    ("CNMV-OIR-34753", "record_date"): (
        "NOT_APPLICABLE", "N/A", "NOT_APPLICABLE",
        'TENDER: record_date no aplica a aceptacion de OPA',
    ),
    ("CNMV-OIR-34753", "payment_date"): (
        "UNKNOWN", "NOT_PUBLISHED", "APPLICABLE",
        'el aviso declara condicion cumplida; no fija fecha de liquidacion',
    ),
    ("CNMV-OIR-34753", "amount_or_ratio"): (
        "UNKNOWN", "NOT_PUBLISHED", "APPLICABLE",
        'precio de la OPA publicado en documentos previos, no en este aviso',
    ),
    ("CNMV-OIR-34753", "currency"): (
        "UNKNOWN", "NOT_PUBLISHED", "APPLICABLE",
        'no declarado en este aviso',
    ),
    # AEDAS amortizacion anticipada (calendario por comunicar)
    ("CNMV-OIR-38513", "ex_date"): (
        "NOT_APPLICABLE", "N/A", "NOT_APPLICABLE",
        'EARLY_REDEMPTION: sin ex-date',
    ),
    ("CNMV-OIR-38513", "record_date"): (
        "NOT_APPLICABLE", "N/A", "NOT_APPLICABLE",
        'EARLY_REDEMPTION: sin record date',
    ),
    ("CNMV-OIR-38513", "payment_date"): (
        "UNKNOWN", "NOT_PUBLISHED", "APPLICABLE",
        'el documento indica que el calendario se comunicara; no publica fecha',
    ),
    # CLINICA BAVIERA propuesta de dividendo
    ("CNMV-OIR-39905", "ex_date"): (
        "UNKNOWN", "NOT_PUBLISHED", "APPLICABLE",
        'propuesta sujeta a Junta; sin ex_date publicada',
    ),
    ("CNMV-OIR-39905", "record_date"): (
        "UNKNOWN", "NOT_PUBLISHED", "APPLICABLE",
        'sin record_date publicada',
    ),
    ("CNMV-OIR-39905", "payment_date"): (
        "UNKNOWN", "NOT_PUBLISHED", "APPLICABLE",
        'el documento dice que la fecha de pago se comunicara tras la convocatoria de Junta',
    ),
    # SMART KITCHENS aviso de ejecucion
    ("POEX-DOC-41986", "ex_date"): (
        "NOT_APPLICABLE", "N/A", "NOT_APPLICABLE",
        'CAPITAL_REDUCTION/REGISTRATION: aviso de ejecucion; sin ex-date',
    ),
    ("POEX-DOC-41986", "record_date"): (
        "NOT_APPLICABLE", "N/A", "NOT_APPLICABLE",
        'ejecucion ya efectuada: no aplica',
    ),
    ("POEX-DOC-41986", "payment_date"): (
        "UNKNOWN", "NOT_PUBLISHED", "APPLICABLE",
        'publica fecha efectiva 11/08/2026, no fecha de pago de la devolucion',
    ),
    # AC RESIDENCIAL BORME/ejecucion
    ("POEX-DOC-7018", "ex_date"): (
        "NOT_APPLICABLE", "N/A", "NOT_APPLICABLE",
        'CAPITAL_REDUCTION/REGISTRATION: sin ex-date',
    ),
    ("POEX-DOC-7018", "record_date"): (
        "NOT_APPLICABLE", "N/A", "NOT_APPLICABLE",
        'no aplica',
    ),
    ("POEX-DOC-7018", "payment_date"): (
        "UNKNOWN", "NOT_PUBLISHED", "APPLICABLE",
        'el aviso indica que el calendario de pago se comunicara',
    ),
}

NOT_CA = {"CNMV-IP-2864", "CNMV-OIR-38198", "CNMV-OIR-40136"}

out = []
unmapped = []
for line in open(PATH, encoding="utf-8"):
    e = json.loads(line)
    key = (e["frame_item_id"], e["field"])
    if e["frame_item_id"] in NOT_CA:
        e["applicability"] = "NOT_APPLICABLE"
        e["classification"] = "NOT_APPLICABLE"
        e["source_review"] = {
            "evidence_locator": "seed_verdict=NOT_CA: no hay evento sobre el titulo",
            "published_status": "N/A",
            "reviewed_at": TS,
            "reviewer": REVIEWER,
            "source_document_id": e["source_review"]["source_document_id"],
        }
    elif key in ADJ:
        classification, status, applicability, locator = ADJ[key]
        if applicability:
            e["applicability"] = applicability
        e["classification"] = classification
        e["source_review"] = {
            "evidence_locator": locator,
            "published_status": status,
            "reviewed_at": TS,
            "reviewer": REVIEWER,
            "source_document_id": e["source_review"]["source_document_id"],
        }
    else:
        unmapped.append(key)
    e.setdefault("status", "PROPOSED")
    out.append(e)

with open(PATH, "w", encoding="utf-8", newline="\n") as fh:
    for e in out:
        fh.write(json.dumps(e, ensure_ascii=False, sort_keys=True) + "\n")

from collections import Counter
print(Counter(e["classification"] for e in out))
if unmapped:
    print("SIN MAPEAR:", unmapped)
