"""Graphviz DOT view of a plant graph, for checking topology by eye (render with `dot -Tsvg`).

Pipe segments are drawn as edges labelled with their line number rather than as nodes; signal edges
are dashed, impulse edges dotted.
"""
from .schema import PHYSICAL

SHAPES = {"equipment": "box", "valve": "diamond", "instrument": "circle", "fitting": "square",
          "offpage": "cds", "tee": "point", "end": "point"}


def _q(s):
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def to_dot(g):
    by_id = g.by_id()
    adj = g.adjacency(PHYSICAL)
    lines = ["graph pid {", '  graph [overlap=false, splines=true, fontname="Helvetica"];',
             '  node [fontname="Helvetica", fontsize=10]; edge [fontname="Helvetica", fontsize=8];']
    for n in g.nodes:
        if n.category == "pipe":
            continue
        label = n.tag or n.text or n.id
        lines.append(f"  {_q(n.id)} [shape={SHAPES.get(n.category, 'ellipse')}, label={_q(label)}];")
    done = set()
    for n in g.nodes:  # fold each pipe into one edge between its two ends
        if n.category != "pipe" or len(adj[n.id]) != 2:
            continue
        a, b = sorted(adj[n.id])
        done.add(n.id)
        lines.append(f"  {_q(a)} -- {_q(b)} [label={_q(n.line_number or '')}];")
    for e in g.edges:
        if e.src in done or e.dst in done:
            continue
        if by_id.get(e.src) and by_id.get(e.dst) and "pipe" in (by_id[e.src].category, by_id[e.dst].category):
            continue  # dangling pipe: already flagged by validate()
        style = {"signal": "dashed", "impulse": "dotted"}.get(e.kind, "solid")
        lines.append(f"  {_q(e.src)} -- {_q(e.dst)} [style={style}];")
    lines.append("}")
    return "\n".join(lines) + "\n"
