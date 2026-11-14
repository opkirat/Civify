"""Pipeline status tests on a small synthetic record (offline)."""

from civify import db, workflow


def rec(claims, participation=None):
    return {"item_id": "X", "official_url": "https://example.invalid/x", "claims": claims,
            "participation": participation or {"council_has_decided": True}}


ITEM = {"documents": [{"filename": "r.pdf", "doc_type": "staff_report", "evidence": ""}]}
READY = {"sentence": "The site is on Queen St.", "quote": "q" * 50, "verified": True, "lane": "ready", "reasons": [], "meaning": {"verdict": "supported"}, "source_sha256": "a"}
REVIEW = {**READY, "sentence": "Staff recommend approval.", "lane": "review", "reasons": ["states a recommendation or decision"]}
BLOCKED = {**READY, "sentence": "Wrong.", "verified": False, "reason": "quote not found", "lane": "blocked", "reasons": ["code check failed"]}


def states(st):
    return {s["key"]: s["state"] for s in st["steps"]}


def test_fresh_item_needs_attention_with_links():
    st = workflow.status(rec([READY, REVIEW, BLOCKED]), ITEM, {})
    assert {k: st["counts"][k] for k in ("ready", "review", "blocked", "stale", "approved", "decided", "total")} == \
        {"ready": 1, "review": 1, "blocked": 1, "stale": 0, "approved": 0, "decided": 0, "total": 3}
    assert states(st)["checked"] == "attention" and states(st)["reviewed"] == "attention" and states(st)["published"] == "todo"
    texts = " ".join(a["text"] for a in st["attention"])
    assert "Sentence 3 failed the source check" in texts and "Sentence 2 needs a look" in texts and "1 sentence(s) passed every check" in texts
    assert any(a["href"] == "/staff/X#claim-1" for a in st["attention"])


def test_all_decided_and_published_needs_nothing():
    r = rec([READY])
    reviews = {0: {"status": "approved", "claim_hash": db.claim_hash(READY)}}
    pub = {"version": 1, "claims": [READY]}
    st = workflow.status(r, ITEM, reviews, pub, [], {"added": 0, "removed": 0})
    assert states(st)["reviewed"] == "done" and states(st)["published"] == "done" and st["attention"] == []


def test_approved_but_unpublished_asks_to_publish():
    reviews = {0: {"status": "approved", "claim_hash": db.claim_hash(READY)}}
    st = workflow.status(rec([READY]), ITEM, reviews, None, [], {"added": 1, "removed": 0})
    assert states(st)["published"] == "attention" and "Publish version 1" in st["attention"][0]["text"]


def test_escalation_is_listed_first_with_its_note():
    esc = [{"claim_index": 1, "raised_by": "Clerk A", "note": "check with legal"}]
    st = workflow.status(rec([READY, REVIEW]), ITEM, {}, None, esc, None)
    assert "escalated by Clerk A" in st["attention"][0]["text"] and "check with legal" in st["attention"][0]["text"]
    assert not any("Sentence 2 needs a look" in a["text"] for a in st["attention"])


def test_stale_approval_is_flagged():
    reviews = {0: {"status": "approved", "claim_hash": "old"}}
    st = workflow.status(rec([READY]), ITEM, reviews)
    assert st["counts"]["stale"] == 1 and "changed since it was reviewed" in st["attention"][0]["text"]


def test_unrecognised_document_and_missing_participation_rule_are_flagged():
    item = {"documents": ITEM["documents"] + [{"filename": "odd.pdf", "doc_type": "unknown", "evidence": "?"}]}
    st = workflow.status(rec([READY], {"council_has_decided": False}), item, {})
    texts = " ".join(a["text"] for a in st["attention"])
    assert "odd.pdf was not recognised" in texts and "Confirm on the official item page" in texts
    assert states(st)["documents"] == "attention"


def test_no_triage_falls_back_to_review():
    plain = {k: v for k, v in READY.items() if k not in ("lane", "reasons", "meaning")}
    st = workflow.status(rec([plain]), ITEM, {})
    assert st["counts"]["review"] == 1 and states(st)["meaning"] == "attention"
