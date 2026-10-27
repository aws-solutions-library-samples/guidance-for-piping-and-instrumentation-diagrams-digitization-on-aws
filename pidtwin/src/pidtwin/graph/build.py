"""Digitizer output (results/<sheet>.<model>.json from pidtwin.digitize.pipeline) -> canonical Graph.

Every physical run becomes a chain  end - pipe - item - pipe - item ... - pipe - end, cut at each
inline item and at each tee where another run joins it. Signal runs become direct signal edges;
impulse runs become direct impulse edges (no pipe nodes: instrument tubing is not piping).
"""
import math
import re

from ..common import _along, centre, derive_connections, norm
from .schema import Edge, Graph, Node

TEE_MERGE = 4.0  # sheet units: joins closer than this along a run share one tee (a cross)
SAMPLE_REACH = 15.0  # sheet units: max distance from an unconnected sample point to its flange
LABEL_REACH = 10.0  # sheet units: a line-number label this close to a run's path is printed along it
END_SNAP = 10.0  # sheet units: a bare run end this close to another run's path joins that run

# (category, keyword in the digitizer's free-text type) -> DEXPI 1.3 class. First match wins.
# Best effort: check names against the DEXPI spec before relying on them downstream.
CLASS_RULES = [
    ("valve", "butterfly", "ButterflyValve"), ("valve", "ball", "BallValve"), ("valve", "gate", "GateValve"),
    ("valve", "globe", "GlobeValve"), ("valve", "check", "CheckValve"), ("valve", "relief", "SafetyValveOrFitting"),
    ("valve", "safety", "SafetyValveOrFitting"), ("valve", "control", "OperatedValve"),
    ("valve", "solenoid", "OperatedValve"), ("valve", "needle", "NeedleValve"), ("valve", "plug", "PlugValve"),
    ("valve", "", "CustomValve"),
    ("equipment", "pump", "CentrifugalPump"), ("equipment", "compressor", "CentrifugalCompressor"),
    ("equipment", "exchanger", "HeatExchanger"), ("equipment", "heater", "Heater"), ("equipment", "tank", "Tank"),
    ("equipment", "vessel", "Vessel"), ("equipment", "column", "ProcessColumn"),
    ("equipment", "strainer", "CustomEquipment"), ("equipment", "", "CustomEquipment"),
    ("fitting", "sample", "CustomPipingComponent"), ("fitting", "blind", "BlindFlange"), ("fitting", "cap", "BlindFlange"), ("fitting", "spectacle", "LineBlind"),
    ("fitting", "orifice", "RestrictionOrifice"), ("fitting", "reducer", "PipeReducer"),
    ("fitting", "strainer", "CustomPipingComponent"), ("fitting", "flange", "Flange"),
    ("fitting", "", "CustomPipingComponent"),
    ("instrument", "", "ProcessInstrumentationFunction"),
    ("offpage", "", "PipeOffPageConnector"), ("tee", "", "PipeTee"), ("pipe", "", "PipingNetworkSegment"),
    ("end", "", None),
]
LINE_RE = re.compile(r'^\s*(\d+(?:[./]\d+)?\s*["”″]?)\s*-\s*([A-Z]+)\s*-\s*([A-Z0-9]+)(?:\s*-\s*(\S+))?', re.I)
SIZE_RE = re.compile(r'^\s*(\d+(?:[./]\d+)?)\s*["”″]\s*$')


def dexpi_class(category, type_text):
    t = (type_text or "").lower()
    return next(c for cat, kw, c in CLASS_RULES if cat == category and kw in t)


def parse_line_number(s):
    """'6"-DW-1865' -> ('6"', 'DW'); unparseable -> (None, None)."""
    m = LINE_RE.match(s or "")
    if not m:
        return None, None
    size = re.sub(r'\s|["”″]', "", m.group(1)) + '"'
    return size, m.group(2).upper()


def _items(out):
    """Flatten the digitizer's per-category lists back into {id: item} with a uniform shape."""
    items = {}
    for cat, key in (("equipment", "equipment"), ("valve", "valves"), ("instrument", "instruments"),
                     ("fitting", "fittings"), ("offpage", "offpage")):
        for it in out.get(key, []):
            iid = it.get("label") if cat == "offpage" else it.get("id")
            if not iid or not it.get("bbox"):
                continue
            items[iid] = {"id": iid, "category": cat, "bbox": it["bbox"],
                          "type": it.get("type") or it.get("function"),
                          "tag": None if cat in ("fitting", "offpage") else it.get("tag"),
                          "text": it.get("text") or it.get("description")}
    return items


def _fold_sample_points(items, runs, warn):
    """A sample-point symbol on a stem off a flange is part of one 'sample connection'. When the
    digitizer listed the symbol on its own and no run uses it, fold it into the nearest flange."""
    used = {i for r in runs for i in r.get("items") or []}
    flanges = [it for it in items.values() if it["category"] == "fitting" and it["id"] in used
               and any(k in (it["type"] or "").lower() for k in ("flange", "orifice", "sample"))]
    for it in [it for it in items.values() if it["category"] == "fitting" and it["id"] not in used
               and "sample" in (it["type"] or "").lower()]:
        size = max(it["bbox"][2] - it["bbox"][0], it["bbox"][3] - it["bbox"][1])
        near = min(flanges, key=lambda f: math.dist(centre(f["bbox"]), centre(it["bbox"])), default=None)
        if near and math.dist(centre(near["bbox"]), centre(it["bbox"])) <= max(SAMPLE_REACH, 2 * size):
            del items[it["id"]]
            near["type"] = "sample connection"
            near["bbox"] = [min(near["bbox"][0], it["bbox"][0]), min(near["bbox"][1], it["bbox"][1]),
                            max(near["bbox"][2], it["bbox"][2]), max(near["bbox"][3], it["bbox"][3])]
            warn(f"{it['id']}: unconnected sample point folded into {near['id']} (sample connection)")


def _dist(path, pt):
    """Shortest distance from pt to a polyline."""
    best = float("inf")
    for a, b in zip(path, path[1:]):
        seg = math.dist(a, b) or 1e-9
        u = max(0.0, min(1.0, ((pt[0] - a[0]) * (b[0] - a[0]) + (pt[1] - a[1]) * (b[1] - a[1])) / seg ** 2))
        best = min(best, math.dist(pt, (a[0] + u * (b[0] - a[0]), a[1] + u * (b[1] - a[1]))))
    return best


def _labels_along(path, labels):
    """Distinct line numbers whose printed label sits along the path."""
    found = {}
    for lab in labels:
        if path and _dist(path, centre(lab["bbox"])) <= LABEL_REACH:
            found.setdefault(norm(lab["line_number"]), lab["line_number"])
    return sorted(found.values())


def _physical_runs(runs, warn, dashed_as_piping=False):
    """Process runs, plus signal runs that carry a line number or that a physical run tees into
    (on some sheets dashed lines are alternate piping, not signals). With dashed_as_piping every
    signal run is piping (sheets whose notes say dotted lines are alternates)."""
    by_id = {r.get("id"): r for r in runs}
    kinds = ("process", "signal") if dashed_as_piping else ("process",)
    phys = {r["id"] for r in runs if r.get("kind") in kinds}
    for r in runs:
        if r.get("kind") == "signal" and r.get("line_number"):
            phys.add(r["id"])
            warn(f"{r['id']}: signal run carries line number {r['line_number']} - treated as piping")
    changed = True
    while changed:
        changed = False
        for rid in list(phys):
            seq = by_id[rid].get("items") or []
            for ref in seq[:1] + seq[-1:]:
                if ref in by_id and ref not in phys and by_id[ref].get("kind") != "impulse":
                    phys.add(ref)
                    changed = True
                    warn(f"{ref}: {by_id[ref].get('kind')} run is teed into by piping run {rid} - treated as piping")
    return phys


def _path(r):
    p = [q for q in r.get("path") or [] if isinstance(q, (list, tuple)) and len(q) == 2]
    return p if len(p) >= 2 else None


def build_graph(out, sheet=None, dashed_as_piping=False):
    """out: dict loaded from a digitizer result JSON. Returns a Graph (source="pid").
    dashed_as_piping: treat dashed (signal) runs as piping, for sheets that say so in their notes."""
    warnings = []
    warn = warnings.append
    sheet = sheet or (out.get("drawing") or {}).get("number") or "sheet"
    items = _items(out)
    runs = [r for r in out.get("runs", []) if r.get("id")]
    _fold_sample_points(items, runs, warn)
    run_by_id = {r["id"]: r for r in runs}
    phys = _physical_runs(runs, warn, dashed_as_piping)
    labels = [l for l in out.get("lines", []) if l.get("bbox") and l.get("line_number")]
    nodes, edges = {}, []

    for it in items.values():
        size = None
        if it["category"] == "fitting" and SIZE_RE.match(it.get("text") or ""):
            size = SIZE_RE.match(it["text"]).group(1) + '"'
        nodes[it["id"]] = Node(id=it["id"], category=it["category"], dexpi_class=dexpi_class(it["category"], it["type"]),
                               type=it["type"], tag=it["tag"], text=it["text"], nominal_size=size, sheet=sheet,
                               bbox=[round(v, 1) for v in it["bbox"]])

    # 1. tee requests: a physical run whose end is another run id joins that run at its end point
    requests = {}  # target run -> [(along, point, source run, end index)]
    for r in runs:
        if r["id"] not in phys:
            continue
        seq, path = r.get("items") or [], _path(r)
        for k in {0, len(seq) - 1} if seq else ():
            ref = seq[k]
            if ref == "END" and path:
                # a bare end lying on another pipe is a join the trace did not name
                pt = path[0] if k == 0 else path[-1]
                # (a run that itself starts or ends on this one continues it, so it is not a candidate)
                near = min(((_dist(_path(o), pt), o["id"]) for o in runs
                            if o["id"] in phys and o["id"] != r["id"] and _path(o)
                            and r["id"] not in (o.get("items") or [])[:1] + (o.get("items") or [])[-1:]),
                           default=None)
                if near and near[0] <= END_SNAP:
                    ref = near[1]
                    warn(f"{r['id']}: bare end at ({pt[0]:.0f}, {pt[1]:.0f}) lies on {ref} - joined to it")
            if ref in run_by_id and ref != r["id"]:
                pt = (path[0] if k == 0 else path[-1]) if path else None
                tp = _path(run_by_id[ref])
                along = _along(tp, pt) if tp and pt else None
                requests.setdefault(ref, []).append((along, pt, r["id"], k))
        for ref in seq[1:-1]:
            if ref in run_by_id:
                warn(f"{r['id']}: run id {ref} inside the run is ignored (only run ends can tee)")
    tee_of, tees_on, n_tee = {}, {}, 0  # (run, end index) -> tee id ; run -> [(along, tee id, point)]
    for target, reqs in requests.items():
        reqs.sort(key=lambda q: (q[0] is None, q[0] or 0))
        clusters = []
        for q in reqs:
            if q[0] is not None and clusters and clusters[-1][0] is not None and q[0] - clusters[-1][0] <= TEE_MERGE:
                clusters[-1][2].append(q)
            else:
                clusters.append([q[0], q[1], [q]])
        for along, pt, qs in clusters:
            n_tee += 1
            tid = f"T{n_tee}"
            line = run_by_id[target].get("line_number")
            nodes[tid] = Node(id=tid, category="tee", dexpi_class="PipeTee", sheet=sheet, line_number=line,
                              bbox=[pt[0] - 1, pt[1] - 1, pt[0] + 1, pt[1] + 1] if pt else None)
            tees_on.setdefault(target, []).append((along, tid, pt))
            for q in qs:
                tee_of[(q[2], q[3])] = tid
            if along is None:
                warn(f"{tid}: position of the join on {target} is unknown (no path) - placed at the nearest item")

    # 2. each physical run -> ordered node chain -> pipe segments between consecutive nodes
    n_pipe, n_end = 0, 0
    for r in runs:
        if r["id"] not in phys:
            continue
        seq, path = list(r.get("items") or []), _path(r)
        chain = []
        for k, ref in enumerate(seq):
            if (k == 0 or k == len(seq) - 1) and (r["id"], k) in tee_of:
                chain.append(tee_of[(r["id"], k)])
            elif ref == "END" or ref == r["id"]:
                n_end += 1
                eid = f"E{n_end}"
                pt = (path[0] if k == 0 else path[-1]) if path and k in (0, len(seq) - 1) else None
                nodes[eid] = Node(id=eid, category="end", sheet=sheet,
                                  bbox=[pt[0] - 1, pt[1] - 1, pt[0] + 1, pt[1] + 1] if pt else None)
                chain.append(eid)
            elif ref in items:
                chain.append(ref)
            elif ref not in run_by_id:
                warn(f"{r['id']}: unknown id {ref} skipped")
        # insert the tees other runs make on this one, by position along its path
        along_of = {}
        for along, tid, pt in sorted(tees_on.get(r["id"], []), key=lambda t: (t[0] is None, t[0] or 0)):
            pos = [along_of.get(c, _along(path, centre(items[c]["bbox"])) if path and c in items else None)
                   for c in chain]
            if along is not None and path:
                # after the last chain node at or before the tee; ends stay at the ends
                idx = max([i for i, a in enumerate(pos) if a is not None and a <= along] + [0]) + 1
            elif pt and any(c in items for c in chain):
                idx = min((i for i, c in enumerate(chain) if c in items),
                          key=lambda i: math.dist(centre(items[chain[i]]["bbox"]), pt)) + 1
            else:
                idx = len(chain)
            # a join at a bare end of this run is a bend into the other run, not a tee: take the end's place
            length = sum(math.dist(p, q) for p, q in zip(path, path[1:])) if path else None
            at_end = None
            if along is not None and length is not None:
                at_end = 0 if along <= TEE_MERGE else -1 if length - along <= TEE_MERGE else None
            if at_end is not None and chain and nodes[chain[at_end]].category == "end":
                del nodes[chain[at_end]]
                chain[at_end] = tid
                along_of[tid] = along
                continue
            idx = max(1, min(idx, len(chain) - 1)) if len(chain) >= 2 else len(chain)
            chain.insert(idx, tid)
            along_of[tid] = along
        chain = [c for i, c in enumerate(chain) if i == 0 or c != chain[i - 1]]
        size, service = parse_line_number(r.get("line_number"))
        labs = _labels_along(path, labels)
        extra = {"line_labels": labs} if len(labs) > 1 else {}
        for a, b in zip(chain, chain[1:]):
            n_pipe += 1
            pid = f"P{n_pipe}"
            nodes[pid] = Node(id=pid, category="pipe", dexpi_class="PipingNetworkSegment", sheet=sheet,
                              line_number=r.get("line_number"), nominal_size=size, service=service,
                              attrs={"run": r["id"], **extra})
            edges += [Edge(src=a, dst=pid, run=r["id"]), Edge(src=pid, dst=b, run=r["id"])]
        if len(chain) == 1:
            warn(f"{r['id']}: run reduces to a single node {chain[0]} - no piping created")

    # 3. signal and impulse runs -> direct edges between the items they join
    by_item = {i: {"bbox": it["bbox"]} for i, it in items.items()}
    for c in derive_connections(runs, by_item):
        if c["run"] not in phys:
            edges.append(Edge(src=c["from"], dst=c["to"],
                              kind="impulse" if c["kind"] == "impulse" else "signal", run=c["run"]))

    g = Graph(source="pid", sheets=[{"id": sheet, **(out.get("drawing") or {}),
                                     "image": (out.get("_image") or {}).get("path")}],
              nodes=list(nodes.values()), edges=edges, warnings=warnings)
    return simplify(g)


def simplify(g):
    """Merge tees that are one junction drawn as two (joins on different runs at the same point,
    linked by a single pipe), drop tees that ended up with only two pipe connections (a bend, not
    a branch) and merge pipe segments that touch each other directly into one."""
    by_id = g.by_id()
    adj = g.adjacency(("process",))
    tees = [n for n in g.nodes if n.category == "tee" and n.bbox]
    for i, a in enumerate(tees):
        for b in tees[i + 1:]:
            if a.id not in by_id or b.id not in by_id or math.dist(centre(a.bbox), centre(b.bbox)) > TEE_MERGE:
                continue
            link = [p for p in adj[a.id] & adj[b.id] if by_id[p].category == "pipe" and adj[p] == {a.id, b.id}]
            if not link:
                continue
            for p in link:
                adj.pop(p)
                adj[a.id].discard(p); adj[b.id].discard(p)
                del by_id[p]
            for x in adj.pop(b.id):
                adj[x].discard(b.id); adj[x].add(a.id); adj[a.id].add(x)
            del by_id[b.id]
            g.warnings.append(f"{b.id}: same junction as {a.id} - merged")
    for n in [n for n in g.nodes if n.id in by_id and n.category == "tee" and len(adj[n.id]) == 2]:
        a, b = adj.pop(n.id)
        adj[a].discard(n.id); adj[b].discard(n.id)
        adj[a].add(b); adj[b].add(a)
        del by_id[n.id]
    for n in list(by_id.values()):
        if n.id not in by_id or n.category != "pipe":
            continue
        while m := next((m for m in adj[n.id] if m in by_id and m != n.id and by_id[m].category == "pipe"), None):
            other = by_id.pop(m)
            if other.line_number and n.line_number and norm(other.line_number) != norm(n.line_number):
                g.warnings.append(f"{n.id}/{m}: adjacent pipes with different line numbers "
                                  f"{n.line_number} / {other.line_number} merged")
            n.line_number = n.line_number or other.line_number
            n.nominal_size = n.nominal_size or other.nominal_size
            n.service = n.service or other.service
            for x in adj.pop(m) - {n.id}:
                adj[x].discard(m); adj[x].add(n.id); adj[n.id].add(x)
            adj[n.id].discard(m)
    keep = set(by_id)
    other_edges = [e for e in g.edges if e.kind != "process" and e.src in keep and e.dst in keep]
    run_of = {n.id: n.attrs.get("run") for n in by_id.values()}
    proc = {tuple(sorted((a, b))) for a, nb in adj.items() if a in keep for b in nb if b in keep}
    g.nodes = list(by_id.values())
    g.edges = [Edge(src=a, dst=b, run=run_of.get(a) or run_of.get(b)) for a, b in sorted(proc)] + other_edges
    return g
