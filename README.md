# AI-Assisted Proposal Triage Tool: Design

**Name:** Sivakumar Manoharan

**Reference:** MATACS-TH-2026-02

**Time actually spent**: 4 hours over 2 days

## What this is

A design for an AI-assisted tool that takes contractor proposals (PDFs) for a category, applies admin-defined criteria, and returns a ranked list with a reason for each position. A human makes the final award decision. This submission is design only. No deployed system is included.

The given problem statement is with respect to a Commercial Solar Installation which is a 150 kW rooftop system at Windsor, Ontario with a budget ceiling of $260,000 CAD, and completion within 16 weeks of award.

## Files

| File | What it contains |
|---|---|
| [diagram/process-flow.png](diagram/Matacs_ai_triage_design.pdf) | Process flow from upload to ranked output. Colour-coded to show AI steps, rule-based steps, and human checkpoints. |
| [WRITEUP.md](WRITEUP.md) | Answers to the five questions: AI vs. rules, consistency and explainability, human in the loop, changing criteria, and risks. |
| [PROMPTS.md](PROMPTS.md) | The three prompts, as they would be sent: injection screen, extraction, and reason writer. |
| [ranking.json](ranking.json) | Expected ranking of proposals A to E. |
| [prototype/criteria.json](prototype/criteria.json) | Example of the admin-defined criteria config that the design loads (version 2): gates, weights, formulas, and project limits. |

## Design summary

- **Two stages.** Stage 1 runs per file on upload. Stage 2 runs when the reviewer clicks Rank.
- **AI reads, code decides.** AI screens for injection, extracts facts with a verbatim quote and page for each, and words the one-line reason. Gates, scoring, ranking, and status are plain code.
- **Ranking needs at least two eligible proposals.** Price and timeline are scored relative to the best eligible bid.
- **Result on the sample set:** A ranked 1, E ranked 2. C is flagged for an embedded instruction aimed at automated reviewers. D is flagged because it gives no completion date. B is ineligible because its licence is held by a subcontractor.

## How I used AI tools


- **Tool used:** Claude (Anthropic).
- **What I used it for:** I used it for generating my draft mermaid code files, draft documents for writeup and readme and to discuss my flaws with respect to my design
- **What I did myself:** Base design is done from my side. Finding the gap in my design where the pdf gets uploaded and evaluation happens. Ranking flag for a single proposal is cancelled by me and I added the rule that ranking should be done between two or more proposals.
- **How I checked the output:** I recomputed the scores manually using a calculator and thought of edge cases that would fail. This helped me correct the output and helped me refine my design

## Notes

- Experience cap (12 installs) is an assumption and an admin parameter.
- No prototype script is included.
