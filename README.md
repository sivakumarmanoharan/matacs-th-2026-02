# AI-Assisted Proposal Triage Tool: Design

**Name:** Sivakumar Manoharan

**Reference:** MATACS-TH-2026-02

**Time actually spent**: 4 hours over 2 days

## What this is

A design for an AI-assisted tool that takes contractor proposals (PDFs) for a category, applies admin-defined criteria, and returns a ranked list with a reason for each position. A human makes the final award decision. This submission is a design with a prototype that delivers the ranked json based on the sample proposals given.

The given problem statement is with respect to a Commercial Solar Installation which is a 150 kW rooftop system at Windsor, Ontario with a budget ceiling of $260,000 CAD, and completion within 16 weeks of award.

## Files

| File | What it contains |
|---|---|
| [diagram/Matacs_ai_triage_design.png](diagram/Matacs_ai_triage_design.png) | Process flow from upload to ranked output. Colour-coded to show AI steps, rule-based steps, and human checkpoints. |
| [WRITEUP.md](WRITEUP.md) | Answers to the five questions: AI vs. rules, consistency and explainability, human in the loop, changing criteria, and risks. |
| [PROMPTS.md](PROMPTS.md) | The three prompts, as they would be sent: injection screen, extraction, and reason writer. |
| [ranking.json](ranking.json) | Expected ranking of proposals A to E. |
| [prototype/](prototype/) | A working prototype which follows the design in the pdf and extracts the values for testing purposes |

## Design summary

- **Two stages.** Stage 1 runs per file on upload. Stage 2 runs when the reviewer clicks Rank.
- **AI reads, code decides.** AI screens for injection, extracts facts with a verbatim quote and page for each, and words the one-line reason. Gates, scoring, ranking, and status are plain code.
- **Ranking needs at least two eligible proposals.** Price and timeline are scored relative to the best eligible bid.
- **Result on the sample set:** A ranked 1, E ranked 2. C is flagged for an embedded instruction aimed at automated reviewers. D is flagged because it gives no completion date. B is ineligible because its licence is held by a subcontractor.
- **Deterministic order:** If two samples are ranked the same, then the order is defined by the least amount quoted and the proposal id. 

## How I used AI tools


- **Tool used:** Claude (Anthropic) and Gemini(Google) for API calls in the prototype.
- **What I used it for:** I used it for generating my draft mermaid code files, draft documents for writeup and readme and to discuss my flaws with respect to the design AI generated as a base. For API calls, I used Gemini(Google), because it gives me with a free tier option, but made anthropic calls as default if the user has anthropic API keys
- **What I did myself:** Finding the gap in the base design AI gave where the pdf gets uploaded and evaluation happens. Ranking flag for a single proposal is cancelled by me and I added the rule that ranking should be done between two or more proposals.
- **How I checked the output:** I recomputed the scores manually using a calculator and thought of edge cases that would fail. This helped me correct the output and helped me refine my design
- **Defying the decisions AI took:** The first prototype used only Anthropic. When I asked about cost, Claude listed free-tier options, and I decided to add Gemini. So the code was rewritten in a way that it can also use Gemini API key to reduce costs by using free tier. 

## Running the prototype
1. Do a ``git clone`` of the repository
2. Open the repository in VSCode.
3. Create a .env file to store the API key of anthropic or gemini if the user wants to test the prompts
4. In VSCode, navigate to Terminal-> New Terminal
5. Navigate to prototype folder using ```cd prototype```
6. Follow the commands below if the user wants to test it offline or with API key

```
python triage.py --offline                       # no API key needed
python triage.py --live --provider gemini        # needs GEMINI_API_KEY (Google AI Studio)
python triage.py --live                          # Anthropic, needs ANTHROPIC_API_KEY
```
The script compares its result with ranking.json (rank, status, and score) and exits with an error if they differ. Offline mode matches.

## Demo for offline mode

https://github.com/user-attachments/assets/adfc9c10-c711-44a2-bec0-a2710cc88c8d

For live mode, the additional step of creation of API key from Gemini or Anthropic is needed. Once that is done, create a .env file within prototype directory and add the value of the key given in .env.example


## Notes

- Experience cap (12 installs) is an assumption and an admin parameter.
