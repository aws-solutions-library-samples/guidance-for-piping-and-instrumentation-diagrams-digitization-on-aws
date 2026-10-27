"""Merge per-sheet graphs into one plant graph.

Node ids get a "<sheet>/" prefix. Sheets are stitched in two ways:
- equipment drawn on several sheets (same tag, unique on each sheet) becomes one node;
- off-page connectors are paired across sheets when their pipes carry the same line number, or when
  one connector's text names the other sheet; each pair is joined by a process edge.
"""
from collections import Counter, defaultdict

from ..common import norm
from .schema import Edge, Graph


def merge(graphs):
    out = Graph(source="pid")
    eq_by_tag, offpage = {}, []
    alias = {}
    for g in graphs:
        sheet = g.sheets[0]["id"] if g.sheets else f"sheet{len(out.sheets) + 1}"
        out.sheets += g.sheets or [{"id": sheet}]
        out.warnings += [f"{sheet}: {w}" for w in g.warnings]
        proc = g.adjacency(("process",))
        by_id = g.by_id()
        local = Counter(norm(n.tag) for n in g.nodes if n.category == "equipment" and n.tag)
        for n in g.nodes:
            nid = f"{sheet}/{n.id}"
            unique = n.category == "equipment" and n.tag and local[norm(n.tag)] == 1
            if unique and norm(n.tag) in eq_by_tag:
                alias[nid] = eq_by_tag[norm(n.tag)]
                continue
            lines = {norm(by_id[m].line_number) for m in proc[n.id] if by_id[m].line_number}
            n = n.model_copy(update={"id": nid, "sheet": sheet})
            if unique:
                eq_by_tag[norm(n.tag)] = nid
            if n.category == "offpage":
                offpage.append((n, sheet, lines))
            out.nodes.append(n)
        for e in g.edges:
            out.edges.append(e.model_copy(update={"src": f"{sheet}/{e.src}", "dst": f"{sheet}/{e.dst}"}))
    for e in out.edges:
        e.src, e.dst = alias.get(e.src, e.src), alias.get(e.dst, e.dst)

    # pair off-page connectors across sheets
    sheet_nums = {s["id"]: norm(s.get("number") or s["id"]) for s in out.sheets}
    used = set()
    by_line = defaultdict(list)
    for n, sheet, lines in offpage:
        for ln in lines:
            by_line[ln].append((n, sheet))
    pairs = []
    for ln, group in by_line.items():
        group = [(n, s) for n, s in group if n.id not in used]
        cross = [(a, b) for i, a in enumerate(group) for b in group[i + 1:] if a[1] != b[1]]
        if len(cross) == 1:
            pairs.append((cross[0][0][0], cross[0][1][0], f"line {ln}"))
            used |= {cross[0][0][0].id, cross[0][1][0].id}
        elif cross:
            out.warnings.append(f"line {ln}: {len(group)} off-page connectors on several sheets - not stitched")
    for n, sheet, _ in offpage:
        if n.id in used:
            continue
        target = next((s for s, num in sheet_nums.items() if s != sheet and num and num in norm(n.text)), None)
        if not target:
            continue
        back = [m for m, s, _ in offpage if s == target and m.id not in used and sheet_nums[sheet] in norm(m.text)]
        if len(back) == 1:
            pairs.append((n, back[0], f"sheet reference {n.text!r}"))
            used |= {n.id, back[0].id}
    for a, b, why in pairs:
        out.edges.append(Edge(src=a.id, dst=b.id, kind="process", run="offpage"))
        a.attrs["stitched_to"], b.attrs["stitched_to"] = b.id, a.id
        a.attrs["stitch_reason"] = b.attrs["stitch_reason"] = why
    unstitched = [n.id for n, _, _ in offpage if n.id not in used]
    if unstitched and len(graphs) > 1:
        out.warnings.append(f"{len(unstitched)} off-page connectors not stitched: {unstitched[:20]}")
    return out
