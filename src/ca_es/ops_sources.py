"""P9 — Orquestacion de source refresh sobre el state store P7.

docs/p9/p91-source-observations.md + docs/p9/p92-discovery-state.md.

Invariantes:

* failure de una fuente queda aislado (source-level result propio);
* el checkpoint SOLO avanza tras discovery+fetch+persistencia durable;
* discovery incompleto => PARTIAL y el checkpoint no avanza;
* misma identidad + bytes distintos => CONTENT_CHANGED, nunca
  overwrite; mismo sha => SAME_BYTES (una blob, otra observacion);
* ausencia en una enumeracion NUNCA implica desaparicion;
* source-policy.json es autoritativo: ingestion_status distinto de
  ACTIVE no se adquiere; raw_storage se propaga al metadata.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime

from .semantic_hash import byte_sha256, semantic_sha256

CONTRACT_OBSERVATION = "CA_ES_SOURCE_OBSERVATION_V1"
CONTRACT_REFRESH = "CA_ES_SOURCE_REFRESH_V1"

# Retrieval / change status (P9.1)
RETRIEVED = "RETRIEVED"
FETCH_FAILED = "FETCH_FAILED"
DISCOVERY_ONLY_STATUS = "DISCOVERY_ONLY"

CHANGE_NEW = "NEW_DOCUMENT"
CHANGE_SAME = "SAME_BYTES"
CHANGE_CHANGED = "CONTENT_CHANGED"
CHANGE_FAILED = "FETCH_FAILED"
CHANGE_DISCOVERY = "DISCOVERY_ONLY"

# Source-level result (P9.1)
SRC_SUCCESS = "SUCCESS"
SRC_PARTIAL = "PARTIAL"
SRC_FAILED = "FAILED"
SRC_UNCHANGED = "UNCHANGED"

DEFAULT_SOURCES_CONFIG: dict = {
    "enabled": True,
    "politeness_seconds": 0.35,
    "timeout_seconds": 90,
    "retries": 3,
    "max_bytes": 64 * 1024 * 1024,
    "adapters": {
        "cnmv_oir": {
            "adapter": "cnmv", "portal": "oir",
            "source_id": "CNMV", "surface_id": "OIR",
            "enabled": True, "required": False,
            "desde": "2024-01-01", "overlap_days": 14,
            "refetch_known": False,
        },
        "cnmv_ip": {
            "adapter": "cnmv", "portal": "ip",
            "source_id": "CNMV", "surface_id": "IP",
            "enabled": True, "required": False,
            "desde": "2024-01-01", "overlap_days": 14,
            "refetch_known": False,
        },
        "bme_growth": {
            "adapter": "bme",
            "source_id": "BME_GROWTH", "surface_id": "CORPORATE_ACTIONS",
            "enabled": True, "required": False,
        },
        "portfolio": {
            "adapter": "portfolio",
            "source_id": "PORTFOLIO_STOCK_EXCHANGE",
            "surface_id": "PORTFOLIO_MARKET",
            "enabled": True, "required": False,
        },
    },
}


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_adapter(name: str, cfg: dict):
    """Instancia el adapter live correspondiente a ``cfg``."""
    if name == "cnmv":
        from .sources.live.cnmv import CnmvAdapter
        return CnmvAdapter(cfg["portal"])
    if name == "bme":
        from .sources.live.bme import BmeAdapter
        return BmeAdapter()
    if name == "portfolio":
        from .sources.live.portfolio import PortfolioAdapter
        return PortfolioAdapter()
    raise ValueError(f"adapter desconocido: {name}")


def build_fetcher(name: str, cfg: dict, net: dict):
    """Fetcher urllib por adapter (CNMV necesita sesion caliente)."""
    kwargs = {
        "timeout": net.get("timeout_seconds", 90),
        "retries": net.get("retries", 3),
        "politeness": net.get("politeness_seconds", 0.35),
        "max_bytes": net.get("max_bytes", 64 * 1024 * 1024),
    }
    if name == "cnmv":
        from .sources.live.cnmv import live_fetcher
        return live_fetcher(cfg["portal"], **kwargs)
    if name == "bme":
        from .sources.live.bme import live_fetcher
        return live_fetcher(**kwargs)
    if name == "portfolio":
        from .sources.live.portfolio import live_fetcher
        return live_fetcher(**kwargs)
    raise ValueError(f"adapter desconocido: {name}")


def _observation_id(source_id: str, doc_id: str, refresh_id: str,
                    ordinal: int) -> str:
    return semantic_sha256({
        "k": "obs", "source": source_id, "doc": doc_id,
        "refresh": refresh_id, "ordinal": ordinal})


@dataclass
class SourceResult:
    adapter_name: str
    source_id: str
    surface_id: str
    status: str = SRC_UNCHANGED
    discovered: int = 0
    new_documents: int = 0
    unchanged: int = 0
    changed: int = 0
    fetch_failures: int = 0
    discovery_only: int = 0
    pages_fetched: int = 0
    pagination_complete: bool = True
    required: bool = False
    error: str | None = None
    checkpoint_advanced: bool = False
    detail: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "adapter": self.adapter_name,
            "source_id": self.source_id,
            "surface_id": self.surface_id,
            "status": self.status,
            "discovered": self.discovered,
            "new_documents": self.new_documents,
            "unchanged": self.unchanged,
            "changed": self.changed,
            "fetch_failures": self.fetch_failures,
            "discovery_only": self.discovery_only,
            "pages_fetched": self.pages_fetched,
            "pagination_complete": self.pagination_complete,
            "required": self.required,
            "checkpoint_advanced": self.checkpoint_advanced,
            "error": self.error,
            "detail": self.detail,
        }


def _run_one_source(state, conn, adapter_name: str, cfg: dict,
                    adapter, fetch, refresh_id: str, now: str,
                    policy_sources: dict) -> SourceResult:
    """Discovery + fetch + persistencia para un adapter. Aislado."""
    source_id = cfg["source_id"]
    surface_id = cfg["surface_id"]
    result = SourceResult(
        adapter_name=adapter_name, source_id=source_id,
        surface_id=surface_id,
        required=bool(cfg.get("required")))

    policy = policy_sources.get(source_id) or {}
    if policy.get("ingestion_status") not in (None, "ACTIVE"):
        result.status = SRC_FAILED
        result.error = (
            f"POLICY_INGESTION_STATUS:"
            f"{policy.get('ingestion_status')}")
        return result

    checkpoint = state.get_checkpoint(conn, source_id, surface_id)
    kwargs: dict = {"checkpoint": checkpoint}
    if adapter_name.startswith("cnmv"):
        desde = cfg.get("desde") or "2024-01-01"
        hasta = cfg.get("hasta") or now[:10]
        kwargs.update(
            desde=desde, hasta=hasta,
            overlap_days=int(cfg.get("overlap_days", 14)))
    if adapter_name == "bme_growth" and cfg.get("kinds"):
        kwargs["kinds"] = tuple(cfg["kinds"])

    try:
        discovery = adapter.discover(fetch, **kwargs)
    except Exception as exc:  # noqa: BLE001 — aislado por fuente
        result.status = SRC_FAILED
        result.error = f"{exc.__class__.__name__}:{exc}"[:300]
        return result

    result.pages_fetched = discovery.pages_fetched
    result.pagination_complete = discovery.complete
    result.discovered = len(discovery.documents)
    if discovery.error:
        result.error = discovery.error

    refetch_known = bool(cfg.get("refetch_known"))
    ordinal = 0
    fetch_failures: list[str] = []
    for doc in discovery.documents:
        ordinal += 1
        obs_id = _observation_id(
            source_id, doc.source_document_id, refresh_id, ordinal)
        known = state.get_source_document(
            conn, source_id, doc.source_document_id)
        obs = {
            "observation_id": obs_id,
            "refresh_id": refresh_id,
            "source_id": source_id,
            "surface_id": surface_id,
            "source_document_id": doc.source_document_id,
            "source_locator": doc.locator,
            "discovered_at": now,
            "retrieved_at": None,
            "retrieval_status": None,
            "http_status": None,
            "media_type": doc.media_type,
            "content_sha256": None,
            "byte_length": None,
            "change_status": None,
            "source_metadata": doc.metadata,
        }
        try:
            if doc.inline_content is not None:
                payload = doc.inline_content
                http_status = None
                media_type = doc.media_type
            elif known is not None and not refetch_known:
                # Documento ya observado: basta la re-observacion de
                # identidad — sin bytes nuevos no hay que descargar.
                obs["change_status"] = CHANGE_DISCOVERY
                obs["retrieval_status"] = DISCOVERY_ONLY_STATUS
                state.insert_source_observation(conn, obs)
                result.discovery_only += 1
                state.upsert_source_document(conn, {
                    "source_id": source_id, "surface_id": surface_id,
                    "source_document_id": doc.source_document_id,
                    "last_seen_at": now,
                    "publication_date": doc.publication_date,
                    "latest_locator": doc.locator,
                    "metadata": doc.metadata})
                continue
            elif doc.locator is None:
                raise ValueError("NO_LOCATOR")
            else:
                response = fetch(
                    doc.locator, referer=doc.locator)
                payload = response.content
                http_status = response.status
                media_type = response.media_type or doc.media_type
        except Exception as exc:  # noqa: BLE001 — fetch aislado
            obs["change_status"] = CHANGE_FAILED
            obs["retrieval_status"] = FETCH_FAILED
            obs["source_metadata"] = {
                **doc.metadata,
                "error": f"{exc.__class__.__name__}:{exc}"[:200]}
            state.insert_source_observation(conn, obs)
            result.fetch_failures += 1
            fetch_failures.append(doc.source_document_id)
            continue

        blob = state.store_blob(payload)
        sha = blob["sha256"]
        obs.update(
            retrieved_at=now, retrieval_status=RETRIEVED,
            http_status=http_status, media_type=media_type,
            content_sha256=sha, byte_length=blob["byte_length"])
        if known is None:
            obs["change_status"] = CHANGE_NEW
            result.new_documents += 1
        elif known.get("latest_content_sha256") == sha:
            obs["change_status"] = CHANGE_SAME
            result.unchanged += 1
        else:
            obs["change_status"] = CHANGE_CHANGED
            result.changed += 1
        obs["source_metadata"] = {
            **doc.metadata,
            "raw_storage": policy.get("raw_storage"),
            "redistribution": policy.get("redistribution"),
        }
        state.insert_source_observation(conn, obs)
        state.upsert_source_document(conn, {
            "source_id": source_id, "surface_id": surface_id,
            "source_document_id": doc.source_document_id,
            "first_seen_at": known and known.get("first_seen_at") or now,
            "last_seen_at": now,
            "publication_date": doc.publication_date,
            "latest_content_sha256": sha,
            "chosen_content_sha256":
                known and known.get("chosen_content_sha256"),
            "latest_locator": doc.locator,
            "metadata": doc.metadata})

    # Checkpoint: solo si discovery+fetches completos.
    if discovery.complete and not fetch_failures:
        state.upsert_checkpoint(
            conn, source_id, surface_id, discovery.cursor, now)
        result.checkpoint_advanced = True

    if discovery.error or fetch_failures:
        result.status = SRC_PARTIAL
    elif (result.new_documents or result.changed
          or result.discovery_only):
        result.status = SRC_SUCCESS
    elif result.discovered:
        result.status = SRC_SUCCESS
    else:
        result.status = SRC_UNCHANGED
    result.detail = {
        "dropped_no_identity": discovery.dropped_no_identity,
        "fetch_failures": fetch_failures[:20],
        "cursor": discovery.cursor,
    }
    return result


def run_source_refresh(state, conn, sources_cfg: dict, *,
                       fetchers: dict | None = None, now: str | None = None,
                       policy: dict | None = None) -> dict:
    """Ejecuta un refresh de fuentes y persiste estado durable.

    ``fetchers``: mapa adapter_name -> fetch(url, referer) inyectable;
    ``None`` construye los fetchers urllib reales.
    Devuelve el doc ``CA_ES_SOURCE_REFRESH_V1`` (tambien persistido en
    ``source_refreshes`` y como artefacto content-addressed).
    """
    now = now or _now_iso()
    sources_cfg = sources_cfg or {}
    # ``adapters: {}`` explicito = sin fuentes (UNCHANGED), no "usar
    # el default": distinguir None de vacio.
    adapters_cfg = sources_cfg.get("adapters")
    if adapters_cfg is None:
        adapters_cfg = DEFAULT_SOURCES_CONFIG["adapters"]
    net = {
        "timeout_seconds": sources_cfg.get("timeout_seconds", 90),
        "retries": sources_cfg.get("retries", 3),
        "politeness_seconds": sources_cfg.get("politeness_seconds", 0.35),
        "max_bytes": sources_cfg.get(
            "max_bytes", 64 * 1024 * 1024),
    }
    policy_sources = ((policy or {}).get("sources")) or {}

    enabled = [
        (name, cfg) for name, cfg in sorted(adapters_cfg.items())
        if cfg.get("enabled", True)]
    # refresh_id = identidad de EJECUCION: incluye started_at, por lo
    # que NO puede ser semantic_sha256 (que lo excluye por politica).
    seed = {"schema": CONTRACT_REFRESH, "started_at": now,
            "adapters": [n for n, _ in enabled]}
    refresh_id = "SRF-" + byte_sha256(
        json.dumps(seed, sort_keys=True).encode("utf-8"))[:24]

    results: list[SourceResult] = []
    for name, cfg in enabled:
        adapter_name = cfg.get("adapter", name)
        try:
            adapter = build_adapter(adapter_name, cfg)
            fetch = (fetchers or {}).get(name)
            if fetch is None:
                fetch = build_fetcher(adapter_name, cfg, net)
        except Exception as exc:  # noqa: BLE001 — aislado
            results.append(SourceResult(
                adapter_name=name,
                source_id=cfg.get("source_id", "?"),
                surface_id=cfg.get("surface_id", "?"),
                status=SRC_FAILED,
                required=bool(cfg.get("required")),
                error=f"{exc.__class__.__name__}:{exc}"[:300]))
            continue
        results.append(_run_one_source(
            state, conn, name, cfg, adapter, fetch,
            refresh_id, now, policy_sources))

    completed = _now_iso()
    statuses = {r.status for r in results}
    if not results:
        overall = SRC_UNCHANGED
    elif statuses == {SRC_FAILED}:
        overall = SRC_FAILED
    elif SRC_FAILED in statuses or SRC_PARTIAL in statuses:
        overall = SRC_PARTIAL
    elif statuses == {SRC_UNCHANGED}:
        overall = SRC_UNCHANGED
    else:
        overall = SRC_SUCCESS

    summary = {
        "adapters_run": len(results),
        "new_documents": sum(r.new_documents for r in results),
        "changed": sum(r.changed for r in results),
        "unchanged": sum(r.unchanged for r in results),
        "fetch_failures": sum(r.fetch_failures for r in results),
        "discovery_only": sum(r.discovery_only for r in results),
        "checkpoints_advanced": sum(
            1 for r in results if r.checkpoint_advanced),
    }
    doc = {
        "schema": CONTRACT_REFRESH,
        "refresh_id": refresh_id,
        "started_at": now,
        "completed_at": completed,
        "status": overall,
        "source_results": [r.as_dict() for r in results],
        "summary": summary,
    }
    state.insert_source_refresh(conn, {
        "refresh_id": refresh_id, "started_at": now,
        "completed_at": completed, "status": overall,
        "summary": summary})
    state.store_artifact(conn, doc, CONTRACT_REFRESH, "V1")
    return doc
