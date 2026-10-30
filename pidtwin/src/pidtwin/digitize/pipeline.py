"""Digitize P&ID images with Bedrock models and score against ground truth (if present).

Pipeline, per sheet and model:
  1. detect - the sheet is cut into overlapping tiles near model-native resolution; each tile
              lists every symbol (tagged or not) with a bbox. Tiles are merged and de-duplicated
              and every item gets an id.
  2. trace  - the full sheet, an id-marked copy and the merged inventory are sent together; the
              model traces every pipe/signal run as a polyline through the ids it passes and
              attaches the line number printed along it.
  3. review - a Strands agent (same model) zooms into regions of the original with its current
              result overlaid and fixes items and runs until it is satisfied (see review.py).
Connections are derived from the runs. The pre-review result is kept as draft.json; graph rule
violations found in the draft (pidtwin.graph.validate) are handed to the review agent as hints.
Artifacts go to a sink (artifacts.py): local files here, S3 when running in AgentCore Runtime.

Usage: python -m pidtwin.digitize.pipeline [--no-review] [--resume] [--models sonnet,opus|all] [image|pdf ...]
       (default: GPT-6.1 Sol on every image in samples/; results in results/)
Ground truth: samples/<name>.truth.json alongside the image (optional).
"""
import argparse
import concurrent.futures as cf
import io
import json
import math
import os
import re
import time
from pathlib import Path

from botocore.config import Config
from PIL import Image, ImageDraw, ImageFont

from ..common import _along, centre, derive_connections, norm  # noqa: F401 (re-exported)
from ..solution import get_client, solution_config
from .artifacts import LocalSink

REGION = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"
MODELS = {
    "GPT-6 Astra": "us.openai.gpt-6-astra",
    "GPT-6.1 Sol": "us.openai.gpt-6.1-sol",
    "GPT-6.1 Terra": "us.openai.gpt-6.1-terra",
    "Claude Opus 5.5": "global.anthropic.claude-opus-5-5",  # US profile kept returning ServiceUnavailable
    "Claude Sonnet 5.5": "us.anthropic.claude-sonnet-5-5",
}
# USD per 1M tokens: (input, output, cache write, cache read), on-demand standard tier, 2026-10-08.
# Source: AWS Pricing API (AmazonBedrockFoundationModels / AmazonBedrock, us-east-1) except GPT-6.1 Sol
# and GPT-6.1 Terra, which are from their Bedrock model cards (US CRIS, <=272K-token requests; Terra
# checked 2026-10-27). Several providers cache images implicitly on Converse, so most image tokens
# arrive as cacheWrite/cacheRead rather than inputTokens.
PRICES = {
    "us.openai.gpt-6-astra": (11.00, 55.00, 13.75, 1.10),
    "us.openai.gpt-6.1-sol": (2.20, 11.00, 2.75, 0.11),
    "us.openai.gpt-6.1-terra": (1.10, 5.50, 1.375, 0.055),
    "global.anthropic.claude-opus-5-5": (4.00, 20.00, 5.00, 0.20),
    "us.anthropic.claude-sonnet-5-5": (2.20, 11.00, 2.75, 0.11),
}
DEFAULT_MODEL = "sol"  # best value on the 10-sheet benchmark (README)
USAGE_KEYS = ("inputTokens", "outputTokens", "cacheWriteInputTokens", "cacheReadInputTokens")


def cost(model_id, usage):
    p = PRICES.get(model_id)
    return None if not p else sum(usage.get(k, 0) * rate for k, rate in zip(USAGE_KEYS, p)) / 1e6
TILE = 2576       # Claude 5.x long-edge limit; anything larger is downscaled by the model
OVERLAP = 0.12    # fraction of a tile step shared with each neighbour
MAX_BYTES = 3_500_000  # stay under Bedrock's per-image size limit

# carries the solution user-agent token, so the review agent's Strands BedrockModel (review.py) is attributed too
BOTO_CONFIG = solution_config(Config(read_timeout=900, retries={"max_attempts": 6, "mode": "adaptive"}))
brt = get_client("bedrock-runtime", BOTO_CONFIG, region_name=REGION)

BBOX_DOC = """BBOX = [x_min, y_min, x_max, y_max] in normalized coordinates 0-1000 on both axes, where
(0,0) is the top-left corner of the image and (1000,1000) the bottom-right."""

CATEGORY_DOC = """Categories:
- equipment: vessels, tanks, pumps, exchangers, heaters, and any boxed or labelled unit symbol
  (e.g. a square marked "STA"); tag = the printed label.
- valve: any valve body (gate, globe, ball, butterfly, check, control, relief, solenoid, ...);
  type = the valve kind; tag = printed tag or null.
- instrument: ISA bubbles, discs, shared-display squares; tag = letters + "-" + loop number on one
  line (e.g. "FT-101"); put any extra text inside the symbol in "text".
- fitting: inline or terminal piping items - end cap / blind flange (short double bar at a line
  end), spectacle blind, orifice or flange pair (double bar across a line, often with a size label),
  reducer, strainer, insulation or tracing segment, drain / vent / ground-style termination
  (stacked short bars). type = the kind; "text" = any size or note label beside it
  (e.g. "16\\"").
  A flange pair with a short stem ending in a sample-point symbol (dot and/or circle) is ONE
  fitting: type "sample connection", one box around flange, stem and symbol, "text" = its size
  label. Do not list the sample-point symbol separately, and do not call it an orifice.
- offpage: off-page connectors, and any text at the end of a line naming where it comes from or
  goes to (e.g. "TO UNIT 200", "STEAM", "CONDENSATE"); "text" = that text.
- line_label: a printed line number such as 6"-DW-1865; "text" = the exact string.
Flow-direction arrowheads on lines are not items."""

DETECT_PROMPT = """You are digitizing a Piping & Instrumentation Diagram (P&ID). This image is __WHERE__.
List EVERY drawn symbol and every text label attached to piping - tagged or not, however small
or repeated - and return ONLY a JSON object, no prose:
{"items": [{"category": "equipment"|"valve"|"instrument"|"fitting"|"offpage"|"line_label",
            "type": str, "tag": str|null, "text": str|null, "bbox": BBOX, "partial": bool}]}
""" + BBOX_DOC + """ Coordinates are relative to THIS image.
""" + CATEGORY_DOC + """
Box tightly around the graphic (for labels, around the text). Set "partial": true when the
symbol is cut by the image edge. Ignore the title block, notes and revision table."""

RUN_RULES = """- A run is one continuous drawn line between two ends. "items" starts with what sits at one end,
  lists every item the line passes through in order (valves, fittings, instrument taps,
  equipment), and ends with what sits at the other end.
- An end is an item id; another run's id (e.g. "R3") when the line tees into that run; or "END"
  for a bare line end with no symbol.
- "path" is the polyline of the drawn line in sheet coordinates (0-1000), including every bend.
- "line_number" is the line-number text printed along that run (see the line_label items), else null.
  Do not put line_label ids in "items".
- Dashed lines are "signal"; thin lines joining an instrument to a process line are "impulse"."""

TRACE_PROMPT = """You are digitizing a Piping & Instrumentation Diagram (P&ID). Image 1 is the full sheet.
Image 2 is the same sheet with every detected item boxed and labelled with its id.
Detected items, one per line: id | category | type | tag or text | bbox
(""" + BBOX_DOC.replace("the image", "the sheet") + """)
__INVENTORY__

Trace EVERY pipe and every instrument signal or impulse line on the sheet and return ONLY a JSON
object, no prose:
{"drawing": {"number": str|null, "revision": str|null, "title": str|null},
 "runs": [{"id": "R1", "kind": "process"|"signal"|"impulse", "line_number": str|null,
           "items": [ids in order along the run], "path": [[x, y], ...]}],
 "added": [{"id": str, "category": str, "type": str, "tag": str|null, "text": str|null, "bbox": BBOX}]}
Rules:
""" + RUN_RULES + """
- If you see a symbol missing from the list, add it under "added" (new id such as "X1") and use it.
Use only ids from the list, from "added", run ids, or "END"."""


# ---------- model calls ----------
def image_block(im):
    buf = io.BytesIO()
    im.save(buf, "PNG")
    if buf.tell() <= MAX_BYTES:
        return {"image": {"format": "png", "source": {"bytes": buf.getvalue()}}}
    buf = io.BytesIO()
    im.convert("RGB").save(buf, "JPEG", quality=92)
    return {"image": {"format": "jpeg", "source": {"bytes": buf.getvalue()}}}


def fit(im, side=TILE):
    if max(im.size) <= side:
        return im
    im = im.copy()
    im.thumbnail((side, side), Image.LANCZOS)
    return im


def call(model_id, images, prompt):
    t = time.time()
    r = brt.converse(
        modelId=model_id,
        messages=[{"role": "user", "content": [*(image_block(i) for i in images), {"text": prompt}]}],
        inferenceConfig={"maxTokens": 32000},
    )
    text = "".join(c.get("text", "") for c in r["output"]["message"]["content"])
    return text, r["usage"], time.time() - t


def parse_json(text):
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0)) if m else None


def call_json(model_id, images, prompt, attempts=3):
    """call() + parse_json(), re-asking when the reply is not valid JSON. Usage covers every attempt."""
    usage, secs = dict.fromkeys(USAGE_KEYS, 0), 0.0
    for i in range(attempts):
        text, u, s = call(model_id, images, prompt)
        usage, secs = add_usage(usage, u), secs + s
        try:
            out = parse_json(text)
        except json.JSONDecodeError:
            out = None
        if out is not None or i == attempts - 1:
            return out, text, usage, secs


# ---------- tiling / merging ----------
def tile_boxes(W, H):
    nx, ny = math.ceil(W / TILE), math.ceil(H / TILE)
    sx, sy = W / nx, H / ny
    ox, oy = OVERLAP * sx, OVERLAP * sy
    return [(round(max(0, i * sx - ox)), round(max(0, j * sy - oy)),
             round(min(W, (i + 1) * sx + ox)), round(min(H, (j + 1) * sy + oy)), j, i, ny, nx)
            for j in range(ny) for i in range(nx)]


def to_sheet(b, tile, W, H):
    x0, y0, x1, y1 = tile[:4]
    tw, th = x1 - x0, y1 - y0
    return [(x0 + b[0] / 1000 * tw) / W * 1000, (y0 + b[1] / 1000 * th) / H * 1000,
            (x0 + b[2] / 1000 * tw) / W * 1000, (y0 + b[3] / 1000 * th) / H * 1000]


def valid_box(b):
    try:
        x1, y1, x2, y2 = (float(v) for v in b)
    except (TypeError, ValueError):
        return None
    x1, x2 = sorted((x1, x2)); y1, y2 = sorted((y1, y2))
    return [x1, y1, x2, y2] if x2 > x1 and y2 > y1 else None


def iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0])); iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union else 0


def same_item(a, b):
    """Two detections of the same physical symbol (typically from overlapping tiles)."""
    if a["category"] != b["category"]:
        return False
    ta, tb = norm(a.get("tag") or a.get("text")), norm(b.get("tag") or b.get("text"))
    if ta and tb and ta != tb and not (a.get("partial") or b.get("partial")):
        return False
    size = max(a["bbox"][2] - a["bbox"][0], a["bbox"][3] - a["bbox"][1],
               b["bbox"][2] - b["bbox"][0], b["bbox"][3] - b["bbox"][1])
    return iou(a["bbox"], b["bbox"]) > 0.25 or math.dist(centre(a["bbox"]), centre(b["bbox"])) < 0.6 * size


def merge(items):
    # complete, tagged, larger detections win over partial ones
    items = sorted(items, key=lambda it: (bool(it.get("partial")), not it.get("tag"),
                                          -(it["bbox"][2] - it["bbox"][0]) * (it["bbox"][3] - it["bbox"][1])))
    kept = []
    for it in items:
        if not any(same_item(k, it) for k in kept):
            kept.append(it)
    return kept


PREFIX = {"equipment": "EQ", "valve": "V", "instrument": "I", "fitting": "F", "offpage": "OP", "line_label": "L"}


def assign_ids(items):
    counts = {}
    for it in items:
        if it.get("tag") and it["category"] != "line_label":
            counts[it["tag"]] = counts.get(it["tag"], 0) + 1
    seen, n = {}, {}
    for it in sorted(items, key=lambda it: (it["bbox"][1], it["bbox"][0])):  # reading order
        tag = it.get("tag") if it["category"] != "line_label" else None
        if tag and counts[tag] == 1:
            it["id"] = tag
        elif tag:  # repeated label such as "STA" -> STA#1, STA#2 ...
            seen[tag] = seen.get(tag, 0) + 1
            it["id"] = f"{tag}#{seen[tag]}"
        else:
            p = PREFIX[it["category"]]
            n[p] = n.get(p, 0) + 1
            it["id"] = f"{p}{n[p]}"
    return items


def label(it):
    return it.get("tag") or it.get("text") or ""


FONTS = {False: ["/System/Library/Fonts/Supplemental/Arial.ttf", "/usr/share/fonts/dejavu/DejaVuSans.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"],
         True: ["/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]}


def font(size, bold=False):
    """Arial (macOS) or DejaVu (Linux) when installed, else Pillow's built-in scalable font (Aileron),
    which is what AgentCore Runtime gets. The bitmap default font is too small for the id labels."""
    for path in FONTS[bold]:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default(size)


def draw_state(im, items, runs, region=(0, 0, 1000, 1000)):
    """Draw item boxes + ids and run paths onto im, which shows `region` (sheet coords 0-1000)."""
    im = im.convert("RGB")
    W, H = im.size
    rx0, ry0, rx1, ry1 = region
    px = lambda x, y: ((x - rx0) / (rx1 - rx0) * W, (y - ry0) / (ry1 - ry0) * H)
    d = ImageDraw.Draw(im)
    f = font(max(10, min(W, H) // 70), bold=True)
    for r in runs or []:
        pts = [px(*p) for p in r.get("path") or [] if isinstance(p, (list, tuple)) and len(p) == 2]
        if len(pts) >= 2:
            d.line(pts, fill=(255, 140, 0), width=2)
            d.text(pts[len(pts) // 2], r.get("id", ""), fill=(255, 100, 0), font=f)
    for it in items:
        x1, y1 = px(it["bbox"][0], it["bbox"][1]); x2, y2 = px(it["bbox"][2], it["bbox"][3])
        if x2 < 0 or y2 < 0 or x1 > W or y1 > H:
            continue
        d.rectangle([x1, y1, x2, y2], outline=(230, 0, 0), width=1)
        d.text((x2 + 1, y1), it["id"], fill=(0, 0, 230), font=f)
    return im


# ---------- pipeline ----------
def detect(model_id, sheet, sink):
    W, H = sheet.size
    tiles = tile_boxes(W, H)
    raw, usage, secs = [], dict.fromkeys(USAGE_KEYS, 0), 0.0

    def one(t):
        where = ("the full sheet" if len(tiles) == 1 else
                 f"tile row {t[4] + 1} of {t[6]}, column {t[5] + 1} of {t[7]} of a larger sheet "
                 "(neighbouring tiles overlap slightly)")
        return t, call_json(model_id, [fit(sheet.crop(t[:4]))], DETECT_PROMPT.replace("__WHERE__", where))

    with cf.ThreadPoolExecutor(len(tiles)) as ex:
        for t, (out, _, u, s) in ex.map(one, tiles):
            usage = add_usage(usage, u)
            secs = max(secs, s)
            for it in (out or {}).get("items", []):
                b = valid_box(it.get("bbox"))
                if b and it.get("category") in PREFIX:
                    it["bbox"] = to_sheet(b, t, W, H)
                    raw.append(it)
    items = assign_ids(merge(raw))
    sink.save("detect.json", {"tiles": len(tiles), "raw": len(raw), "items": items, "usage": usage, "seconds": secs})
    return items, usage, secs, len(tiles), len(raw)


def inventory(items):
    return "\n".join(f'{it["id"]} | {it["category"]} | {it.get("type") or ""} | {label(it)} | '
                     f'[{", ".join(str(round(v)) for v in it["bbox"])}]' for it in items)


def trace(model_id, sheet, items, sink):
    traced, text, usage, secs = call_json(model_id, [fit(sheet), draw_state(fit(sheet), items, [])],
                                          TRACE_PROMPT.replace("__INVENTORY__", inventory(items)))
    sink.save("trace.raw.txt", text)
    traced = traced or {}
    for it in traced.pop("added", []):
        b = valid_box(it.get("bbox"))
        if b and it.get("id") and it.get("category") in PREFIX:
            it["bbox"] = b
            items.append(it)
    sink.save("trace.json", {"items": items, "traced": traced, "usage": usage, "seconds": secs})
    return traced, usage, secs


def assemble(items, runs, drawing, image, size):
    by_id = {it["id"]: it for it in items}
    pick = lambda cat: [it for it in items if it["category"] == cat]
    lines = [{"line_number": label(it), "bbox": it["bbox"], "id": it["id"]} for it in pick("line_label") if label(it)]
    known = {norm(l["line_number"]) for l in lines}
    for r in runs:
        if r.get("line_number") and norm(r["line_number"]) not in known:
            known.add(norm(r["line_number"]))
            lines.append({"line_number": r["line_number"], "bbox": None})
    return {
        "drawing": drawing or {},
        "equipment": [{"id": it["id"], "tag": it.get("tag") or it["id"], "type": it.get("type"),
                       "description": it.get("text"), "bbox": it["bbox"]} for it in pick("equipment")],
        "valves": [{"id": it["id"], "tag": it.get("tag"), "type": it.get("type"), "bbox": it["bbox"]}
                   for it in pick("valve")],
        "instruments": [{"id": it["id"], "tag": it.get("tag") or it["id"], "function": it.get("type"),
                         "text": it.get("text"), "bbox": it["bbox"]} for it in pick("instrument")],
        "fittings": [{"id": it["id"], "type": it.get("type"), "text": it.get("text"), "bbox": it["bbox"]}
                     for it in pick("fitting")],
        "offpage": [{"label": it["id"], "text": label(it), "bbox": it["bbox"]} for it in pick("offpage")],
        "lines": lines,
        "runs": runs,
        "connections": derive_connections(runs, by_id),
        "_image": {"path": str(image), "size": list(size)},
    }


def add_usage(a, b):
    return {k: a.get(k, 0) + b.get(k, 0) for k in USAGE_KEYS}


def run_pipeline(model_id, image, sheet, sink, review=True, max_views=None, dashed_as_piping=False, resume=False):
    """Detect, trace and (optionally) review one sheet. With resume, stages whose artifact is already in
    the sink (detect.json, trace.json) are loaded instead of re-run, so a retried sheet picks up where
    it stopped."""
    done = sink.load_json("trace.json") if resume else None
    if done:
        items, traced, usage, secs = done["items"], done["traced"], done["usage"], done["seconds"]
        meta = {"resumed_from": "trace"}
    else:
        done = sink.load_json("detect.json") if resume else None
        if done:
            items, usage, s1, ntiles, nraw = done["items"], done["usage"], done["seconds"], done["tiles"], done["raw"]
        else:
            items, usage, s1, ntiles, nraw = detect(model_id, sheet, sink)
        traced, u2, s2 = trace(model_id, sheet, items, sink)
        usage, secs = add_usage(usage, u2), s1 + s2
        meta = {"tiles": ntiles, "raw_detections": nraw}
    runs, drawing = traced.get("runs", []), traced.get("drawing")
    meta.update(items=len(items), runs=len(runs))
    out = assemble(items, runs, drawing, image, sheet.size)
    out["_pipeline"] = dict(meta)
    if review:
        from .review import MAX_VIEWS, review_with_agent  # strands import is slow; only load when used
        sink.save("draft.json", out)
        issues = graph_issues(out, dashed_as_piping)
        items, runs, log, u3, s3 = review_with_agent(model_id, sheet, items, runs, sink, issues,
                                                     max_views or MAX_VIEWS)
        usage, secs = add_usage(usage, u3), secs + s3
        out = assemble(items, runs, drawing, image, sheet.size)
        out["_pipeline"] = {**meta, "review": log, "graph_issues_before_review": len(issues)}
    return out, usage, secs


def graph_issues(out, dashed_as_piping=False):
    """Build the plant graph from a draft and return its rule violations as review hints."""
    from ..graph.build import build_graph
    from ..graph.validate import validate
    return [i for i in validate(build_graph(out, dashed_as_piping=dashed_as_piping)) if i.level != "info"]


# ---------- scoring ----------
def prf(pred, gold):
    p, g = {norm(x) for x in pred if x}, {norm(x) for x in gold}
    tp = len(p & g)
    prec = tp / len(p) if p else 0.0
    rec = tp / len(g) if g else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return {"P": round(prec, 2), "R": round(rec, 2), "F1": round(f1, 2),
            "missed": sorted(g - p), "extra": sorted(p - g)}


def loc_score(out, truth):
    """Predicted box centre must fall inside the true box padded by 2% of the image's longer side."""
    w, h = truth["image_size"]
    pad = 0.02 * max(w, h)
    gold = {norm(k): v for k, v in truth["boxes"].items()}
    hits, errs, n = [], [], 0
    for cat, key in (("equipment", "tag"), ("valves", "tag"), ("instruments", "tag"), ("lines", "line_number")):
        for it in out.get(cat, []):
            g, b = gold.get(norm(it.get(key))), it.get("bbox")
            if not g or not (isinstance(b, list) and len(b) == 4):
                continue
            n += 1
            cx, cy = (b[0] + b[2]) / 2000 * w, (b[1] + b[3]) / 2000 * h
            ok = g[0] - pad <= cx <= g[2] + pad and g[1] - pad <= cy <= g[3] + pad
            errs.append(((cx - (g[0] + g[2]) / 2) ** 2 + (cy - (g[1] + g[3]) / 2) ** 2) ** .5 / max(w, h) * 100)
            if not ok:
                hits.append(norm(it.get(key)))
    acc = (n - len(hits)) / n if n else 0.0
    return {"P": round(acc, 2), "R": round(n / len(gold), 2), "F1": round(acc, 2), "missed": sorted(hits),
            "extra": [], "mean_center_err_pct": round(sum(errs) / len(errs), 1) if errs else None}


def contract(conns, through):
    """Undirected edges with pass-through nodes (fittings) removed: their neighbours join directly."""
    adj = {}
    for c in conns:
        a, b = c.get("from"), c.get("to")
        if a and b and a != b:
            adj.setdefault(a, set()).add(b); adj.setdefault(b, set()).add(a)
    for n in [n for n in adj if n in through]:
        nbrs = adj.pop(n) - {n}
        for x in nbrs:
            adj[x].discard(n)
            adj[x] |= nbrs - {x}
    return {tuple(sorted((a, b))) for a, nb in adj.items() for b in nb}


def score(out, truth):
    s = {
        "equipment": prf([e.get("tag") for e in out.get("equipment", [])], truth["equipment"]),
        "valves": prf([v.get("tag") for v in out.get("valves", [])], truth["valves"]),
        "instruments": prf([i.get("tag") for i in out.get("instruments", [])], truth["instruments"]),
        "lines": prf([l.get("line_number") for l in out.get("lines", [])], truth["lines"]),
    }
    if truth.get("boxes"):
        s["location"] = loc_score(out, truth)
    # connections may use internal ids; compare on printed tags / off-page text
    alias = {it["id"]: it.get("tag") or it["id"]
             for cat in ("equipment", "valves", "instruments", "fittings") for it in out.get(cat, []) if it.get("id")}
    alias.update({o["label"]: o.get("text") or o["label"] for o in out.get("offpage", [])})
    edge = lambda a, b: "|".join(sorted([norm(alias.get(a, a)), norm(alias.get(b, b))]))  # undirected
    pred = contract(out.get("connections", []), {f["id"] for f in out.get("fittings", [])})
    s["connections"] = prf([edge(a, b) for a, b in pred], [edge(a, b) for a, b in truth["connections"]])
    return s


def report(name, out, usage, secs, truth, usd=None):
    counts = {k: len(out.get(k, [])) for k in ("equipment", "valves", "instruments", "fittings", "lines", "runs", "connections")}
    price = f"${usd:.3f}" if usd is not None else "$?"
    print(f"  {name}: {secs:.0f}s  in={usage['inputTokens']} cache_w={usage.get('cacheWriteInputTokens', 0)} "
          f"cache_r={usage.get('cacheReadInputTokens', 0)} out={usage['outputTokens']}  cost={price}  counts={counts}")
    if "_pipeline" in out:
        print(f"    pipeline: {out['_pipeline']}")
    if not truth:
        return None
    sc = score(out, truth)
    for k, v in sc.items():
        if k == "location":
            print(f"    {'location':12s} acc={v['P']:.2f} boxed={v['R']:.2f} "
                  f"mean_err={v['mean_center_err_pct']}% of width  misplaced={v['missed']}")
            continue
        miss = f"  missed={v['missed']}" if v["missed"] else ""
        miss += f"  extra={v['extra']}" if v["extra"] else ""
        print(f"    {k:12s} P={v['P']:.2f} R={v['R']:.2f} F1={v['F1']:.2f}{miss}")
    return sc


def run(image: Path, models, review, resume=False):
    sheet = Image.open(image)
    sheet.load()
    truth_path = image.with_name(image.stem + ".truth.json")
    truth = json.loads(truth_path.read_text()) if truth_path.exists() else None
    print(f"\n### {image.name}  {sheet.size[0]}x{sheet.size[1]}  review={review}  "
          f"tiles={len(tile_boxes(*sheet.size))}  ({'with' if truth else 'no'} ground truth)", flush=True)
    slug = lambda name: name.replace(" ", "_").replace(".", "")

    summary = []
    with cf.ThreadPoolExecutor(len(models)) as ex:
        sinks = {name: LocalSink(f"results/{image.stem}.{slug(name)}.") for name in models}
        futs = {name: ex.submit(run_pipeline, mid, image, sheet, sinks[name], review, resume=resume) for name, mid in models.items()}
        for name, fut in futs.items():
            try:
                out, usage, secs = fut.result()
            except Exception as e:
                print(f"  {name}: ERROR {type(e).__name__}: {e}")
                continue
            usd = cost(models[name], usage)
            out["_usage"] = {**usage, "seconds": round(secs), "usd": usd}
            summary.append((name, usage, secs, usd))
            Path(f"results/{image.stem}.{slug(name)}.json").write_text(json.dumps(out, indent=2))
            sc = report(name, out, usage, secs, truth, usd)
            if sc:
                Path(f"results/{image.stem}.{slug(name)}.score.json").write_text(json.dumps(sc, indent=2))
    print(f"\n  {'model':18s} {'input':>10s} {'cache wr':>10s} {'cache rd':>10s} {'output':>9s} {'seconds':>8s} {'USD':>8s}")
    for name, u, secs, usd in summary:
        print(f"  {name:18s} {u['inputTokens']:>10,} {u.get('cacheWriteInputTokens', 0):>10,} "
              f"{u.get('cacheReadInputTokens', 0):>10,} {u['outputTokens']:>9,} {secs:>8.0f} "
              f"{'$%.3f' % usd if usd is not None else 'n/a':>8s}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("images", nargs="*")
    ap.add_argument("--no-review", action="store_true", help="skip the Strands review agent")
    ap.add_argument("--models", default=DEFAULT_MODEL,
                    help=f"comma-separated substrings of model names, e.g. sonnet,opus, or all (default: {DEFAULT_MODEL})")
    ap.add_argument("--resume", action="store_true", help="reuse detect/trace results already in results/")
    a = ap.parse_args()
    models = {n: m for n, m in MODELS.items()
              if a.models == "all" or any(s.strip().lower() in n.lower() for s in a.models.split(","))}
    images = [Path(p) for p in a.images] or sorted(
        p for p in Path("samples").iterdir()
        if ".render." not in p.name and ".overlay." not in p.name
        and p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"))
    Path("results").mkdir(exist_ok=True)
    pages = []
    for im in images:
        if im.suffix.lower() == ".pdf":  # one PNG per page, rendered into results/pages/
            from .pdf import render
            pages += render(im, "results/pages")
        else:
            pages.append(im)
    for im in pages:
        run(im, models, not a.no_review, a.resume)
