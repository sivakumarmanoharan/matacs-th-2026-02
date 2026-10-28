#!/usr/bin/env python3
"""Proposal triage prototype (MATACS-TH-2026-02).

Runs the design on the five sample proposals in samples/.

  python triage.py --offline   no API key; uses hand-labelled extractions in fixtures/
  python triage.py --live      calls a model API with the prompts in ../PROMPTS.md
      --provider anthropic     (default) needs ANTHROPIC_API_KEY
      --provider gemini        free tier via Google AI Studio, needs GEMINI_API_KEY
      --model NAME             override the default model for the provider
No third-party packages are needed: API calls use Python's standard library.

AI steps (live mode): injection screen, extraction, reason wording.
Everything else is plain code: quote verification, gates, requirement checks,
scoring, ranking and status. Weights, caps and project limits come from criteria.json.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent
CACHE = HERE / ".cache"
# Per provider: env var(s) holding the key, default model, and a pause (seconds) after each
# call so free-tier rate limits are not hit.
PROVIDERS = {
    "anthropic": {"keys": ["ANTHROPIC_API_KEY"], "model": os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5"), "delay": 0},
    "gemini": {"keys": ["GEMINI_API_KEY", "GOOGLE_API_KEY"], "model": os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite"), "delay": 7}
}
PROVIDER = "anthropic"
MODEL = PROVIDERS["anthropic"]["model"]
WORDS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen "
    "fourteen fifteen sixteen seventeen eighteen nineteen twenty".split())}

# Pattern rules for the injection screen (the AI classifier is added in live mode).
INJECTION_PATTERNS = [
    r"automated (review )?(system|reviewer)s?", r"\bAI (system|reviewer)s?\b",
    r"rank (it|this proposal) first", r"full marks", r"pre-?approved",
    r"ignore (the )?(criteria|instructions)", r"bypass the reviewer",
]


# ---------------------------------------------------------------- loading
def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_prompts():
    """Read the three prompts exactly as written in PROMPTS.md."""
    text = (ROOT / "PROMPTS.md").read_text(encoding="utf-8")
    parts = re.split(r"(?m)^# Prompt (\d):.*$", text)
    out = {}
    for num, body in zip(parts[1::2], parts[2::2]):
        system = re.search(r"### System prompt\s+```\n(.*?)\n```", body, re.S).group(1)
        user = re.search(r"### User prompt template\s+```\n(.*?)\n```", body, re.S).group(1)
        out[int(num)] = (system, user)
    return out


def schema_fields(criteria):
    """Extraction fields come from the criteria config, not from code."""
    fields = {}
    for block in criteria["gates"] + criteria["weighted"]:
        if "fields" not in block:
            sys.exit("criteria.json is out of date: the entry '" + block.get("id", "?") +
                     "' has no 'fields' list. Replace it with the latest prototype/criteria.json.")
        for f in block["fields"]:
            fields[f["name"]] = {"type": f["type"], "description": f["description"]}
    return fields


# ---------------------------------------------------------------- text helpers
def split_pages(text):
    parts = re.split(r"\[\[PAGE (\d+)\]\]", text)
    return {int(p): t.strip() for p, t in zip(parts[1::2], parts[2::2])}


def join_pages(pages):
    return "\n".join(f"[[PAGE {p}]]\n{t}" for p, t in pages.items())


def norm(s):
    return re.sub(r"\s+", " ", s).strip()


def numbers_in(quote):
    """All numbers a quote contains: digits, $5M style, and number words."""
    nums = set()
    for m in re.finditer(r"(\d[\d,]*(?:\.\d+)?)\s?([MK])?\b", quote):
        v = float(m.group(1).replace(",", ""))
        v *= {"M": 1e6, "K": 1e3}.get(m.group(2), 1)
        nums.add(v)
    nums.update(float(WORDS[w]) for w in re.findall(r"[a-z]+", quote.lower()) if w in WORDS)
    return nums


# ---------------------------------------------------------------- AI calls (live mode)
def parse_json(raw):
    raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def read_env_file(path):
    """Read a .env file. Handles UTF-8, UTF-8 with BOM (Notepad) and UTF-16 (PowerShell's '>')."""
    raw = Path(path).read_bytes()
    text = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8-sig")
    values = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        name, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].strip()
        values[name.strip()] = value
    return values


def load_env(dirs=None):
    """Load API keys from a .env file in prototype/, the repo root, or the current folder.
    Real environment variables always win over the file. Returns (file used, names loaded)."""
    for d in dirs or [HERE, ROOT, Path.cwd()]:
        f = Path(d) / ".env"
        if f.is_file():
            loaded = [k for k, v in read_env_file(f).items() if v and k not in os.environ]
            for k, v in read_env_file(f).items():
                if v:
                    os.environ.setdefault(k, v)
            return f, loaded
        if (Path(d) / ".env.txt").is_file():
            print(f"Note: found {Path(d) / '.env.txt'}. The file must be named exactly '.env' (no .txt).", file=sys.stderr)
    return None, []


def get_key():
    names = PROVIDERS[PROVIDER]["keys"]
    for n in names:
        if os.environ.get(n):
            return os.environ[n]
    sys.exit(f"Live mode with provider '{PROVIDER}' needs an API key named {names[0]}. "
             f"Put {names[0]}=your-key in a file named .env in the prototype folder, or set it in this terminal. "
             f"Looked for .env in: {HERE}, {ROOT}, {Path.cwd()}")


def post_json(url, headers, body, tries=5):
    """POST JSON using the standard library. Waits and retries on rate limits (429) and server errors."""
    data = json.dumps(body).encode("utf-8")
    for attempt in range(1, tries + 1):
        req = urllib.request.Request(url, data=data, method="POST",
                                     headers={"Content-Type": "application/json", **headers})
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            if e.code in (429, 500, 502, 503, 504) and attempt < tries:
                retry_after = e.headers.get("Retry-After") if e.headers else None
                wait = int(retry_after) if retry_after and retry_after.isdigit() else 15 * attempt
                why = re.sub(r"\s+", " ", detail)[:140]
                print(f"  provider returned {e.code} ({why}); waiting {wait}s (attempt {attempt}/{tries})", file=sys.stderr)
                time.sleep(wait)
                continue
            sys.exit(f"API error {e.code} from {PROVIDER}: {detail}")
        except urllib.error.URLError as e:
            sys.exit(f"Network error calling {PROVIDER}: {e.reason}")


def raw_completion(system, user):
    """One request at temperature 0. Returns the model's text (empty string if the reply has none)."""
    key = get_key()
    try:
        if PROVIDER == "gemini":
            out = post_json(f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent",
                            {"x-goog-api-key": key},
                            {"systemInstruction": {"parts": [{"text": system}]},
                             "contents": [{"role": "user", "parts": [{"text": user}]}],
                             "generationConfig": {"temperature": 0, "responseMimeType": "application/json"}})
            return out["candidates"][0]["content"]["parts"][0]["text"]
        out = post_json("https://api.anthropic.com/v1/messages",
                        {"x-api-key": key, "anthropic-version": "2023-06-01"},
                        {"model": MODEL, "max_tokens": 2000, "temperature": 0, "system": system,
                         "messages": [{"role": "user", "content": user}]})
        return "".join(b.get("text", "") for b in out["content"] if b.get("type") == "text")
    except (KeyError, IndexError, TypeError):
        return ""  # e.g. a blocked or empty reply: treated as invalid JSON by the caller


def call_llm(system, user, version):
    """One AI call. Cached by prompt version + provider + model + input text."""
    key = hashlib.sha256("|".join([version, PROVIDER, MODEL, system, user]).encode("utf-8")).hexdigest()
    path = CACHE / f"{key}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    for _ in range(2):  # retry once on invalid JSON, then give up
        data = parse_json(raw_completion(system, user))
        time.sleep(PROVIDERS[PROVIDER]["delay"])
        if isinstance(data, dict):
            CACHE.mkdir(exist_ok=True)
            path.write_text(json.dumps(data), encoding="utf-8")
            return data
    return None


# ---------------------------------------------------------------- stage 1 steps
def regex_screen(pages):
    findings = []
    for page, text in pages.items():
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            if any(re.search(p, sentence, re.I) for p in INJECTION_PATTERNS):
                findings.append({"page": page, "quote": sentence,
                                 "why": "Text tries to influence an automated reviewer"})
    return findings


def ai_screen(pages, prompts):
    system, user = prompts[1]
    user = user.replace("{{proposal_text_with_page_markers}}", join_pages(pages))
    data = call_llm(system, user, "injection_v1") or {}
    src = norm(join_pages(pages))
    # only trust findings whose quote really appears in the text
    return [f for f in data.get("findings", []) if norm(f.get("quote", "")) in src]


def quarantine(pages, findings):
    clean = dict(pages)
    for f in findings:
        clean[f["page"]] = clean.get(f["page"], "").replace(f["quote"], "").strip()
    return clean


def extract(pages, criteria, fields, prompts):
    system, user = prompts[2]
    user = (user.replace("{{category_name}}", criteria["category"])
                .replace("{{criteria_version}}", str(criteria["version"]))
                .replace("{{generated_schema_json}}", json.dumps(fields, indent=2))
                .replace("{{proposal_text_with_page_markers}}", join_pages(pages)))
    return call_llm(system, user, "extraction_v1")


def verify(extraction, fields, text):
    """Code check: every value needs a quote that exists in the source, and numbers must match."""
    src, facts, flags = norm(text), {}, []
    for name, spec in fields.items():
        e = (extraction or {}).get(name) or {}
        v, q = e.get("value"), e.get("quote")
        if v is not None:
            if not q or norm(q) not in src:
                flags.append(f"{name}: quote not found in source"); v = None
            elif spec["type"] in ("integer", "number") and float(v) not in numbers_in(q):
                flags.append(f"{name}: number does not match quote"); v = None
        facts[name] = {"value": v, "quote": q if v is not None else None, "note": e.get("note")}
    return facts, flags


def check_rules(facts, criteria):
    """Gates and project requirement checks. Returns (ineligible reasons, flagged reasons)."""
    g = lambda name: facts[name]["value"]
    proj, bad, flag = criteria["project"], [], []
    min_ins = criteria["gates"][1]["min_liability_cad"]
    if g("licence_held_by_bidder") is False:
        bad.append("licence is not held by the bidder")
    elif g("licence_held_by_bidder") is None:
        flag.append("licence holder not stated")
    if g("wsib_clearance") is not True:
        flag.append("WSIB clearance not confirmed")
    if g("liability_insurance_cad") is None:
        flag.append("liability insurance not confirmed")
    elif g("liability_insurance_cad") < min_ins:
        bad.append("liability insurance below minimum")
    if g("total_price_cad") is None:
        flag.append("price not stated")
    elif g("total_price_cad") > proj["budget_ceiling_cad"]:
        bad.append("price above budget ceiling")
    if g("completion_weeks") is None:
        flag.append(f"completion time not stated, {proj['max_weeks_from_award']}-week requirement cannot be confirmed")
    elif g("completion_weeks") > proj["max_weeks_from_award"]:
        bad.append("completion time above maximum")
    return bad, flag


# ---------------------------------------------------------------- stage 2 steps
def present(v):
    return v is True or (isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0)


def score_pool(pool, facts, criteria):
    """Weighted points per criterion. Price and timeline are relative to the eligible pool."""
    W = {w["id"]: w for w in criteria["weighted"]}
    val = lambda p, k: facts[p][k]["value"]
    best_price = min(val(p, "total_price_cad") for p in pool)
    best_weeks = min(val(p, "completion_weeks") for p in pool)
    out = {}
    for p in pool:
        pts = {}
        w = W["experience"]; n = val(p, "installs_100kw_plus")
        pts["experience"] = w["weight"] * min(n or 0, w["cap"]) / w["cap"]
        pts["price"] = W["price"]["weight"] * best_price / val(p, "total_price_cad")
        pts["timeline"] = W["timeline"]["weight"] * best_weeks / val(p, "completion_weeks")
        w = W["warranty"]; half = w["weight"] / 2
        pts["warranty"] = (half * min(val(p, "panel_warranty_years") or 0, w["panel_cap_years"]) / w["panel_cap_years"]
                           + half * min(val(p, "workmanship_warranty_years") or 0, w["workmanship_cap_years"]) / w["workmanship_cap_years"])
        w = W["team"]
        pts["team"] = w["weight"] * sum(present(val(p, i)) for i in w["items"]) / len(w["items"])
        out[p] = {"points": pts, "total": sum(pts.values())}
    return out


def template_reason(pid, res, n_ranked):
    if res["status"] == "ranked":
        return (f"Ranked {res['rank']} of {n_ranked} (score {res['score']}); strongest on {res['top']}, "
                f"weakest on {res['weak']}.")
    return f"{res['status'].capitalize()}: " + "; ".join(res["reasons"]) + "."


def ai_reason(pid, res, n_ranked, prompts):
    system, user = prompts[3]
    labels = "; ".join(res["reasons"]) if res["reasons"] else "none"
    user = (user.replace("{{id}}", pid).replace("{{status}}", res["status"])
                .replace("{{rank}}", str(res["rank"])).replace("{{score}}", str(res["score"]))
                .replace("{{breakdown_json}}", json.dumps(res.get("points", {})))
                .replace("{{reason_labels}}", labels)
                .replace("{{top_criterion}}", str(res.get("top")))
                .replace("{{weakest_criterion}}", str(res.get("weak"))))
    data = call_llm(system, user, "reason_v1") or {}
    text = data.get("reason", "")
    # guard: reject text that mentions a number that was not in the data we supplied
    if text and numbers_in(text) <= numbers_in(user):
        return text
    return template_reason(pid, res, n_ranked)


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--offline", action="store_true")
    mode.add_argument("--live", action="store_true")
    ap.add_argument("--provider", choices=list(PROVIDERS), default="anthropic", help="live mode only")
    ap.add_argument("--model", help="override the provider's default model")
    args = ap.parse_args()
    live = args.live
    global PROVIDER, MODEL
    PROVIDER = args.provider
    MODEL = args.model or PROVIDERS[PROVIDER]["model"]
    if live:
        env_file, loaded = load_env()
        if env_file:
            print(f"Read {env_file}: " + (", ".join(loaded) if loaded else "no new variables (already set in the terminal)"))
        get_key()  # fail early with a clear message if the key is missing

    criteria = read_json(HERE / "criteria.json")
    assert sum(w["weight"] for w in criteria["weighted"]) == 100, "weights must add up to 100"
    fields, prompts = schema_fields(criteria), load_prompts()
    print(f"Mode: {'live (' + PROVIDER + ': ' + MODEL + ')' if live else 'offline (fixtures)'} | criteria v{criteria['version']} | "
          f"project: {criteria['project']['project_size_kw']} kW, ceiling ${criteria['project']['budget_ceiling_cad']:,}, "
          f"{criteria['project']['max_weeks_from_award']} weeks\n")

    # ---- Stage 1: per proposal
    facts, results = {}, {}
    for path in sorted((HERE / "samples").glob("*.txt")):
        pid = path.stem
        pages = split_pages(path.read_text(encoding="utf-8"))
        findings = regex_screen(pages)
        if live:
            known = {norm(f["quote"]) for f in findings}
            findings += [f for f in ai_screen(pages, prompts) if norm(f["quote"]) not in known]
        clean = quarantine(pages, findings)
        extraction = (extract(clean, criteria, fields, prompts) if live
                      else read_json(HERE / "fixtures" / f"{pid}.json"))
        facts[pid], vflags = verify(extraction, fields, join_pages(clean))
        bad, flag = check_rules(facts[pid], criteria)
        if extraction is None:
            flag.append("extraction failed")
        if findings:
            flag.insert(0, "embedded instruction aimed at automated reviewers (quarantined)")
        status = "ineligible" if bad else "flagged" if flag else "candidate"
        results[pid] = {"status": status, "reasons": bad + flag + vflags, "rank": None, "score": None}

    # ---- Stage 2: rank the eligible pool (needs at least 2)
    pool = [p for p, r in results.items() if r["status"] == "candidate"]
    if len(pool) < criteria["ranking"]["minimum_eligible_to_rank"]:
        for p in pool:
            results[p].update(status="flagged", reasons=["need at least two eligible proposals to compare"])
        print("Not enough eligible proposals to rank.")
    else:
        scores = score_pool(pool, facts, criteria)
        price = lambda p: facts[p]["total_price_cad"]["value"]
        order = sorted(pool, key=lambda p: (-scores[p]["total"], price(p), p))
        for i, p in enumerate(order, 1):
            ratios = {k: v / next(w["weight"] for w in criteria["weighted"] if w["id"] == k)
                      for k, v in scores[p]["points"].items()}
            results[p].update(status="ranked", rank=i, score=round(scores[p]["total"], 1),
                              points={k: round(v, 2) for k, v in scores[p]["points"].items()},
                              top=max(ratios, key=ratios.get), weak=min(ratios, key=ratios.get))
        # reference score for proposals held out only by an injection flag
        for p, r in results.items():
            if r["status"] == "flagged" and r["reasons"] and "embedded" in r["reasons"][0] \
                    and facts[p]["total_price_cad"]["value"] and facts[p]["completion_weeks"]["value"]:
                ref = score_pool(pool + [p], facts, criteria)[p]["total"]
                r["reasons"][0] += f", clean-content score about {round(ref)}"

    # ---- Reasons, output, and check against ranking.json
    n_ranked = len(pool)
    ranking = []
    for pid, r in sorted(results.items(), key=lambda kv: (kv[1]["rank"] is None, kv[1]["rank"] or 0, kv[0])):
        reason = ai_reason(pid, r, n_ranked, prompts) if live else template_reason(pid, r, n_ranked)
        ranking.append({"proposal": pid, "rank": r["rank"], "status": r["status"],
                        "score": r["score"], "reason": reason})
        print(f"{pid}  rank={r['rank']}  {r['status']:<10} score={r['score']}  {reason}")
    (HERE / "triage_output.json").write_text(json.dumps(ranking, indent=2), encoding="utf-8")

    expected = {e["proposal"]: e for e in read_json(ROOT / "ranking.json")}
    diffs = [f"{x['proposal']}: got ({x['rank']}, {x['status']}, {x['score']}), expected "
             f"({expected[x['proposal']]['rank']}, {expected[x['proposal']]['status']}, {expected[x['proposal']]['score']})"
             for x in ranking
             if (x["rank"], x["status"], x["score"]) != (expected[x["proposal"]]["rank"],
                                                          expected[x["proposal"]]["status"],
                                                          expected[x["proposal"]]["score"])]
    print("\nMatches ../ranking.json (rank, status, score)." if not diffs else "\nDIFFERENCES vs ../ranking.json:\n  " + "\n  ".join(diffs))
    sys.exit(1 if diffs else 0)


if __name__ == "__main__":
    main()