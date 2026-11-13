---
name: civify-context
description: Full hackathon context for Civify, including the exact problem statement ("Making municipal decisions easier to understand"), the exact judging rubric and the agreed solution idea. Load before planning, designing, building or writing anything for Civify (features, report, video script, pitch), or when asked whether something fits the brief or rubric.
---

# Civify: hackathon context

Read the two reference files in this folder before working:

- [brief.md](brief.md): the exact problem statement. It is the source of truth for requirements and constraints.
- [rubric.md](rubric.md): the exact judging rubric (100 points). Aim every decision at "5 · Excellent".

## The agreed idea

Civify is an address-first decision tracker for Toronto council items. A resident enters a location and gets a card for each item near them. Each card answers three things:
1. **What is proposed, and why**, in plain language.
2. **Where it stands:** staff recommendation → committee decision → council decision → closed or appeal.
3. **Can I still have a say?** Yes or no, with the deadline and how to take part.

What sets it apart from "paste a report, get an AI summary" is the **trust layer**:
- Every summary sentence is paired with an exact quote from the source. Code checks that the quote exists and that the numbers match. Anything unverified is flagged and never shown as fact.
- Stages are read from the record, never inferred.
- Deadlines come only from the official item page, with a "last verified" date. Never infer them from a meeting date.
- Municipal staff approve every summary before residents see it (staff review console).
- Offline reach: SMS alerts (Twilio) and a printable one-page notice with a QR code.

## Scope and constraints

- Two-day build. Stack: Python, FastAPI, SQLite, a simple frontend and Twilio.
- Three real Toronto items: zoning or development, fee or budget, and bike lane or transit. At least one was amended and at least one has an open comment window.
- Store no street addresses. SMS subscribers: phone number, three-character postal area code and language only.
- Neutral, non-partisan, plain language. Preserve conditions and uncertainty.
- Never cut the verifier, the stage labels or staff approval. If behind schedule, cut in this order: translation, notifications, the amendment diff.

## Rubric reminders that are easy to miss

- Presentation is **40%** (readiness report 20, video 20). Plan these from day one.
- The video must **distinguish working features from planned ones** and should show the verifier catching a wrong summary.
- References (5 points) need the **version and licence** of every library, plus documentation of how AI was used **and verified**.
- UML must **match the implementation**. Requirements must be **testable**.
- Architecture rationale needs **alternatives compared** and **trade-offs**.
- Impact needs a path to **other municipalities**, not just Toronto.
