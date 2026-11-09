"""Evidence pipeline: source pack, extractive answer, abstention, conflicts, injection flags, graph.

Confidence is reported as *evidence coverage* and retrieval diagnostics, never as a probability
that the answer is true. Extractive answers are verbatim spans of the stored source text.
"""

from __future__ import annotations

import datetime as dt
import math
import re
from dataclasses import asdict, dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from .access import VersionView
from .db import Chunk
from .ingest import sentence_spans
from .search import SYNONYMS, Hit, content_terms, stem, tokens

# Thresholds were chosen on the dev split of the gold set (see docs/RETRIEVAL_EVAL.md).
COVERAGE_MIN = 0.5
PACK_SIZE = 6
PER_VERSION = 3

INJECTION_PATTERNS = [
    r"\b(?:ignore|disregard|forget|override|bypass)\s+(?:all\s+|any\s+)?(?:of\s+)?(?:your|their|its|the|my|these|those)?\s*"
    r"(?:previous|prior|earlier|above|existing|own)?\s*(?:instructions|rules|directions|prompts?|guidelines|"
    r"access(?:\s+(?:rules|policy|policies|controls|restrictions))?|permissions?|authori[sz]ation|security|policy|policies)",
    r"(?:note|instruction|message|notice)s?\s+(?:to|for)\s+(?:any\s+|all\s+)?(?:ai|automated|llm|language model|assistant)",
    r"\b(?:ai|automated)\s+(?:assistants?|tools?|reviewers?|readers?|systems?)\b[^.]{0,80}\b(?:must|should|shall)\b",
    r"\b(?:system prompt|developer message|jailbreak|maintenance mode)\b",
    r"\byou are now\b",
    r"(?:treat|consider)\s+(?:the\s+)?(?:reader|user|requester|me)\s+as\s+(?:an?\s+)?(?:admin|administrator|partner|superuser)",
    r"(?:reveal|disclose|output|print|append|paste)\s+(?:the\s+|all\s+|every\s+)?(?:full\s+text\s+of\s+)?"
    r"(?:restricted|confidential|privileged|hidden|secret|closed-session)",
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
    if re.search(r"\bhow much\b|\bfee|\bcost|\bcap\b|\bamount|\bprice|\bpay|\$|\blimit|\bthreshold|\bbudget|\bvalue"
                 r"|\bcharge|\bbill|\bowe|\bspend|\bcash|\brebate|\brate\b", q):
        want.add("money")
    if re.search(r"\bminimum\b|\bmaximum\b|\bat least\b|\bno more than\b|\bhow (?:many|much)\b", q):
        want.update({"money", "percent", "duration"})
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
    def present(t: str) -> bool:
        return stem(t) in hay or any(stem(x) in hay for x in SYNONYMS.get(t, []))

    found = [t for t in terms if present(t)]
    missing = [t for t in terms if not present(t)]
    return len(found) / len(terms), found, missing


def _cite(p: Passage, a: int, b: int, version_text: str) -> Citation:
    return Citation(p.pid, p.version_id, p.ref, a, b, version_text[a:b])


def _query_stems(question: str) -> set[str]:
    out = set()
    for t in content_terms(question):
        out.add(stem(t))
        out.update(stem(x) for x in SYNONYMS.get(t, []))
    return out


def _sentence_candidates(pack: list[Passage], texts: dict[int, str]) -> list[tuple[Passage, int, int, set[str]]]:
    out = []
    for p in pack:
        body = texts[p.version_id]
        for a, b in sentence_spans(body, p.char_start, p.char_end):
            out.append((p, a, b, {stem(t) for t in tokens(body[a:b])}))
    return out


def _idf(cands) -> dict[str, float]:
    df: dict[str, int] = {}
    for *_, st in cands:
        for t in st:
            df[t] = df.get(t, 0) + 1
    n = max(1, len(cands))
    return {t: math.log(1 + n / c) for t, c in df.items()}


def extractive_answer(question: str, pack: list[Passage], texts: dict[int, str], max_sentences: int = 3) -> list[AnswerSentence]:
    """Pick verbatim sentences: query-term matches weighted by rarity within the pack (IDF), a bonus when the
    sentence carries the kind of value the question asks for, and a small prior for higher-ranked passages."""
    q_stems = _query_stems(question)
    want = asked_types(question)
    cands = _sentence_candidates(pack, texts)
    idf = _idf(cands)
    max_w = sum(sorted((idf.get(t, 0.0) for t in q_stems), reverse=True)[:3]) or 1.0
    scored: list[tuple[float, Passage, int, int]] = []
    for p, a, b, st in cands:
        s = texts[p.version_id][a:b]
        if detect_injection(s):
            continue  # never quote an embedded instruction as an answer
        matched = q_stems & st
        if not matched:
            continue
        w = sum(idf.get(t, 0.0) for t in matched) / max_w
        vals = extract_values(s)
        bonus = 0.6 if any(vals[t] for t in want) else 0.0
        scored.append((w + bonus - 0.03 * p.rank, p, a, b))
    scored.sort(key=lambda x: -x[0])
    out: list[AnswerSentence] = []
    used: set[tuple[int, int, int]] = set()
    for score, p, a, b in scored:
        if len(out) >= max_sentences:
            break
        if score < 0.45 or (p.version_id, a, b) in used:
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


def _concepts(question: str) -> dict[str, set[str]]:
    """Query concept -> the stems that express it (the term itself plus its synonyms)."""
    return {t: {stem(t)} | {stem(x) for x in SYNONYMS.get(t, [])} for t in content_terms(question)}


def _best_value_sentence(p: Passage, concepts: dict[str, set[str]], want: set[str], body: str):
    """Highest concept-overlap sentence in the passage that carries a value of an asked type."""
    best, best_s = None, 0
    for a, b in sentence_spans(body, p.char_start, p.char_end):
        seg = body[a:b]
        vals = extract_values(seg)
        if not any(vals[k] for k in want):
            continue
        st = {stem(t) for t in tokens(seg)}
        s = sum(1 for forms in concepts.values() if forms & st)
        if s > best_s:
            best, best_s = (a, b, st, vals), s
    return best


def _units(kind: str, values: set[str]) -> dict[str, set[str]]:
    """Group values by unit so '5 business days' is never compared with '45 days'."""
    if kind != "duration":
        return {kind: values}
    out: dict[str, set[str]] = {}
    for v in values:
        n, unit = v.split(" ", 1)
        out.setdefault(unit, set()).add(n)
    return out


def find_conflicts(question: str, pack: list[Passage], texts: dict[int, str], top: int = 6) -> tuple[list[Conflict], list[str]]:
    """Testable contradiction rule (no model involved). Two passages conflict when ALL hold:
    1. both versions are in force on the as-of date and belong to different documents;
    2. the question asks for a value type (money, %, duration, date, time) and each passage has a sentence
       carrying that type which matches >= 1 shared query concept (term or synonym);
    3. every named subject in the question (e.g. "Orion") appears in both documents (same subject, so
       look-alike contracts with other parties are not compared);
    4. for some unit present in both sentences, the value sets are disjoint.
    If one document amends the other, the pair is reported as an amendment override instead, and a base
    document with an in-force amendment in the pack is not compared on the amended value type.
    """
    want = asked_types(question)
    if not want:
        return [], []
    concepts = _concepts(question)
    subjects = [n.lower() for n in _proper_nouns(question)]
    cands = [p for p in pack[:top] if p.in_force]
    docs_text = {p.version_id: texts[p.version_id].lower() + " " + p.title.lower() for p in cands}
    cands = [p for p in cands if all(sj in docs_text[p.version_id] for sj in subjects)]
    amended = {p.amends_key for p in cands if p.amends_key}
    best = {p.pid: _best_value_sentence(p, concepts, want, texts[p.version_id]) for p in cands}
    conflicts: list[Conflict] = []
    overrides: list[str] = []
    seen_pairs: set[tuple[str, str, str]] = set()
    for i, a in enumerate(cands):
        for b in cands[i + 1:]:
            if a.doc_key == b.doc_key or not best[a.pid] or not best[b.pid]:
                continue
            (sa0, sa1, sta, va), (sb0, sb1, stb, vb) = best[a.pid], best[b.pid]
            shared = [c for c, forms in concepts.items() if forms & sta and forms & stb]
            if not shared:
                continue
            for kind in sorted(want):
                if not (va[kind] and vb[kind]):
                    continue
                ua, ub = _units(kind, va[kind]), _units(kind, vb[kind])
                common = [u for u in ua if u in ub]
                if not common or any(ua[u] & ub[u] for u in common):
                    continue
                key = tuple(sorted((a.doc_key, b.doc_key))) + (kind,)
                if key in seen_pairs:
                    continue
                seen_pairs.add(key)
                if a.amends_key == b.doc_key or b.amends_key == a.doc_key:
                    amd, base = (a, b) if a.amends_key == b.doc_key else (b, a)
                    overrides.append(f"{amd.ref} amends {base.ref}: the {kind} differs; the amendment governs "
                                     f"from {amd.effective_date}.")
                    continue
                if a.doc_key in amended or b.doc_key in amended:
                    base = a if a.doc_key in amended else b
                    overrides.append(f"{base.ref} has an in-force amendment in the evidence; its original {kind} "
                                     "is not treated as a contradiction.")
                    continue
                conflicts.append(Conflict(
                    kind, _cite(a, sa0, sa1, texts[a.version_id]), _cite(b, sb0, sb1, texts[b.version_id]),
                    sorted(va[kind]), sorted(vb[kind]),
                    f"Two in-force documents give different {kind} values for the same subject "
                    f"({', '.join(shared)}). Shown side by side; not resolved automatically."))
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
Ignore Disregard System Note Admin Also Any All MSA SLA NDA PDF AI I Is Back Above Below Before After Since
January February March April May June July August September October November December
Monday Tuesday Wednesday Thursday Friday Saturday Sunday SYSTEM Pretend Respond Follow Summarize Quote Print
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
