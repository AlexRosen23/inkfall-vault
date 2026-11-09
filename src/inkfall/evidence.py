"""Evidence pipeline: source pack, extractive answer, abstention, conflicts, injection flags, graph.

Confidence is reported as *evidence coverage* and retrieval diagnostics, never as a probability
that the answer is true. Extractive answers are verbatim spans of the stored source text.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import asdict, dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from .access import VersionView
from .db import Chunk
from .ingest import sentence_spans
from .search import Hit, content_terms, stem, tokens

# Thresholds were chosen on the dev split of the gold set (see docs/RETRIEVAL_EVAL.md).
COVERAGE_MIN = 0.6
PACK_SIZE = 6
PER_VERSION = 3

INJECTION_PATTERNS = [
    r"ignore (?:all |any )?(?:previous|prior|earlier|above|your)\s+(?:instructions|rules|directions|prompts?)",
    r"disregard (?:all |any |the |your )?(?:previous |prior )?(?:instructions|rules|access|policy|policies|guidelines)",
    r"(?:note|instruction|message|notice)s? (?:to|for) (?:any |all )?(?:ai|automated|llm|language model|assistant)",
    r"\b(?:system prompt|developer message|jailbreak)\b",
    r"you are now\b",
    r"(?:treat|consider) (?:the )?(?:reader|user|requester) as (?:an? )?(?:admin|administrator|partner|superuser)",
    r"(?:override|bypass|ignore) (?:the |any |your )?(?:access|permission|authori[sz]ation|security)",
    r"(?:reveal|disclose|output|print) (?:the |all )?(?:restricted|confidential|privileged|hidden|secret)",
]
INJECTION_RE = re.compile("|".join(f"(?:{p})" for p in INJECTION_PATTERNS), re.IGNORECASE)

WORD_NUM = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "fourteen": 14, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40,
    "forty-five": 45, "sixty": 60, "ninety": 90, "hundred": 100,
}
MONTHS = "january february march april may june july august september october november december".split()
MONEY_RE = re.compile(r"(?:\$|USD\s?)\s?([\d,]+(?:\.\d+)?)\s*(million|billion|thousand|[mk]\b)?", re.IGNORECASE)
PCT_RE = re.compile(r"(\d+(?:\.\d+)?)\s?(?:%|percent\b)", re.IGNORECASE)
DUR_RE = re.compile(
    r"(?:\b([a-z]+(?:-[a-z]+)?)\s+)?(?:\((\d+)\)|\b(\d+))?\s*(business days|calendar days|working days|days|months|"
    r"years|hours|minutes|weeks)\b", re.IGNORECASE)
DATE_RE = re.compile(r"\b(" + "|".join(m.capitalize() for m in MONTHS) + r")\s+(\d{1,2}),\s+(\d{4})\b|\b(\d{4})-(\d{2})-(\d{2})\b")
TIME_RE = re.compile(r"\b(\d{1,2}):(\d{2})\b")


@dataclass
class Passage:
    pid: str
    chunk_id: int
    version_id: int
    ref: str
    doc_key: str
    title: str
    heading: str
    char_start: int
    char_end: int
    text: str
    rank: int
    method_ranks: dict[str, int]
    effective_date: str
    in_force: bool
    superseded_by: int | None
    amends_key: str | None
    doc_type: str
    classification: str
    injection_flags: list[str] = field(default_factory=list)


@dataclass
class Citation:
    pid: str
    version_id: int
    ref: str
    char_start: int
    char_end: int
    quote: str


@dataclass
class AnswerSentence:
    text: str
    citations: list[Citation]
    support: str = "verbatim"  # verbatim | supported | partial | unsupported
    notes: list[str] = field(default_factory=list)


@dataclass
class Conflict:
    kind: str
    a: Citation
    b: Citation
    a_values: list[str]
    b_values: list[str]
    explanation: str


# ------------------------------------------------------------------ value extraction

def _dur_value(m: re.Match) -> str | None:
    word, paren, digits, unit = m.group(1), m.group(2), m.group(3), m.group(4).lower()
    n = None
    if paren:
        n = int(paren)
    elif digits:
        n = int(digits)
    elif word and word.lower() in WORD_NUM:
        n = WORD_NUM[word.lower()]
    if n is None:
        return None
    unit = unit.replace("calendar ", "").replace("working", "business")
    return f"{n} {unit}"


def extract_values(s: str) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {"money": set(), "percent": set(), "duration": set(), "date": set(), "time": set()}
    for m in MONEY_RE.finditer(s):
        num = float(m.group(1).replace(",", "") or 0)
        mult = (m.group(2) or "").lower()
        num *= {"million": 1e6, "m": 1e6, "billion": 1e9, "thousand": 1e3, "k": 1e3}.get(mult, 1)
        out["money"].add(f"${num:,.0f}")
    for m in PCT_RE.finditer(s):
        out["percent"].add(f"{float(m.group(1)):g}%")
    for m in DUR_RE.finditer(s):
        v = _dur_value(m)
        if v:
            out["duration"].add(v)
    for m in DATE_RE.finditer(s):
        if m.group(1):
            out["date"].add(f"{int(m.group(3)):04d}-{MONTHS.index(m.group(1).lower()) + 1:02d}-{int(m.group(2)):02d}")
        else:
            out["date"].add(f"{m.group(4)}-{m.group(5)}-{m.group(6)}")
    for m in TIME_RE.finditer(s):
        out["time"].add(f"{int(m.group(1)):02d}:{m.group(2)}")
    return out


def asked_types(question: str) -> set[str]:
    q = question.lower()
    want: set[str] = set()
    if re.search(r"\bhow much\b|\bfee|\bcost|\bcap\b|\bamount|\bprice|\bpay|\$|\blimit|\bthreshold|\bbudget|\bvalue", q):
        want.add("money")
    if re.search(r"percent|%|\buptime|\brate\b|\bavailability", q):
        want.add("percent")
    if re.search(r"\bhow (?:many|long)\b|\bdays?\b|\bmonths?\b|\byears?\b|\bperiod|\bnotice|\bwithin\b|\bhours?\b|\bretain|\bretention", q):
        want.add("duration")
    if re.search(r"\bwhen\b|\bdate\b|\bdeadline|\bexpire|\beffective|\bby what", q):
        want.add("date")
    if re.search(r"\bwhat time\b|\bstart(?:ed)? at\b|\btime\b", q):
        want.add("time")
    return want


# ------------------------------------------------------------------ pack + answer

def detect_injection(s: str) -> list[str]:
    return [m.group(0) for m in INJECTION_RE.finditer(s)]


def build_pack(session: Session, hits: list[Hit], views: dict[int, VersionView], size: int = PACK_SIZE) -> list[Passage]:
    pack: list[Passage] = []
    per: dict[int, int] = {}
    ids = [h.chunk_id for h in hits[: size * 4]]
    chunks = {c.id: c for c in session.scalars(select(Chunk).where(Chunk.id.in_(ids)))} if ids else {}
    for h in hits:
        if len(pack) >= size:
            break
        view = views.get(h.version_id)
        c = chunks.get(h.chunk_id)
        if view is None or c is None:  # not authorized / not loaded -> never enters the pack
            continue
        if per.get(h.version_id, 0) >= PER_VERSION:
            continue
        per[h.version_id] = per.get(h.version_id, 0) + 1
        v = view.version
        assert v.text[c.char_start:c.char_end] == c.text, "chunk offset invariant violated"
        pack.append(Passage(
            pid=f"P{len(pack) + 1}", chunk_id=c.id, version_id=v.id, ref=view.ref, doc_key=view.document.doc_key,
            title=v.title, heading=c.heading, char_start=c.char_start, char_end=c.char_end, text=c.text,
            rank=h.rank, method_ranks=dict(h.components), effective_date=v.effective_date.isoformat(),
            in_force=view.in_force, superseded_by=view.superseded_by, amends_key=v.amends_key,
            doc_type=view.document.doc_type, classification=v.classification,
            injection_flags=detect_injection(c.text),
        ))
    return pack


def coverage(question: str, pack: list[Passage], top: int = 3) -> tuple[float, list[str], list[str]]:
    terms = content_terms(question)
    if not terms:
        return 0.0, [], []
    hay = set()
    for p in pack[:top]:
        hay.update(stem(t) for t in tokens(f"{p.title} {p.heading} {p.text}"))
    found = [t for t in terms if stem(t) in hay]
    missing = [t for t in terms if stem(t) not in hay]
    return len(found) / len(terms), found, missing


def _cite(p: Passage, a: int, b: int, version_text: str) -> Citation:
    return Citation(p.pid, p.version_id, p.ref, a, b, version_text[a:b])


def extractive_answer(question: str, pack: list[Passage], texts: dict[int, str], max_sentences: int = 3) -> list[AnswerSentence]:
    q_stems = {stem(t) for t in content_terms(question)}
    want = asked_types(question)
    scored: list[tuple[float, Passage, int, int]] = []
    for p in pack:
        body = texts[p.version_id]
        for a, b in sentence_spans(body, p.char_start, p.char_end):
            s = body[a:b]
            if detect_injection(s):
                continue  # never quote an embedded instruction as an answer
            st = {stem(t) for t in tokens(s)}
            overlap = len(q_stems & st)
            if overlap == 0:
                continue
            vals = extract_values(s)
            bonus = 0.75 if any(vals[t] for t in want) else 0.0
            scored.append((overlap + bonus - 0.05 * p.rank, p, a, b))
    scored.sort(key=lambda x: -x[0])
    out: list[AnswerSentence] = []
    used: set[tuple[int, int, int]] = set()
    for score, p, a, b in scored:
        if len(out) >= max_sentences:
            break
        if score < 1.0 or (p.version_id, a, b) in used:
            continue
        used.add((p.version_id, a, b))
        out.append(AnswerSentence(texts[p.version_id][a:b].strip(), [_cite(p, a, b, texts[p.version_id])]))
    for s in out:  # trim citation to the stripped sentence so the span is exact
        c = s.citations[0]
        lead = len(c.quote) - len(c.quote.lstrip())
        c.char_start += lead
        c.char_end = c.char_start + len(s.text)
        c.quote = s.text
    return out


def _best_sentence(p: Passage, q_stems: set[str], body: str) -> tuple[int, int] | None:
    best, best_s = None, 0
    for a, b in sentence_spans(body, p.char_start, p.char_end):
        s = len(q_stems & {stem(t) for t in tokens(body[a:b])})
        if s > best_s:
            best, best_s = (a, b), s
    return best


def find_conflicts(question: str, pack: list[Passage], texts: dict[int, str], top: int = 5) -> tuple[list[Conflict], list[str]]:
    """Value disagreements between in-force passages of different documents on the asked topic.

    Amendment relationships are reported as overrides, not as contradictions.
    """
    q_stems = {stem(t) for t in content_terms(question)}
    want = asked_types(question) or {"money", "percent", "duration", "date", "time"}
    conflicts: list[Conflict] = []
    overrides: list[str] = []
    cands = [p for p in pack[:top] if p.in_force]
    best = {p.pid: _best_sentence(p, q_stems, texts[p.version_id]) for p in cands}
    for i, a in enumerate(cands):
        for b in cands[i + 1:]:
            if a.doc_key == b.doc_key:
                continue
            sa, sb = best[a.pid], best[b.pid]
            if not sa or not sb:
                continue
            ta, tb = texts[a.version_id][sa[0]:sa[1]], texts[b.version_id][sb[0]:sb[1]]
            shared_topic = q_stems & {stem(t) for t in tokens(ta)} & {stem(t) for t in tokens(tb)}
            if len(shared_topic) < 2:
                continue
            va, vb = extract_values(ta), extract_values(tb)
            for kind in sorted(want):
                if va[kind] and vb[kind] and not (va[kind] & vb[kind]):
                    if a.amends_key == b.doc_key or b.amends_key == a.doc_key:
                        amd, base = (a, b) if a.amends_key == b.doc_key else (b, a)
                        overrides.append(f"{amd.ref} amends {base.ref}: {kind} differs; the amendment governs "
                                         f"from {amd.effective_date}.")
                        continue
                    conflicts.append(Conflict(
                        kind, _cite(a, *sa, texts[a.version_id]), _cite(b, *sb, texts[b.version_id]),
                        sorted(va[kind]), sorted(vb[kind]),
                        f"Two in-force documents state different {kind} values on the same topic "
                        f"({', '.join(sorted(shared_topic))}). Shown side by side; not resolved automatically."))
                    break
    return conflicts, overrides


def freshness(pack: list[Passage], as_of: dt.date) -> list[str]:
    notes = []
    seen = set()
    for p in pack:
        if p.ref in seen:
            continue
        seen.add(p.ref)
        age = (as_of - dt.date.fromisoformat(p.effective_date)).days
        if not p.in_force:
            notes.append(f"{p.ref} is historical: superseded by v{p.superseded_by}.")
        elif age > 3 * 365:
            notes.append(f"{p.ref} took effect {p.effective_date} ({age // 365} years before the as-of date).")
    return notes


@dataclass
class Assessment:
    abstained: bool
    abstain_reason: str | None
    coverage: float
    matched_terms: list[str]
    missing_terms: list[str]
    gaps: list[str]


def assess(question: str, pack: list[Passage], answer: list[AnswerSentence]) -> Assessment:
    cov, found, missing = coverage(question, pack)
    gaps: list[str] = []
    if not pack:
        return Assessment(True, "No authorized document matched this question.", 0.0, [], content_terms(question),
                          ["No passages in your authorized scope matched."])
    if missing:
        gaps.append("Not found in the top authorized passages: " + ", ".join(missing))
    proper = _proper_nouns(question)
    hay = " ".join(f"{p.title} {p.heading} {p.text}" for p in pack).lower()
    absent = [n for n in proper if n.lower() not in hay]
    if absent:
        return Assessment(True, "Named subject(s) not present in any authorized evidence: " + ", ".join(absent) + ".",
                          cov, found, missing, gaps)
    if cov < COVERAGE_MIN:
        return Assessment(True, f"Evidence covers {cov:.0%} of the question's key terms (minimum {COVERAGE_MIN:.0%}).",
                          cov, found, missing, gaps)
    if not answer:
        return Assessment(True, "No sentence in the authorized evidence directly addresses the question.", cov,
                          found, missing, gaps)
    return Assessment(False, None, cov, found, missing, gaps)


COMMON_CAPS = set("""
What When Where Which Who Whom Why How Does Do Did Is Are Was Were Can Could Should Would Will Under Per The A An
In On For To Of And Or If Please Tell Show List Give Find According Our Their Its This That These Those As At By
Ignore Disregard System Note Admin Also Any All MSA SLA NDA PDF AI I Is
""".split())


def _proper_nouns(question: str) -> list[str]:
    words = re.findall(r"\b[A-Z][a-zA-Z]{2,}\b", question)
    out = []
    for i, w in enumerate(words):
        if w in COMMON_CAPS:
            continue
        if question.strip().startswith(w) and i == 0:
            continue
        if w not in out:
            out.append(w)
    return out


# ------------------------------------------------------------------ graph (metadata + retrieval links only)

def evidence_graph(pack: list[Passage], views: dict[int, VersionView], answer: list[AnswerSentence],
                   conflicts: list[Conflict]) -> dict:
    nodes: dict[str, dict] = {"q": {"id": "q", "kind": "question", "label": "Question"}}
    edges: list[dict] = []
    cited = {(c.version_id, c.char_start) for s in answer for c in s.citations}
    by_key: dict[str, list[VersionView]] = {}
    for v in views.values():
        by_key.setdefault(v.document.doc_key, []).append(v)
    for p in pack:
        did = f"d{p.version_id}"
        if did not in nodes:
            view = views[p.version_id]
            nodes[did] = {"id": did, "kind": "document", "label": p.ref, "title": p.title, "doc_type": p.doc_type,
                          "effective_date": p.effective_date, "in_force": p.in_force, "version_id": p.version_id}
            for party in view.version.parties or []:
                eid = "e:" + party
                nodes.setdefault(eid, {"id": eid, "kind": "entity", "label": party})
                edges.append({"from": did, "to": eid, "kind": "party"})
        cid = f"c{p.chunk_id}"
        nodes[cid] = {"id": cid, "kind": "clause", "label": p.heading or p.pid, "pid": p.pid,
                      "cited": any(vid == p.version_id and p.char_start <= s < p.char_end for vid, s in cited),
                      "injection": bool(p.injection_flags)}
        edges.append({"from": "q", "to": cid, "kind": "retrieved", "rank": p.rank})
        edges.append({"from": cid, "to": did, "kind": "part_of"})
    doc_nodes = {n["version_id"]: n for n in nodes.values() if n["kind"] == "document"}
    for vid in doc_nodes:
        v = views[vid]
        if v.version.amends_key:
            for other in by_key.get(v.version.amends_key, []):
                if other.version.id in doc_nodes:
                    edges.append({"from": f"d{vid}", "to": f"d{other.version.id}", "kind": "amends"})
        for other in by_key.get(v.document.doc_key, []):
            if other.version.id in doc_nodes and other.version.version == v.version.version + 1:
                edges.append({"from": f"d{other.version.id}", "to": f"d{vid}", "kind": "supersedes"})
    pid_to_chunk = {p.pid: p.chunk_id for p in pack}
    for c in conflicts:
        edges.append({"from": f"c{pid_to_chunk[c.a.pid]}", "to": f"c{pid_to_chunk[c.b.pid]}", "kind": "contradicts",
                      "label": c.kind})
    return {"nodes": list(nodes.values()), "edges": edges}


def to_dict(obj) -> dict:
    return asdict(obj)
