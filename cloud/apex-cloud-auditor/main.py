import json, os, re, sys, urllib.request
from concurrent.futures import ThreadPoolExecutor

TIMEOUT = int(os.environ.get("CALL_TIMEOUT", "90"))
ROLES = ("propose", "critique", "adjudicate")
MIN_FAMILIES = 3

def _post(url, payload, headers):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode())

def openai_call(model, prompt):
    d = _post("https://api.openai.com/v1/chat/completions",
        {"model": model, "messages": [{"role": "user", "content": prompt}]},
        {"Authorization": "Bearer " + os.environ["OPENAI_API_KEY"]})
    return d["choices"][0]["message"]["content"]

def anthropic_call(model, prompt):
    d = _post("https://api.anthropic.com/v1/messages",
        {"model": model, "max_tokens": 1200, "messages": [{"role": "user", "content": prompt}]},
        {"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"})
    return "".join(b.get("text", "") for b in d.get("content", []))

def gemini_call(model, prompt):
    url = ("https://generativelanguage.googleapis.com/v1beta/models/"
           + model + ":generateContent?key=" + os.environ["GEMINI_API_KEY"])
    d = _post(url, {"contents": [{"parts": [{"text": prompt}]}]}, {})
    return d["candidates"][0]["content"]["parts"][0].get("text", "")

FAMILIES = [
    ("openai", os.environ.get("OPENAI_MODEL", "gpt-5-mini"), openai_call),
    ("anthropic", os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5"), anthropic_call),
    ("google", os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"), gemini_call),
]

PROMPTS = {
 "propose": "Audit the artifact below. State what it does, then list every defect you can substantiate from the text itself. No speculation, no style notes. If it is sound, say so and say why.\n\n--- ARTIFACT ---\n{artifact}",
 "critique": "Another auditor produced the finding below about this artifact. Attack it. Which claims are wrong or unsupported, and which real defects did it miss? Cite the text.\n\n--- ARTIFACT ---\n{artifact}\n\n--- FINDING ---\n{prior}",
 "adjudicate": "You wrote neither document below. Decide what actually holds.\n\n--- ARTIFACT ---\n{artifact}\n\n--- FINDING ---\n{proposal}\n\n--- REBUTTAL ---\n{prior}\n\nReply with JSON only: {{\"verdict\": \"pass\" | \"fix_required\" | \"unclear\", \"confidence\": 0.0, \"reasons\": [\"...\"]}}",
}

def rotations(fams):
    n = len(fams)
    if n < MIN_FAMILIES:
        raise ValueError("need more than 2 independent lineages, got %d" % n)
    return [[fams[(i + r) % n] for r in range(len(ROLES))] for i in range(n)]

def parse_verdict(text):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return "unclear", 0.0, ["adjudicator returned no JSON"]
    try:
        d = json.loads(m.group(0))
    except Exception:
        return "unclear", 0.0, ["adjudicator returned malformed JSON"]
    v = str(d.get("verdict", "unclear")).lower().strip()
    if v not in ("pass", "fix_required", "unclear"):
        v = "unclear"
    try:
        c = max(0.0, min(1.0, float(d.get("confidence", 0.0))))
    except Exception:
        c = 0.0
    return v, c, [str(x) for x in d.get("reasons", [])][:5]

def run_sequence(idx, chain, artifact):
    out = {"index": idx, "chain": [f[0] for f in chain], "verdict": "error",
           "confidence": 0.0, "reasons": [], "error": None}
    ctx = {"artifact": artifact, "prior": "", "proposal": ""}
    try:
        for role, (key, model, call) in zip(ROLES, chain):
            text = call(model, PROMPTS[role].format(**ctx))
            if role == "propose":
                ctx["proposal"] = text
            ctx["prior"] = text
        out["verdict"], out["confidence"], out["reasons"] = parse_verdict(ctx["prior"])
    except Exception as e:
        out["error"] = "%s: %s" % (type(e).__name__, e)
    return out

def converge(results, prior_unanimity=0.0):
    done = [r for r in results if not r["error"]]
    failed = len(results) - len(done)
    if not done:
        return {"verdict": "error", "agreement": 0.0, "completed": 0, "failed": failed,
                "informative": False, "note": "every sequence failed", "dissent": [],
                "sequences": results}
    tally = {}
    for r in done:
        tally[r["verdict"]] = tally.get(r["verdict"], 0) + 1
    top = max(tally, key=lambda v: (tally[v], sum(r["confidence"] for r in done if r["verdict"] == v)))
    agreement = tally[top] / float(len(done))
    dissent = ["%s judged %s (%.2f): %s" % (r["chain"][-1], r["verdict"], r["confidence"],
               r["reasons"][0] if r["reasons"] else "no reason given")
               for r in done if r["verdict"] != top]
    if len(done) < MIN_FAMILIES:
        inf = False; note = "only %d sequences survived; below the 3-lineage floor, treat as one opinion" % len(done)
    elif agreement == 1.0 and prior_unanimity >= 0.9:
        inf = False; note = "unanimous, but this crowd agrees %.0f%% of the time here - agreement is the default, not evidence" % (prior_unanimity * 100)
    elif agreement == 1.0:
        inf = True; note = "unanimous across independent lineages"
    elif agreement >= 0.6:
        inf = True; note = "majority, with dissent recorded"
    else:
        inf = False; note = "no majority - crowd is split, escalate to a human"
    return {"verdict": top, "agreement": round(agreement, 3), "completed": len(done),
            "failed": failed, "informative": inf, "note": note, "dissent": dissent,
            "sequences": done}

def load_artifact():
    if os.environ.get("AUDIT_TEXT"):
        return os.environ["AUDIT_TEXT"][:20000]
    url = os.environ.get("AUDIT_URL")
    if url:
        try:
            with urllib.request.urlopen(url, timeout=TIMEOUT) as r:
                return r.read().decode("utf-8", "replace")[:20000]
        except Exception as e:
            return "Target %s could not be fetched: %s: %s" % (url, type(e).__name__, e)
    return "No audit target configured (set AUDIT_URL or AUDIT_TEXT)."

def main():
    artifact = load_artifact()
    chains = rotations(FAMILIES)
    with ThreadPoolExecutor(max_workers=len(chains)) as ex:
        results = list(ex.map(lambda t: run_sequence(t[0], t[1], artifact), list(enumerate(chains))))
    report = converge(results, float(os.environ.get("PRIOR_UNANIMITY", "0")))
    report["target"] = os.environ.get("AUDIT_URL", "inline")
    print(json.dumps(report, indent=2)[:60000], flush=True)
    sys.exit(0 if report["completed"] else 1)

main()
