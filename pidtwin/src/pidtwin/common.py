"""Small helpers shared by the digitizer and the graph code (no AWS imports here)."""
import math
import re


def norm(s):
    return re.sub(r"[\s“”″'\"]", "", str(s or "")).upper()


def centre(b):
    return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)


def _along(path, pt):
    """Distance along a polyline to the point on it closest to pt."""
    best, run_len = (float("inf"), 0.0), 0.0
    for a, b in zip(path, path[1:]):
        seg = math.dist(a, b) or 1e-9
        t = max(0.0, min(1.0, ((pt[0] - a[0]) * (b[0] - a[0]) + (pt[1] - a[1]) * (b[1] - a[1])) / seg ** 2))
        q = (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
        best = min(best, (math.dist(q, pt), run_len + t * seg))
        run_len += seg
    return best[1]


def derive_connections(runs, by_id):
    """Consecutive items along each run. A tee into run Rk joins the item just upstream of the tee
    point on Rk (the convention for instrument taps), or the nearest item if none is upstream."""
    run_by_id = {r.get("id"): r for r in runs}

    def resolve(ref, point):
        target = run_by_id[ref]
        cands = [i for i in target.get("items", []) if i in by_id]
        path = [p for p in target.get("path") or [] if len(p) == 2]
        if not cands or not point:
            return None
        if len(path) >= 2:
            at = _along(path, point)
            upstream = [(_along(path, centre(by_id[i]["bbox"])), i) for i in cands]
            upstream = [u for u in upstream if u[0] <= at]
            if upstream:
                return max(upstream)[1]
        return min(cands, key=lambda i: math.dist(centre(by_id[i]["bbox"]), point))

    conns = []
    for r in runs:
        seq, path = list(r.get("items") or []), r.get("path") or []
        for k, end in ((0, 0), (len(seq) - 1, -1)):
            if seq and seq[k] in run_by_id and seq[k] != r.get("id"):
                seq[k] = resolve(seq[k], path[end] if path else None)
        seq = [i for i in seq if i in by_id]
        for a, b in zip(seq, seq[1:]):
            if a != b:
                conns.append({"from": a, "to": b, "kind": r.get("kind") or "process", "run": r.get("id")})
    return conns
