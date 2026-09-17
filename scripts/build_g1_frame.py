"""Construye el frame de muestreo G1, el corpus seleccionado y el split.

Enumeracion determinista pre-ingesta (fuentes cerradas en
docs/gates/g1-sampling-preregistered.json). El SHA-256 del frame es el
nuevo punto de congelacion de G1.

    python scripts/build_g1_frame.py [--skip-cnmv] [--skip-portfolio]

Salidas:
  g1/corpus/raw/frame/...            snapshots crudos (LOCAL_ONLY)
  g1/manifests/sampling-frame.json   frame completo (candidatos elegibles)
  g1/manifests/sampling-frame.sha256
  g1/manifests/corpus.json           seleccion + particion DEV/HOLDOUT
  g1/manifests/bme-benchmark.json    referencia externa SIBE (no es frame)
  g1/manifests/dev-holdout.json      listas pobladas

El script es reanudable: los snapshots mensuales/tipo ya presentes no se
vuelven a descargar (salvo --force).
"""
from __future__ import annotations

import argparse
import hashlib
import html as html_mod
import json
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import fetch_cnmv as cnmv  # noqa: E402
from ca_es.canonical import canonical_bytes, sha256_bytes, sha256_text  # noqa: E402

RAW_DIR = REPO_ROOT / "g1" / "corpus" / "raw" / "frame"
MANIFEST_DIR = REPO_ROOT / "g1" / "manifests"

WINDOW = {"from": "2025-01-01", "to": "2026-09-13"}
STRATUM_TARGETS = {"MAIN_MARKET": 20, "BME_GROWTH_MTF": 10, "PORTFOLIO": 10}
HOLDOUT_COUNT = 15
SAMPLE_NS = "CA_ES_G1_SAMPLE_V1"
SPLIT_NS = "CA_ES_G1_SPLIT_V1"
NEGCTRL_NS = "CA_ES_G1_NEGCTRL_V1"
NEGCTRL_N = 100
ADV_NS = "CA_ES_G1_ADV_V1"
ADV_N = 10

# Criterios adversariales detectables con metadata del frame (titulo,
# categoria, related). Los criterios que exigen leer el documento no se
# preseleccionan: se etiquetan KNOWN_PRE_G1 o DISCOVERED_ADVERSARIAL.
ADV_METADATA_TITLE_PATTERNS = {
    "EXPLICIT_REVISION": [
        r"nuevas? fechas?",
        r"rectific",
        r"modificaci",
        r"actualizaci",
        r"sustitu",
    ],
    "RIGHTS_OR_OPTIONALITY": [
        r"derechos? de suscripci",
        r"suscripci[o\u00f3]n preferente",
        r"\bscrip\b",
        r"canje",
        r"opci[o\u00f3]n",
    ],
    "MERGER_OR_EXCHANGE": [r"fusi[o\u00f3]n", r"escisi[o\u00f3]n", r"absorci[o\u00f3]n"],
    "TAKEOVER": [r"\bopa\b", r"oferta publica de adquisici"],
    "CAPITAL_REDUCTION": [
        r"reducci[o\u00f3]n de capital",
        r"devoluci[o\u00f3]n de (aportaciones|prima)",
        r"amortizaci[o\u00f3]n de acciones",
    ],
    "EARLY_REDEMPTION": [
        r"amortizaci[o\u00f3]n anticipada",
        r"reembolso anticipado",
        r"redenci[o\u00f3]n",
    ],
}
ADV_CONTENT_REQUIRED = [
    "NON_DEFAULT_INFRASTRUCTURE",
    "COMPLEX_ENTITLEMENT",
    "MUTABLE_ENTITLEMENT",
    "ISIN_CHANGE",
    "HIGH_PRECISION_AMOUNT",
]

CNMV_RESULTADO = {
    "oir": "https://www.cnmv.es/portal/otra-informacion-relevante/resultado-oir.aspx?fechaDesde={desde}&fechaHasta={hasta}&page={page}",
    "ip": "https://www.cnmv.es/portal/informacion-privilegiada/resultado-ip.aspx?fechaDesde={desde}&fechaHasta={hasta}&page={page}",
}

BME_API = "https://apiweb.bolsasymercados.es/Market/v1/EQ/CorporateActions/{kind}"
BME_TYPES = [
    "Dividends",
    "CapitalIncreases",
    "Splits",
    "Mergers",
    "OtherPayments",
    "NewListings",
    "Delistings",
    "PublicOfferings",
    "TakeoverBids",
]
BME_DATE_KEYS = [
    "exDate",
    "splitDate",
    "startingDate",
    "admissionDate",
    "authorisationDate",
    "paymentDate",
    "finishDate",
]

PORTFOLIO_INDEX = "https://portfolio.exchange/es/portfolio-market"
PORTFOLIO_PRODUCT_RE = re.compile(
    r"/es/portfolio-market/([a-z0-9-]+-[A-Z0-9]+-ES[A-Z0-9]{10}-\d+)"
)
PORTFOLIO_SECTION_RE = re.compile(
    r'"(issuanceInfo|insideInformation|otherRelevant|marketNotices|'
    r'financialDocs|prospectus|publicOffers)"'
)
PORTFOLIO_DOC_RE = re.compile(
    r'(?<![\d.])(\d+),((?:"[^"]{0,300}",){0,5})"(\d{4}-\d{2}-\d{2})T[^"]*",'
    r'"https:\\u002F\\u002Fapi\.portfolio\.exchange\\u002Fpoex\\u002Fdocument\\u002F(\d+)"'
)
PORTFOLIO_TYPE_RE = re.compile(r"^[A-Z_]{3,40}$")

POLITE_SLEEP = 0.35


def normalize(text: str | None) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text).lower().strip()


def get(opener, url: str, referer: str | None = None, retries: int = 4) -> bytes:
    headers = {**cnmv.HEADERS}
    if referer:
        headers["Referer"] = referer
    for attempt in range(retries):
        try:
            time.sleep(POLITE_SLEEP)
            return opener.open(
                urllib.request.Request(url, headers=headers), timeout=90
            ).read()
        except Exception as exc:  # noqa: BLE001
            if attempt == retries - 1:
                raise
            time.sleep(2**attempt)
    raise RuntimeError(f"unreachable: {url}")


def month_chunks(dfrom: date, dto: date) -> list[tuple[date, date]]:
    chunks = []
    year, month = dfrom.year, dfrom.month
    while True:
        start = date(year, month, 1)
        if month == 12:
            nxt = date(year + 1, 1, 1)
        else:
            nxt = date(year, month + 1, 1)
        end = nxt.toordinal() - 1
        end = date.fromordinal(end)
        chunk = (max(start, dfrom), min(end, dto))
        if chunk[0] > chunk[1]:
            break
        chunks.append(chunk)
        if end >= dto:
            break
        year, month = nxt.year, nxt.month
    return chunks


def dmy(iso: str) -> str:
    y, m, d = iso.split("-")
    return f"{d}/{m}/{y}"


def iso_from_dmy(value: str | None) -> str | None:
    if not value:
        return None
    d, m, y = value.split("/")
    return f"{y}-{m}-{d}"


def no_floats(obj: object) -> object:
    if isinstance(obj, float):
        return repr(obj)
    if isinstance(obj, dict):
        return {k: no_floats(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [no_floats(v) for v in obj]
    return obj


def save_raw(path: Path, payload: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return sha256_bytes(payload)


def save_json_raw(path: Path, obj: object) -> str:
    return save_raw(path, canonical_bytes(no_floats(obj)))


def enumerate_cnmv_portal(
    opener, portal: str, chunks: list[tuple[date, date]], force: bool
) -> tuple[list[dict], int]:
    out_dir = RAW_DIR / f"cnmv-{portal}"
    rows: list[dict] = []
    total = 0
    seen: set[str] = set()
    for start, end in chunks:
        tag = f"{start:%Y%m}"
        month_file = out_dir / f"{portal}-{tag}.json"
        if month_file.exists() and not force:
            month_rows = json.loads(month_file.read_text(encoding="utf-8"))["rows"]
        else:
            month_rows = []
            template = CNMV_RESULTADO[portal]
            url = template.format(desde=dmy(start.isoformat()), hasta=dmy(end.isoformat()), page=0)
            html = get(opener, url, cnmv.PORTALS[portal]["page"]).decode("utf-8", "replace")
            month_rows.extend(cnmv.extract_results(html))
            max_page = 0
            for link in cnmv.paginate_links(html):
                match = re.search(r"page=(\d+)", link)
                if match:
                    max_page = max(max_page, int(match.group(1)))
            for page in range(1, max_page + 1):
                page_html = get(
                    opener,
                    template.format(
                        desde=dmy(start.isoformat()),
                        hasta=dmy(end.isoformat()),
                        page=page,
                    ),
                    cnmv.PORTALS[portal]["page"],
                ).decode("utf-8", "replace")
                page_rows = cnmv.extract_results(page_html)
                if not page_rows:
                    break
                month_rows.extend(page_rows)
            save_json_raw(month_file, {"portal": portal, "chunk": [str(start), str(end)], "rows": month_rows})
            print(f"  cnmv-{portal} {tag}: {len(month_rows)} rows", flush=True)
        total += len(month_rows)
        for row in month_rows:
            key = row.get("registration_number") or row.get("document_url") or repr(row)
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
    return rows, total


def fetch_bme_ca(opener, trading_system: str, mtf_segment: str, kind: str,
                 force: bool, tag: str) -> list[dict]:
    out_dir = RAW_DIR / f"bme-{tag}"
    out_file = out_dir / f"{kind}.json"
    if out_file.exists() and not force:
        cached = json.loads(out_file.read_text(encoding="utf-8"))
        return (cached.get("data") if isinstance(cached, dict) else cached) or []
    query = urllib.parse.urlencode(
        {
            "companyKey": "",
            "from": WINDOW["from"].replace("-", ""),
            "to": WINDOW["to"].replace("-", ""),
            "page": 0,
            "pageSize": 0,
            "tradingSystem": trading_system,
            "listingType": "All",
            "mtfSegment": mtf_segment,
        }
    )
    url = BME_API.format(kind=kind) + "?" + query
    payload = get(opener, url, "https://www.bolsasymercados.es/")
    data = json.loads(payload)
    save_raw(out_file, payload)
    items = data.get("data") if isinstance(data, dict) else data
    print(f"  bme-{tag} {kind}: {len(items or [])} rows", flush=True)
    return items or []


def bme_item_date(item: dict) -> str | None:
    for key in BME_DATE_KEYS:
        value = item.get(key)
        if isinstance(value, str) and re.fullmatch(r"\d{8}", value):
            return f"{value[:4]}-{value[4:6]}-{value[6:]}"
    return None


def in_window(iso: str | None) -> bool:
    return iso is not None and WINDOW["from"] <= iso <= WINDOW["to"]


def enumerate_portfolio(opener, force: bool) -> list[dict]:
    out_dir = RAW_DIR / "portfolio"
    index_file = out_dir / "index.html"
    if index_file.exists() and not force:
        index_html = index_file.read_text(encoding="utf-8")
    else:
        index_html = get(opener, PORTFOLIO_INDEX).decode("utf-8", "replace")
        save_raw(index_file, index_html.encode("utf-8"))
    products = sorted(set(PORTFOLIO_PRODUCT_RE.findall(index_html)))
    docs: list[dict] = []
    for product in products:
        url = f"https://portfolio.exchange/es/portfolio-market/{product}"
        safe = re.sub(r"[^a-z0-9]+", "-", product.lower())[:80]
        product_file = out_dir / f"product-{safe}.html"
        if product_file.exists() and not force:
            html = product_file.read_text(encoding="utf-8")
        else:
            try:
                html = get(opener, url).decode("utf-8", "replace")
            except Exception as exc:  # noqa: BLE001
                print(f"  portfolio product ERROR {product}: {exc}", flush=True)
                continue
            save_raw(product_file, html.encode("utf-8"))
        sections = [
            (m.start(), m.group(1)) for m in PORTFOLIO_SECTION_RE.finditer(html)
        ]
        seen_ids: set[str] = set()
        found = 0
        for match in PORTFOLIO_DOC_RE.finditer(html):
            doc_id, strings_blob, day, url_id = match.groups()
            if url_id != doc_id or doc_id in seen_ids:
                continue
            seen_ids.add(doc_id)
            strings = re.findall(r'"([^"]{0,300})"', strings_blob)
            doc_type = next(
                (s for s in strings if PORTFOLIO_TYPE_RE.match(s)), None
            )
            titles = [s for s in strings if not PORTFOLIO_TYPE_RE.match(s)]
            section = next(
                (name for pos, name in reversed(sections) if pos < match.start()),
                None,
            )
            docs.append(
                {
                    "document_id": doc_id,
                    "title": titles[0] if titles else None,
                    "subtype": titles[1] if len(titles) > 1 else None,
                    "type": doc_type,
                    "section": section,
                    "date": day,
                    "url": f"https://api.portfolio.exchange/poex/document/{doc_id}",
                    "product": product,
                    "product_url": url,
                }
            )
            found += 1
        print(f"  portfolio {product[:60]}: {found} docs", flush=True)
    return docs


def load_rules() -> dict:
    return json.loads(
        (MANIFEST_DIR / "eligibility-rules.json").read_text(encoding="utf-8")
    )


def apply_rules(item: dict, rules: dict) -> tuple[bool, str]:
    category_n = normalize(item.get("official_category"))
    issuer_n = normalize(item.get("issuer_raw"))
    title_n = normalize(item.get("title"))
    source = item["source"]
    for rule in rules["rules"]:
        if source not in rule["applies_to"]:
            continue
        if rule["type"] == "EXCLUDE":
            match = rule["match"]
            for pattern in match.get("category_regex", []):
                if re.search(normalize(pattern), category_n):
                    return False, rule["id"]
            for pattern in match.get("issuer_regex", []):
                if re.search(normalize(pattern), issuer_n):
                    return False, rule["id"]
    for rule in rules["rules"]:
        if source not in rule["applies_to"]:
            continue
        if rule["type"] == "INCLUDE_ALL":
            return True, rule["id"]
        if rule["type"] == "INCLUDE_CATEGORY":
            for cat in rule["categories"]:
                if normalize(cat) == category_n:
                    return True, rule["id"]
        if rule["type"] == "INCLUDE_TITLE_REGEX":
            for pattern in rule["patterns"]:
                if re.search(normalize(pattern), title_n):
                    return True, rule["id"]
    return False, "NO_RULE_MATCH"


def frame_item(item_id: str, stratum: str, source: str, **fields) -> dict:
    return {
        "frame_item_id": item_id,
        "stratum": stratum,
        "source": source,
        "official_registration_id": fields.get("registration"),
        "publication_date": fields.get("date"),
        "issuer_raw": fields.get("issuer"),
        "official_category": fields.get("category"),
        "title": fields.get("title"),
        "source_locator": fields.get("locator"),
        "instrument_isin": fields.get("isin"),
        "metadata": no_floats(fields.get("metadata")),
    }


def build(args: argparse.Namespace) -> int:
    opener = cnmv.build_opener()
    dfrom = date.fromisoformat(WINDOW["from"])
    dto = date.fromisoformat(WINDOW["to"])
    chunks = month_chunks(dfrom, dto)
    rules = load_rules()
    excluded = json.loads(
        (MANIFEST_DIR / "excluded-known-cases.json").read_text(encoding="utf-8")
    )
    excluded_ids = {
        e["frame_item_id"] for e in excluded["excluded"] if e["frame_item_id"]
    }

    candidates: list[dict] = []
    recon: dict[str, dict] = {}

    def bucket(source: str) -> dict:
        return recon.setdefault(
            source,
            {
                "enumerated": 0,
                "deduplicated": 0,
                "dropped_no_registration": 0,
                "dropped_out_of_window": 0,
                "dropped_duplicate_id": 0,
                "excluded_g0": 0,
                "excluded_by_rule": {},
                "eligible": 0,
            },
        )

    if not args.skip_cnmv:
        for portal, prefix in (("oir", "CNMV-OIR"), ("ip", "CNMV-IP")):
            source = f"CNMV_{portal.upper()}"
            b = bucket(source)
            rows, total = enumerate_cnmv_portal(opener, portal, chunks, args.force)
            b["enumerated"] = total
            b["deduplicated"] = total - len(rows)
            for row in rows:
                reg = row.get("registration_number")
                if not reg:
                    b["dropped_no_registration"] += 1
                    continue
                candidates.append(
                    frame_item(
                        f"{prefix}-{reg}",
                        "MAIN_MARKET",
                        source,
                        registration=reg,
                        date=iso_from_dmy(row.get("date")),
                        issuer=html_mod.unescape(row.get("issuer") or "") or None,
                        category=html_mod.unescape(row.get("category") or "") or None,
                        title=html_mod.unescape(row.get("title") or "") or None,
                        locator=row.get("document_url"),
                        metadata={"time": row.get("time"), "related": row.get("related")},
                    )
                )

    if not args.skip_bme_growth:
        b = bucket("BME_GROWTH_OPERACIONES_FINANCIERAS")
        for kind in BME_TYPES:
            items = fetch_bme_ca(opener, "MTF", "BMEGrowth", kind, args.force, "growth")
            b["enumerated"] += len(items)
            for item in items:
                day = bme_item_date(item)
                if not in_window(day):
                    b["dropped_out_of_window"] += 1
                    continue
                isin = item.get("isin") or item.get("lastISIN") or ""
                name = item.get("company") or item.get("issuerName") or item.get("offeringCompanyName") or ""
                item_id = f"BMEG-{kind}-{isin or normalize(name)[:24]}-{day}"
                candidates.append(
                    frame_item(
                        item_id,
                        "BME_GROWTH_MTF",
                        "BME_GROWTH_OPERACIONES_FINANCIERAS",
                        registration=kind,
                        date=day,
                        issuer=name,
                        category=kind,
                        title=item.get("conceptText") or item.get("typeText") or kind,
                        locator=BME_API.format(kind=kind),
                        isin=isin or None,
                        metadata=item,
                    )
                )

    if not args.skip_portfolio:
        b = bucket("PORTFOLIO_PRODUCT_DOCUMENTS")
        docs = enumerate_portfolio(opener, args.force)
        b["enumerated"] = len(docs)
        for doc in docs:
            if not in_window(doc["date"]):
                b["dropped_out_of_window"] += 1
                continue
            candidates.append(
                frame_item(
                    f"POEX-DOC-{doc['document_id']}",
                    "PORTFOLIO",
                    "PORTFOLIO_PRODUCT_DOCUMENTS",
                    registration=doc["document_id"],
                    date=doc["date"],
                    issuer=doc["product"],
                    category=doc["type"] or doc["section"],
                    title=doc["title"],
                    locator=doc["url"],
                    metadata={"product_url": doc["product_url"], "section": doc["section"]},
                )
            )

    if not args.skip_benchmark:
        benchmark: dict[str, list] = {}
        for kind in BME_TYPES:
            items = fetch_bme_ca(opener, "SIBE", "", kind, args.force, "sibe")
            benchmark[kind] = [
                {"date": bme_item_date(i), "isin": i.get("isin") or i.get("lastISIN"),
                 "issuer": i.get("company") or i.get("issuerName") or i.get("offeringCompanyName"),
                 "raw": i}
                for i in items
            ]
        save_json_raw(
            MANIFEST_DIR / "bme-benchmark.json",
            {
                "manifest_version": "CA_ES_G1_BME_BENCHMARK_V1",
                "role": "EXTERNAL_BENCHMARK_ONLY",
                "availability_note": "BME Exchange publica ~ultimo ano; splits ~ultimo mes.",
                "window": WINDOW,
                "events": benchmark,
            },
        )

    # deduplicacion global por frame_item_id (misma seed vista en dos
    # productos/fuentes)
    deduped: dict[str, dict] = {}
    for item in candidates:
        if item["frame_item_id"] in deduped:
            bucket(item["source"])["dropped_duplicate_id"] += 1
            continue
        deduped[item["frame_item_id"]] = item
    candidates = list(deduped.values())

    # elegibilidad + exclusiones
    frame: list[dict] = []
    no_match_items: list[dict] = []
    for item in candidates:
        b = bucket(item["source"])
        if item["frame_item_id"] in excluded_ids:
            item["eligibility"] = "EXCLUDED_G0_REGRESSION_FIXTURE"
            b["excluded_g0"] += 1
            continue
        ok, rule_id = apply_rules(item, rules)
        if ok:
            item["eligibility"] = f"ELIGIBLE:{rule_id}"
            frame.append(item)
            b["eligible"] += 1
        else:
            b["excluded_by_rule"][rule_id] = (
                b["excluded_by_rule"].get(rule_id, 0) + 1
            )
            item["eligibility"] = f"INELIGIBLE:{rule_id}"
            if rule_id == "NO_RULE_MATCH":
                no_match_items.append(item)

    frame.sort(key=lambda i: i["frame_item_id"])
    frame_hash = hashlib.sha256(
        canonical_bytes(no_floats(frame))
    ).hexdigest()

    # reconciliacion mecanica: enumerated = excluidos + dedup + elegibles
    totals = {
        "enumerated": sum(b["enumerated"] for b in recon.values()),
        "deduplicated": sum(b["deduplicated"] for b in recon.values()),
        "dropped_no_registration": sum(
            b["dropped_no_registration"] for b in recon.values()
        ),
        "dropped_out_of_window": sum(
            b["dropped_out_of_window"] for b in recon.values()
        ),
        "dropped_duplicate_id": sum(
            b["dropped_duplicate_id"] for b in recon.values()
        ),
        "excluded_g0": sum(b["excluded_g0"] for b in recon.values()),
        "excluded_by_rule": sum(
            sum(v.values()) for b in recon.values()
            for v in [b["excluded_by_rule"]]
        ),
        "eligible": len(frame),
    }
    accounted = sum(v for k, v in totals.items() if k != "enumerated")
    difference = totals["enumerated"] - accounted
    save_json_raw(
        MANIFEST_DIR / "frame-reconciliation.json",
        {
            "manifest_version": "CA_ES_G1_FRAME_RECONCILIATION_V1",
            "frozen_at": "2026-09-14",
            "window": WINDOW,
            "per_source": recon,
            "totals": totals,
            "invariant": (
                "enumerated = deduplicated + dropped_no_registration "
                "+ dropped_out_of_window + dropped_duplicate_id "
                "+ excluded_g0 + excluded_by_rule + eligible"
            ),
            "invariant_holds": difference == 0,
            "difference": difference,
        },
    )
    if difference != 0:
        print(f"  RECONCILIATION FAIL difference={difference}", flush=True)
        return 1

    # seleccion + split
    for item in frame:
        item["sample_score"] = sha256_text(
            SAMPLE_NS + item["stratum"] + item["frame_item_id"]
        )
    selected: list[dict] = []
    for stratum, target in STRATUM_TARGETS.items():
        pool = sorted(
            (i for i in frame if i["stratum"] == stratum),
            key=lambda i: i["sample_score"],
        )
        selected.extend(pool[:target])
        if len(pool) < target:
            print(
                f"  COVERAGE GAP stratum={stratum}: {len(pool)} elegibles < {target}",
                flush=True,
            )
    for item in selected:
        item["split_score"] = sha256_text(SPLIT_NS + item["frame_item_id"])
    selected_sorted = sorted(selected, key=lambda i: i["split_score"])
    holdout_ids = {i["frame_item_id"] for i in selected_sorted[:HOLDOUT_COUNT]}
    for item in selected:
        item["partition"] = "HOLDOUT" if item["frame_item_id"] in holdout_ids else "DEV"

    # control negativo: muestra determinista de NO_RULE_MATCH para auditar
    # falsos negativos de las reglas de elegibilidad. No altera el frame.
    audit_dir = REPO_ROOT / "g1" / "adjudication"
    audit_dir.mkdir(parents=True, exist_ok=True)
    negctrl = sorted(
        no_match_items,
        key=lambda i: sha256_text(NEGCTRL_NS + i["frame_item_id"]),
    )[:NEGCTRL_N]
    with (audit_dir / "no-match-audit.jsonl").open("w", encoding="utf-8") as fh:
        for item in negctrl:
            fh.write(
                json.dumps(
                    {
                        "frame_item_id": item["frame_item_id"],
                        "source": item["source"],
                        "stratum": item["stratum"],
                        "publication_date": item["publication_date"],
                        "issuer_raw": item["issuer_raw"],
                        "official_category": item["official_category"],
                        "title": item["title"],
                        "source_locator": item["source_locator"],
                        "audit": {
                            "verdict": None,
                            "verdict_values": ["ACTUAL_CA", "NOT_CA", "AMBIGUOUS"],
                            "reviewer": None,
                            "reviewed_at": None,
                            "note": None,
                        },
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n"
            )

    # adversarial preseleccionado: solo criterios detectables con metadata
    # congelada. Nunca entra en tasas globales; excluye seeds del corpus.
    selected_ids = {i["frame_item_id"] for i in selected}
    source_venue = {
        "CNMV_OIR": "CNMV",
        "CNMV_IP": "CNMV",
        "BME_GROWTH_OPERACIONES_FINANCIERAS": "BME_GROWTH",
        "PORTFOLIO_PRODUCT_DOCUMENTS": "PORTFOLIO",
    }
    issuer_venues: dict[str, set] = {}
    for item in frame:
        issuer_venues.setdefault(normalize(item.get("issuer_raw")), set()).add(
            source_venue.get(item["source"], item["source"])
        )
    adv_candidates: list[dict] = []
    for item in frame:
        if item["frame_item_id"] in selected_ids:
            continue
        title_n = normalize(item.get("title"))
        category_n = normalize(item.get("official_category"))
        related = (item.get("metadata") or {}).get("related") or []
        criteria = []
        for criterion, patterns in ADV_METADATA_TITLE_PATTERNS.items():
            if any(
                re.search(normalize(p), title_n) or re.search(normalize(p), category_n)
                for p in patterns
            ):
                criteria.append(criterion)
        if related and "EXPLICIT_REVISION" not in criteria:
            criteria.append("EXPLICIT_REVISION")
        if len(issuer_venues.get(normalize(item.get("issuer_raw")), set())) > 1:
            criteria.append("MULTI_VENUE")
        if criteria:
            adv_candidates.append(
                {"item": item, "criteria": sorted(set(criteria))}
            )
    adv_candidates.sort(
        key=lambda e: sha256_text(ADV_NS + e["item"]["frame_item_id"])
    )
    adv_entries = []
    for rank, entry in enumerate(adv_candidates[:ADV_N], 1):
        item = entry["item"]
        adv_entries.append(
            {
                "registry_id": f"ADV-{rank:03d}",
                "entry_class": "PRESELECTED_ADVERSARIAL",
                "sealed_until": "PARSER_FREEZE",
                "criteria": entry["criteria"],
                "frame_item_id": item["frame_item_id"],
                "source_refs": [item["official_registration_id"]],
                "rationale": "Seleccionado por SHA256(CA_ES_G1_ADV_V1 + frame_item_id), menor score entre candidatos por metadata congelada.",
                "added_by": "build_g1_frame.py",
                "added_at": "2026-09-14",
            }
        )
    save_json_raw(
        MANIFEST_DIR / "adversarial-registry.json",
        {
            "manifest_version": "CA_ES_G1_ADVERSARIAL_V1",
            "frozen_at": "2026-09-14",
            "selection": "PURPOSIVE_REGISTRY",
            "excluded_from_global_rates": True,
            "counts": {
                "unique_cases": len(adv_entries),
                "criterion_assignments": sum(
                    len(e["criteria"]) for e in adv_entries
                ),
            },
            "entry_classes": {
                "PRESELECTED_ADVERSARIAL": "Seleccionado antes de DEV por criterio de metadata congelada; cuenta como evaluacion adversarial. Sellado hasta PARSER_FREEZE.",
                "ADVERSARIAL_DEV": "Usado durante desarrollo; deja de contar como evaluacion adversarial.",
                "KNOWN_PRE_G1": "Caracteristica conocida antes de G1 pero no detectable por metadata; regression fixture, no observacion nueva.",
                "DISCOVERED_ADVERSARIAL": "Encontrado durante DEV; regression fixture futuro, NO cuenta como evaluacion adversarial G1.",
            },
            "criteria_metadata_detectable": sorted(ADV_METADATA_TITLE_PATTERNS)
            + ["MULTI_VENUE"],
            "criteria_content_required": ADV_CONTENT_REQUIRED,
            "entries": adv_entries,
        },
    )

    excluded_by_rule_flat = {
        s: b["excluded_by_rule"] for s, b in recon.items() if b["excluded_by_rule"]
    }

    frame_doc = {
        "frame_version": "CA_ES_G1_SAMPLING_FRAME_V2",
        "frozen_at": "2026-09-14",
        "supersedes": "CA_ES_G1_SAMPLING_FRAME_V1",
        "status": "FROZEN",
        "window": WINDOW,
        "selection_rule": "SHA256(CA_ES_G1_SAMPLE_V1 + stratum + frame_item_id), sort, take N",
        "quota_policy": "No se fuerzan cuotas; la ausencia es un resultado de cobertura.",
        "source_snapshot": {
            "retrieved_at": "2026-09-14",
            "raw_dir": "g1/corpus/raw/frame/",
            "raw_row_counts": {
                s: b["enumerated"] for s, b in recon.items()
            },
        },
        "strata": [
            {
                "id": s,
                "target": t,
                "eligible": sum(1 for i in frame if i["stratum"] == s),
                "selected": sum(
                    1 for i in selected if i["stratum"] == s
                ),
            }
            for s, t in STRATUM_TARGETS.items()
        ]
        + [
            {
                "id": "ADVERSARIAL",
                "target": 10,
                "eligible": 0,
                "selected": 0,
                "notes": "Registro purposive; ver adversarial-registry.json",
            }
        ],
        "excluded_by_rule": excluded_by_rule_flat,
        "items": frame,
    }
    save_json_raw(MANIFEST_DIR / "sampling-frame.json", frame_doc)
    (MANIFEST_DIR / "sampling-frame.sha256").write_text(
        f"{frame_hash}  sampling-frame.items\n", encoding="utf-8"
    )

    corpus_doc = {
        "corpus_version": "CA_ES_G1_CORPUS_V1",
        "frozen_at": "2026-09-14",
        "frame_sha256": frame_hash,
        "sampling_algorithm": "sha256_hex(sample_namespace + stratum + frame_item_id); sort asc; take N",
        "sampling_namespace": SAMPLE_NS,
        "split_algorithm": "sha256_hex(split_namespace + frame_item_id); sort asc; first 15 = HOLDOUT",
        "split_namespace": SPLIT_NS,
        "holdout_count": HOLDOUT_COUNT,
        "selected": [
            {
                "frame_item_id": i["frame_item_id"],
                "stratum": i["stratum"],
                "sample_score": i["sample_score"],
                "split_score": i["split_score"],
                "partition": i["partition"],
            }
            for i in sorted(selected, key=lambda x: x["frame_item_id"])
        ],
        "dedup_rule": "si dos seeds resultan ser la misma CA por evidencia determinista: conservar mejor sample_score, rellenar con el siguiente del frame, registrar.",
    }
    save_json_raw(MANIFEST_DIR / "corpus.json", corpus_doc)

    dev_holdout = json.loads(
        (MANIFEST_DIR / "dev-holdout.json").read_text(encoding="utf-8")
    )
    dev_holdout["status"] = "FROZEN_POPULATED"
    dev_holdout["frame_sha256"] = frame_hash
    dev_holdout["policy"]["holdout_content_sealed_until"] = "PARSER_FREEZE"
    dev_holdout["policy"]["no_manual_holdout_inspection"] = True
    dev_holdout["policy"]["sealed_sets_until_parser_freeze"] = [
        "holdout",
        "PRESELECTED_ADVERSARIAL",
    ]
    dev_holdout["policy"]["baseline_rule"] = (
        "first_run = mismo parser commit para los 25 DEV; "
        "sin cambios de codigo entre ejecuciones"
    )
    dev_holdout["policy"]["generic_fix_rule"] = (
        "un fix cuya condicion sea identificador/emisor/documento "
        "especifico del seed queda rechazado"
    )
    dev_holdout["policy"]["record_runs_per_event"] = [
        "first_run_result",
        "final_run_result",
        "reason_for_change",
    ]
    dev_holdout["development"] = sorted(
        i["frame_item_id"] for i in selected if i["partition"] == "DEV"
    )
    dev_holdout["holdout"] = sorted(
        i["frame_item_id"] for i in selected if i["partition"] == "HOLDOUT"
    )
    save_json_raw(MANIFEST_DIR / "dev-holdout.json", dev_holdout)

    print(
        json.dumps(
            {
                "frame_items": len(frame),
                "frame_sha256": frame_hash,
                "selected": len(selected),
                "holdout": len(holdout_ids),
                "negctrl_sample": len(negctrl),
                "adversarial_preselected": len(adv_entries),
                "reconciliation": totals,
                "excluded_by_rule": excluded_by_rule_flat,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--skip-cnmv", action="store_true")
    parser.add_argument("--skip-bme-growth", action="store_true")
    parser.add_argument("--skip-portfolio", action="store_true")
    parser.add_argument("--skip-benchmark", action="store_true")
    return build(parser.parse_args(argv))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
