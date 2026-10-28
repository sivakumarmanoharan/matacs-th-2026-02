# WRITEUP

Reference: MATACS-TH-2026-02

## Design in brief

Processing has two stages. **Stage 1** runs per file on upload: validation, malware scan, dedupe, text extraction, injection screen, AI extraction, verification, storage, and the mandatory gates. **Stage 2** runs when the reviewer clicks Rank: code scores the eligible pool and ranks it, and an AI writes a one-line reason for each proposal. Files can arrive over several sessions. Ranking needs at least two eligible proposals, because price and timeline are scored relative to the best eligible bid, and a lone proposal would get full marks automatically.

## 1. AI vs. rules

AI is used in three steps:
1. Screening proposal text for injection attempts.
2. Extracting facts from the text.
3. Wording the one-line reason.

Everything else is code or rules: upload, validation, malware scan, hashing, OCR, quote verification, the pass/fail gates, scoring formulas, ranking, tie-breaks, status assignment, storage, and logging. The admin sets the weights and parameters as configuration, and code uses them to calculate points.

I drew the line where the input is unstructured. Extraction is where AI turns messy text into evidence. Anything that decides eligibility, order, or status is code, because code is repeatable and explainable, while an AI judgment could be influenced by text hidden in a proposal. The AI never decides a score or rank. The reason writer only receives numbers that code has already computed.

## 2. Consistency and explainability

- **Repeatable:** scores are arithmetic on stored facts. Extracted facts are saved in a database and cached by file hash plus the schema, prompt, and model versions. A renamed copy of the same PDF reuses the cache, and a changed schema or prompt does not.
- **Ranked twice:** yes, the result is identical when the proposals and criteria version are the same. Equal scores are ordered by lower price, then by proposal ID.
- **Explainable:** every extracted value carries a verbatim quote and a page number. Code checks that the quote exists in the source and that the number matches. The reviewer sees points per criterion, the quote behind each, and any flags, so every position traces back to specific sentences.
- **Limit:** price and timeline scores depend on the pool, so adding a proposal can move other scores. Each ranking run is saved with the proposals it included, so any earlier result can be reproduced.

## 3. Human in the loop

The reviewer uploads the files and chooses the category. Flagged proposals (an injection attempt, unclear gate evidence, an unreadable file) are held out of the ranking until a reviewer clears them. A reviewer can override a result with a mandatory written reason. Overrides are stored separately, and the original output is never edited.

The tool only triages and explains. A human makes the final award decision, and the review round is then locked.

An append-only audit log records file hashes, criteria version, model and prompt versions, raw AI outputs, injection findings, flags, each ranking run (with proposal IDs and scores), every override with user, time, and reason, and the final decision.

## 4. Changing criteria

Criteria are versioned snapshots, and every score records the version it used.

- **Weights or parameters change** (for example the experience cap): stored facts are re-scored under a new version, with no AI calls.
- **A criterion is added or its evidence changes:** the extraction schema is generated from the criteria, so the cache key no longer matches and affected proposals are extracted again.
- **Old results** are never overwritten. They stay labelled with their version, and the reviewer sees a "re-score under the new version" prompt with a before-and-after comparison.
- **Safety check:** the admin screen refuses to save if the weights do not add up to 100.

## 5. Risks

| Risk | Guard |
|---|---|
| Wrong extraction | Every value needs a verbatim quote, checked by code against the source. A mismatch becomes null plus a flag. The reviewer sees the quote beside each score. |
| Made-up facts | The model extracts only what is stated and returns null otherwise. Missing data scores 0 with a visible warning. |
| Prompt injection | Screening runs before extraction, and hits are quarantined and flagged. The AI never controls the ranking, so even a missed attack cannot change the order directly. |
| Bias | The model sees only the fields the criteria need. Scores come from fixed formulas, with no free-form impressions. Company names can be masked at extraction. Overrides need a written reason. |
| Cost | One extraction per proposal, cached. Re-ranking and weight changes cost no AI calls. A small model can run the screen. |
| Unreadable or hostile files | Format check, malware scan, OCR check, and a flag for unreadable files. |
| Over-trust in the ranking | The output is a triage list with reasons, flagged items are visible, and the award is a human decision. |

## Assumptions

1. The experience cap (12 installs) is an admin parameter. The project requirements (150 kW rooftop system, $260,000 CAD ceiling, 16 weeks from award) are stored in the criteria config.
2. The ceiling and the deadline are must-haves, checked after the gates. A bid over either limit is ineligible. A bid that states no price or completion time is flagged, because compliance cannot be confirmed.
3. Proposal B is ineligible: its electrical licence is held by a subcontractor to be confirmed.
4. Proposal C is flagged for its embedded instruction to rank it first. If a reviewer clears the flag, it scores about 81 and would rank second.
5. Proposal D is flagged because it gives no completion date, so the 16-week requirement cannot be confirmed. If it commits to a date within 16 weeks, a reviewer can clear it and it joins the pool.
6. "Last 5 years" cannot always be verified, because proposals say "since 2020". The extraction keeps the stated period for a reviewer to confirm.
