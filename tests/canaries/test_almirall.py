from __future__ import annotations

from ca_es.gates import evaluate_gates
from ca_es.pipeline import run_pipeline


def test_almirall_is_one_event_with_two_revisions(events_by_type):
    events = events_by_type["SCRIP_DIVIDEND"]
    assert len(events) == 1
    event = events[0]
    assert len(event["revisions"]) == 2
    generations = {rev["generation"] for rev in event["revisions"]}
    assert generations == {0, 1}
    successor = next(rev for rev in event["revisions"] if rev["generation"] == 1)
    predecessor = next(rev for rev in event["revisions"] if rev["generation"] == 0)
    assert successor["supersedes_revision_id"] == predecessor["revision_id"]
    assert successor["evidence"]


def test_almirall_ratio_changes_across_revisions(events_by_type, run_result, facts_for):
    event = events_by_type["SCRIP_DIVIDEND"][0]
    ratios: dict[int, str] = {}
    for revision in event["revisions"]:
        for fact in facts_for(run_result, event):
            if (
                fact["revision_id"] == revision["revision_id"]
                and fact["field_path"] == "ratio.rights_per_new_share"
            ):
                ratios[revision["generation"]] = fact["value"]["normalized"]
    assert ratios[0] == "55"
    assert ratios[1] == "65"


def test_almirall_supersession_gate_passes(policy, run_result, repo_root, resolver):
    second = run_pipeline(repo_root, resolver=resolver, run_id="b")
    report = evaluate_gates(run_result, policy=policy, second_run=second)
    assert report["gates"]["EXPLICIT_SUPERSESSION_PROVEN"]["status"] == "PASS"
    assert report["gates"]["AMENDMENT_CHAIN_PROVEN"]["status"] == "PASS"
