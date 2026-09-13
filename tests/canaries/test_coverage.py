from __future__ import annotations

from ca_es.canonical import strict_json_loads


def test_p3_coverage_investigation_is_valid(repo_root):
    raw = strict_json_loads(
        (repo_root / "docs/gates/p3-cnmv-channel-coverage.json").read_text(
            encoding="utf-8"
        )
    )
    assert raw["investigation"] == "CNMV_CHANNEL_COVERAGE_P3"
    assert raw["result"] in {"PROVEN", "NOT_PROVEN", "CONTRADICTED", "INCONCLUSIVE"}
