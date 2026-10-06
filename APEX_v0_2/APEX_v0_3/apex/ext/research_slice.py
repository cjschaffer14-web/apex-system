"""Research Pack: the first complete vertical slice (ChatGPT review, Upgrade 8).

document -> Observation -> document graph -> claims / equations / citations ->
answer -> verification -> benchmark -> LearningCandidate -> sealed improvement

Stdlib only. Retrieval strategies are the Proposal-plane "phenotype" that the
organism improves on its own (ChatGPT's first-autonomous-improvement example:
larger chunks vs section graph vs claim graph). PDF parsing and an MLX
reasoner plug in at `parse_document` and `answer`; the loop around them does
not change.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from ..core import ModelGraph, Plane

STOP = {"the", "a", "an", "of", "to", "and", "or", "in", "on", "for", "by", "is", "are", "was", "were", "be",
        "what", "which", "who", "why", "how", "did", "do", "does", "that", "this", "with", "as", "at", "it",
        "its", "their", "they", "authors", "say", "we", "our", "from", "between"}
WORD = re.compile(r"[a-z0-9][a-z0-9_%.-]*")
CLAIM = re.compile(r"\b(we (show|find|propose|conclude)|suggests?|cut|reduce[sd]?|fell|never|improv\w*)\b", re.I)
CITE = re.compile(r"\[(\d+)\]|\(([A-Z][a-z]+(?: et al\.)?),? (\d{4})\)")


def _stem(w: str) -> str:
    for suf in ("ing", "ed", "es", "s", "e"):
        if len(w) > 4 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def toks(s: str) -> set[str]:
    return {_stem(w.strip(".-")) for w in WORD.findall(s.lower()) if w.strip(".-") and w.strip(".-") not in STOP}


@dataclass(frozen=True)
class Section:
    id: str
    title: str
    text: str


@dataclass
class DocGraph:
    doc_id: str
    title: str
    sections: list[Section]
    sentences: list[tuple[str, str, str]]          # (sentence_id, section_id, text)
    claims: list[str] = field(default_factory=list)
    equations: list[str] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)
    graph: ModelGraph = field(default_factory=ModelGraph)

    def section(self, sid: str) -> Section:
        return next(s for s in self.sections if s.id == sid)


def parse_document(text: str, doc_id: str = "doc") -> DocGraph:
    title, sections, cur_title, buf = doc_id, [], "Preamble", []

    def flush():
        body = "\n".join(buf).strip()
        if body:
            sections.append(Section(f"{doc_id}:s{len(sections)}", cur_title, body))

    for line in text.splitlines():
        if line.startswith("#"):
            flush(); buf = []
            cur_title = line.lstrip("#").strip()
            if line.startswith("# ") and title == doc_id:
                title = cur_title
        else:
            buf.append(line)
    flush()
    g = ModelGraph()
    g.add_node(doc_id, "Entity", {"title": title})
    sentences, claims, eqs, cites = [], [], [], []
    for s in sections:
        g.add_node(s.id, "Entity", {"title": s.title})
        g.add_edge(s.id, doc_id, "instance_of", Plane.PROPOSAL)
        parts = []
        for line in s.text.splitlines():
            line = line.strip()
            if not line:
                continue
            if "=" in line and len(line) < 120:
                parts.append(line)
            else:
                parts.extend(p.strip() for p in re.split(r"(?<=[.!?])\s+(?=[A-Z\[(])", line) if p.strip())
        for p in parts:
            sid = f"{s.id}:t{len(sentences)}"
            sentences.append((sid, s.id, p))
            if "=" in p and len(p) < 120:
                eqs.append(sid); g.add_node(sid, "Symbol", {"text": p}); g.add_edge(sid, s.id, "derived_from", Plane.PROPOSAL)
            elif CLAIM.search(p):
                claims.append(sid); g.add_node(sid, "Claim", {"text": p}); g.add_edge(sid, s.id, "derived_from", Plane.PROPOSAL)
            for m in CITE.finditer(p):
                cid = f"cite:{m.group(1) or (m.group(2) + ' ' + m.group(3))}"
                if cid not in g.nodes:
                    g.add_node(cid, "Entity", {"kind": "citation"}); cites.append(cid)
                if sid in g.nodes:
                    g.add_edge(sid, cid, "depends_on", Plane.PROPOSAL)
    return DocGraph(doc_id, title, sections, sentences, claims, eqs, cites, g)


# --- strategies (the improvable phenotype) ---------------------------------------

def _chunks(doc: DocGraph, size: int) -> list[tuple[str, str]]:
    words = " ".join(s.text for s in doc.sections).split()
    return [(f"chunk{i}", " ".join(words[i:i + size])) for i in range(0, len(words), size)]


def _best(units: list[tuple[str, str]], q: set[str], k: int = 1) -> list[tuple[str, str]]:
    return sorted(units, key=lambda u: -len(q & toks(u[1])))[:k]


def retrieve(doc: DocGraph, question: str, strategy: str) -> tuple[str, list[str], int]:
    """Returns (answer_text, cited unit ids, tokens scanned)."""
    q = toks(question)
    if strategy in ("flat_small", "flat_large"):
        units = _chunks(doc, 14 if strategy == "flat_small" else 45)
        best = _best(units, q)
    elif strategy == "section":
        units = [(s.id, s.text) for s in doc.sections]
        best = _best(units, q)
    elif strategy == "claim_graph":
        units = [(sid, t) for sid, _, t in doc.sentences]
        ranked = [u for u in _best(units, q, k=len(units)) if q & toks(u[1])] or _best(units, q)
        best = ranked[:2]
        sec_of = {sid: sec for sid, sec, _ in doc.sentences}
        other = next((u for u in ranked[2:] if sec_of[u[0]] not in {sec_of[b[0]] for b in best}), None)
        best = best + ([other] if other else [])
    else:
        raise ValueError(f"unknown strategy {strategy}")
    scanned = sum(len(t.split()) for _, t in units)
    return " ".join(t for _, t in best), [i for i, _ in best], scanned


def verify(doc: DocGraph, answer: str) -> bool:
    """Grounding: every answer word sequence must come from the document."""
    corpus = " ".join(" ".join(s.text.split()) for s in doc.sections)
    return all(" ".join(piece.split()) in corpus for piece in [answer]) if answer else False


def benchmark(doc: DocGraph, qa: list[tuple[str, tuple[str, ...]]], strategy: str) -> dict:
    correct = grounded = scanned = 0
    per_q = []
    for question, expected in qa:
        ans, cited, n = retrieve(doc, question, strategy)
        ok = all(e.lower() in ans.lower() for e in expected)
        correct += ok
        grounded += verify(doc, ans) or all(c in {sid for sid, _, _ in doc.sentences} for c in cited)
        scanned += n
        per_q.append(ok)
    n = len(qa)
    return {"strategy": strategy, "accuracy": round(correct / n, 4), "grounded": round(grounded / n, 4),
            "tokens_scanned": scanned, "per_question": per_q}


SAMPLE_PAPER = """# Adaptive Deliberation for Governed Agents

## Abstract
We propose adaptive deliberation, a method that scales reasoning depth with consequence and uncertainty. We show that adaptive loops reduce median latency while preserving answer accuracy on governed tasks [1].

## 1. Introduction
Fixed reasoning loops waste compute on easy requests (Smith et al., 2024). Governed agents must also stay responsive so the operator can act at all times [2].

## 2. Method
The controller selects one of three tiers: FAST, DEEP and GOVERNED.
Reasoning continues only while expected improvement exceeds marginal cost:
continue = E[improvement] > marginal_cost
The DEEP tier generates competing hypotheses and a critic verifies them against retrieved evidence.

## 3. Results
On 1,200 governed tasks, adaptive loops cut median latency from 2.4 s to 1.5 s. Long-document synthesis accuracy fell by 3.1% for the FAST tier, which is the main regression we observed. The GOVERNED tier never executed an action without an authority token.

## 4. Discussion
The FAST tier should escalate when a question spans several sections. We conclude that section-aware retrieval is the most promising fix, because cross-section questions are where flat retrieval fails.

## References
[1] Doe, J. Governed reasoning. 2025.
[2] Roe, R. Operator liveness in autonomous systems. 2024.
"""

SAMPLE_QA: list[tuple[str, tuple[str, ...]]] = [
    ("What median latency did adaptive loops achieve on governed tasks?", ("1.5",)),
    ("Which regression did the authors observe, and which fix do they conclude is most promising?", ("3.1%", "section-aware")),
    ("What rule decides whether reasoning continues?", ("marginal_cost",)),
    ("Which tiers does the controller select?", ("FAST", "DEEP", "GOVERNED")),
    ("Why must governed agents stay responsive?", ("operator",)),
]

STRATEGIES = ("flat_small", "flat_large", "section", "claim_graph")
