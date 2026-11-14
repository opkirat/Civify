"""AI summary: written only from live sentences, checked by code and a guardrail, withdrawn when a source goes."""

import json

import pytest

from civify import db, summary

LIVE = ["Staff recommend designating the church at 19 Don Ridge Drive.",
        "The church was built in 1862 in the Gothic Revival style.",
        "Toronto Preservation Board will consider the item on November 16, 2026."]


def writes(*sentences):
    return lambda _p: json.dumps({"sentences": [{"text": t, "uses": u} for t, u in sentences]})


def checks(*verdicts):
    return lambda _p: json.dumps({"results": [{"index": i, "verdict": v, "issue": "x" if v == "hold" else ""} for i, v in enumerate(verdicts, 1)]})


@pytest.fixture
def tmp_data(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA", tmp_path)
    (tmp_path / "X").mkdir()
    return tmp_path


def test_passing_summary_is_shown_and_cites_live_sentences(tmp_data, monkeypatch):
    monkeypatch.setattr(summary, "WRITE_CALL", writes(("Staff recommend protecting an 1862 church.", [1, 2])))
    monkeypatch.setattr(summary, "CHECK_CALL", checks("approve"))
    s = summary.refresh("X", LIVE)
    assert s["status"] == "ok" and s["sentences"][0]["uses"] == LIVE[:2]
    assert summary.for_residents("X", LIVE)["sentences"][0]["text"].startswith("Staff recommend")


def test_number_not_in_cited_sentences_is_held_without_asking_the_guardrail(tmp_data, monkeypatch):
    monkeypatch.setattr(summary, "WRITE_CALL", writes(("The church is 165 years old.", [2])))
    monkeypatch.setattr(summary, "CHECK_CALL", lambda _p: pytest.fail("guardrail should not run"))
    s = summary.refresh("X", LIVE)
    assert s["status"] == "held" and "165" in s["issues"][0] and s["attempts"] == 2
    assert summary.for_residents("X", LIVE) is None


def test_guardrail_hold_withholds_the_whole_summary_after_one_repair(tmp_data, monkeypatch):
    prompts = []
    def write(p):
        prompts.append(p)
        return writes(("Council designated the church.", [1]), ("It dates from 1862.", [2]))(p)
    monkeypatch.setattr(summary, "WRITE_CALL", write)
    monkeypatch.setattr(summary, "CHECK_CALL", checks("hold", "approve"))
    s = summary.refresh("X", LIVE)
    assert s["status"] == "held" and s["attempts"] == 2 and len(prompts) == 2
    assert "PROBLEMS" in prompts[1] and "Council designated the church." in prompts[1]   # repair sees the reasons
    assert summary.for_residents("X", LIVE) is None


def test_repair_that_passes_is_shown(tmp_data, monkeypatch):
    replies = iter([writes(("Council designated the church.", [1]))(""), writes(("Staff recommend designating the church.", [1]))("")])
    verdicts = iter([checks("hold")(""), checks("approve")("")])
    monkeypatch.setattr(summary, "WRITE_CALL", lambda _p: next(replies))
    monkeypatch.setattr(summary, "CHECK_CALL", lambda _p: next(verdicts))
    s = summary.refresh("X", LIVE)
    assert s["status"] == "ok" and s["attempts"] == 2
    assert summary.for_residents("X", LIVE)["sentences"][0]["text"] == "Staff recommend designating the church."


def test_summary_is_withdrawn_when_a_cited_sentence_is_no_longer_live_and_reused_when_unchanged(tmp_data, monkeypatch):
    monkeypatch.setattr(summary, "WRITE_CALL", writes(("Staff recommend protecting an 1862 church.", [1, 2])))
    monkeypatch.setattr(summary, "CHECK_CALL", checks("approve"))
    summary.refresh("X", LIVE)
    assert summary.for_residents("X", [LIVE[0], LIVE[2]]) is None                 # sentence 2 rejected
    monkeypatch.setattr(summary, "WRITE_CALL", lambda _p: pytest.fail("no new call when nothing changed"))
    assert summary.refresh("X", LIVE)["status"] == "ok"


def test_no_key_or_model_failure_means_no_summary_and_no_file(tmp_data, monkeypatch):
    assert summary.refresh("X", LIVE) is None                                       # conftest: model raises
    assert not (tmp_data / "X" / "summary.json").exists()
    assert summary.refresh("X", []) is None
