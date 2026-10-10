import zlib

import pytest

from ghostbrain.ontology import triage
from ghostbrain.ontology.extract import CandidateIn
from ghostbrain.ontology.store import Store


class FakeEmbedder:
    """Bag-of-words vectors: identical statements → cosine 1, unrelated → ~0."""
    def encode(self, texts):
        out = []
        for t in texts:
            v = [0.0] * 64
            for w in t.lower().split():
                v[zlib.crc32(w.encode()) % 64] += 1.0
            out.append(v)
        return out


def _c(statement="Today policies lapse on day 31.", value="31", conf=0.6):
    return CandidateIn(kind="Rule", name="lapse day", statement=statement, value=value,
                       existing_uid=None, quote="day 31", locator="", confidence=conf)


class ValueBlindEmbedder:
    """Same vector for every text, so only the value check can tell candidates apart."""
    def encode(self, texts):
        return [[1.0, 0.0] for _ in texts]


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "o.db")
    yield s
    s.close()


def test_new_then_duplicate_from_other_artefact_merges(store):
    e = FakeEmbedder()
    kind, cid = triage.triage(store, "p1", "a1", _c(), e)
    assert kind == "new" and store.open_items("p1")[0]["candidate_id"] == cid
    kind2, cid2 = triage.triage(store, "p1", "a2", _c(conf=0.5), e)
    assert (kind2, cid2) == ("merged", cid)
    assert [ev["aid"] for ev in store.evidence(cid)] == ["a1", "a2"]
    assert store.candidate(cid)["confidence"] == pytest.approx(1 - 0.4 * 0.5)
    assert len(store.open_items("p1")) == 1


def test_duplicate_from_same_artefact_does_not_inflate_confidence(store):
    e = FakeEmbedder()
    _, cid = triage.triage(store, "p1", "a1", _c(conf=0.6), e)
    triage.triage(store, "p1", "a1", _c(conf=0.7), e)
    assert store.candidate(cid)["confidence"] == pytest.approx(0.7)


def test_near_rejected_is_dropped(store):
    e = FakeEmbedder()
    _, cid = triage.triage(store, "p1", "a1", _c(), e)
    store.set_candidate_status(cid, "rejected")
    assert triage.triage(store, "p1", "a9", _c(), e) == ("dropped", None)


def test_unrelated_is_new(store):
    e = FakeEmbedder()
    triage.triage(store, "p1", "a1", _c(), e)
    kind, _ = triage.triage(store, "p1", "a1", _c(statement="Reinstatement allowed for 45 days", value="45"), e)
    assert kind == "new"


def test_pack_roundtrip_and_cosine():
    v = [1.0, 0.0, 2.5]
    assert triage.unpack(triage.pack(v)) == pytest.approx(v)
    assert triage.cosine([1, 0], [1, 0]) == pytest.approx(1.0)
    assert triage.cosine([1, 0], [0, 0]) == 0.0


def test_rejected_value_does_not_suppress_different_value(store):
    e = ValueBlindEmbedder()
    _, cid = triage.triage(store, "p1", "a1", _c(value="30"), e)
    store.set_candidate_status(cid, "rejected")
    kind, _ = triage.triage(store, "p1", "a2", _c(value="31"), e)
    assert kind == "new"


def test_merge_picks_same_value_row_even_if_other_value_scores_higher(store):
    e = ValueBlindEmbedder()
    # The 30-row is an exact match for the query vector; the 31-row is slightly lower
    # but still above TAU_DUP. The merge must still go to the 31-row.
    store.add_candidate("p1", kind="Rule", name="lapse day", statement="s", value="30",
                        existing_uid=None, relations=[], confidence=0.5,
                        extractor_version="x", embedding=triage.pack([1.0, 0.0]))
    cid31 = store.add_candidate("p1", kind="Rule", name="lapse day", statement="s", value="31",
                                existing_uid=None, relations=[], confidence=0.5,
                                extractor_version="x", embedding=triage.pack([0.95, 0.31]))
    kind, cid = triage.triage(store, "p1", "a2", _c(value="31"), e)
    assert (kind, cid) == ("merged", cid31)


def test_merge_from_same_artefact_does_not_duplicate_evidence(store):
    e = FakeEmbedder()
    _, cid = triage.triage(store, "p1", "a1", _c(conf=0.6), e)
    triage.triage(store, "p1", "a1", _c(conf=0.7), e)
    assert [ev["aid"] for ev in store.evidence(cid)] == ["a1"]
