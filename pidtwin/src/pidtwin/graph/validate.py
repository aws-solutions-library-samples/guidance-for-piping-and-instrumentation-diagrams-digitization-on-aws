"""Consistency rules for a P&ID graph. Each issue names the node so it can be fed back to the
review agent (see pidtwin/digitize/review.py) or a human reviewer."""
import re
from collections import Counter

from pydantic import BaseModel

from ..common import norm

# printed-tag patterns; a tag that does not fit is probably misread
TAG_RE = {
    "valve": re.compile(r"^[A-Z]{1,5}-\d+(-\d+)?$"),
    "instrument": re.compile(r"^[A-Z]{1,5}-\d+(-\d+)?$"),
}


class Issue(BaseModel):
    level: str   # "error" | "warning" | "info"
    code: str
    node: str | None = None
    message: str


def validate(g):
    issues = []
    add = lambda level, code, node, msg: issues.append(Issue(level=level, code=code, node=node, message=msg))
    by_id = g.by_id()
    for e in g.edges:
        for end in (e.src, e.dst):
            if end not in by_id:
                add("error", "unknown_node", end, f"edge {e.src}-{e.dst} refers to missing node {end}")
    proc = g.adjacency(("process",))
    phys = g.adjacency()
    anyk = g.adjacency(("process", "impulse", "signal"))
    for n in g.nodes:
        d = len(proc[n.id])
        if not anyk[n.id]:
            add("warning", "isolated", n.id, f"{n.category} {n.tag or n.id} has no connections")
        elif n.category == "pipe" and d != 2:
            add("warning", "dangling_pipe", n.id,
                f"pipe segment on run {n.attrs.get('run')} with {d} process connections (expected 2)")
        elif n.category == "valve" and d != 2:
            add("warning", "valve_degree", n.id,
                f"valve {n.tag or n.id} has {d} process connections (expected 2: one in, one out)")
        elif n.category == "tee" and d < 3:
            add("warning", "tee_degree", n.id, f"tee with {d} process connections")
        elif n.category == "equipment" and not phys[n.id]:
            add("warning", "equipment_unpiped", n.id, f"equipment {n.tag or n.id} has no piping connection")
        elif n.category == "offpage" and not n.text:
            add("warning", "offpage_target", n.id, "off-page connector without destination text")
        if n.category in TAG_RE and n.tag and not TAG_RE[n.category].match(n.tag.strip()):
            add("warning", "tag_pattern", n.id, f"tag {n.tag!r} does not look like a {n.category} tag")
    flagged = set()
    for n in g.nodes:
        labs, run = n.attrs.get("line_labels"), n.attrs.get("run")
        if n.category == "pipe" and labs and run not in flagged:
            flagged.add(run)
            add("warning", "multiple_line_numbers", n.id,
                f"run {run} has {len(labs)} line-number labels along it ({', '.join(labs)}) but carries "
                f"{n.line_number}; it may be two lines - split it where the label changes")
    dup = Counter(norm(n.tag) for n in g.nodes if n.tag and n.category in ("valve", "instrument"))
    for n in g.nodes:
        if n.tag and n.category in ("valve", "instrument") and dup[norm(n.tag)] > 1:
            add("warning", "duplicate_tag", n.id, f"tag {n.tag} appears {dup[norm(n.tag)]} times")
    ends = sum(n.category == "end" for n in g.nodes)
    if ends:
        add("info", "open_ends", None, f"{ends} line ends without a symbol")
    return issues


def summary(issues):
    return dict(Counter(f"{i.level}:{i.code}" for i in issues))
