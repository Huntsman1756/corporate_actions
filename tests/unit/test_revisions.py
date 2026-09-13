from __future__ import annotations

from ca_es.revisions import MemberDocument, build_revisions
from ca_es.sources.parsers.base import DocumentReference
from ca_es.vocab import DocumentRelation


def _member(suffix: str) -> MemberDocument:
    return MemberDocument(
        candidate_id=f"cand-{suffix}",
        document_id=f"doc-{suffix}",
        source_id="CNMV",
        official_document_id=f"CNMV-{suffix}",
    )


def test_document_support_is_not_a_revision():
    members = [_member("A"), _member("B")]
    revisions = build_revisions("canon-1", members, {})
    assert len(revisions) == 1
    assert set(revisions[0].document_ids) == {"doc-A", "doc-B"}


def test_explicit_correction_creates_revision():
    members = [_member("A"), _member("B")]
    references = {
        "doc-B": [
            DocumentReference(
                relation=DocumentRelation.SUPERSEDES.value,
                target_official_document_id="CNMV-A",
                target_source_id="CNMV",
                evidence_locator="B corrige a A",
            )
        ]
    }
    revisions = build_revisions("canon-1", members, references)
    assert len(revisions) == 2
    assert revisions[0].generation == 0
    assert revisions[1].generation == 1
    assert revisions[1].supersedes_revision_id == revisions[0].revision_id
    assert revisions[1].evidence == ("B corrige a A",)


def test_revision_identity_order_independent():
    members = [_member("A"), _member("B")]
    references = {
        "doc-B": [
            DocumentReference(
                relation=DocumentRelation.SUPERSEDES.value,
                target_official_document_id="CNMV-A",
                target_source_id="CNMV",
                evidence_locator="B corrige a A",
            )
        ]
    }
    forward = build_revisions("canon-1", members, references)
    backward = build_revisions("canon-1", list(reversed(members)), references)
    assert [r.revision_id for r in forward] == [r.revision_id for r in backward]
