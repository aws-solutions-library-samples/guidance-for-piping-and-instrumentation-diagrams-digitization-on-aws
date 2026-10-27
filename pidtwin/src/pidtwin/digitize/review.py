"""Self-review stage: a Strands agent inspects its draft digitization against the original sheet.

The agent gets tools to zoom into any region of the original at native resolution (optionally with
its current items and runs drawn on top) and to add / update / delete items and runs. It sweeps the
sheet, fixes what it finds, and calls finish(). Items and runs are edited in place.
"""
import time

from strands import Agent, tool
from strands.hooks import BeforeModelCallEvent
from strands.models.bedrock import BedrockModel

from .pipeline import (BBOX_DOC, BOTO_CONFIG, CATEGORY_DOC, PREFIX, REGION, RUN_RULES, USAGE_KEYS, draw_state,
                      fit, image_block, inventory, valid_box)

MAX_VIEWS = 40   # default zoom budget per sheet
# Bedrock rejects images inside toolResult for these providers, though it accepts them as a plain
# content block in the same user message; keyed by the provider segment of the model id
TOOL_RESULT_IMAGES = {"openai": False}


def _hoist_tool_images(event):
    """Move images out of toolResult blocks into sibling content blocks of the same user message."""
    for msg in event.agent.messages:
        if msg["role"] != "user":
            continue
        hoisted = []
        for block in msg["content"]:
            tr = block.get("toolResult")
            if tr and any("image" in c for c in tr["content"]):
                hoisted += [c for c in tr["content"] if "image" in c]
                tr["content"] = [c for c in tr["content"] if "image" not in c] or [{"text": "(image below)"}]
        msg["content"].extend(hoisted)
VIEW_SIDE = 1600  # long edge of each returned crop (native resolution or better for typical regions)

SYSTEM = """You are reviewing a draft digitization of a Piping & Instrumentation Diagram (P&ID).
The draft consists of items (symbols and labels, each with an id, category, type, tag/text and bbox)
and runs (traced pipe / signal lines). All coordinates are sheet-normalized 0-1000 on both axes,
(0,0) top-left.

Your job: make the draft match the drawing exactly.
1. Sweep the whole sheet with view_region in overlapping windows (about 6-12 windows; smaller ones
   where the drawing is dense), with overlay on, comparing the drawn boxes and orange run paths
   against the drawing underneath. Use overlay=false when the overlay hides detail.
2. Fix every discrepancy with the edit tools: missing or misread symbols and tags (zoom in to read
   small text), wrong boxes, missing fittings / end caps / drains / STA boxes, line-number labels,
   runs that are missing, stop short, jump across the sheet without a drawn line, or list the wrong
   items, and runs whose line_number is missing.
3. Make sure every drawn line on the sheet is covered by a run and both ends of each run are set.
4. Call finish with a short summary when done. Do not stop early; do not stop to ask questions.

""" + CATEGORY_DOC + """

Run rules:
""" + RUN_RULES


def review_with_agent(model_id, sheet, items, runs, sink, issues=(), max_views=MAX_VIEWS):
    W, H = sheet.size
    log = {"views": 0, "added": 0, "updated": 0, "deleted": 0, "runs_added": 0, "runs_updated": 0,
           "runs_deleted": 0, "finished": False, "summary": None}
    by_id = lambda i: next((it for it in items if it["id"] == i), None)
    run_by_id = lambda i: next((r for r in runs if r.get("id") == i), None)

    def new_id(prefix, pool):
        k = 1
        while f"{prefix}{k}" in pool:
            k += 1
        return f"{prefix}{k}"

    @tool
    def view_region(x_min: float, y_min: float, x_max: float, y_max: float, overlay: bool = True) -> dict:
        """Zoom into a region of the original sheet (sheet coords 0-1000) and return it as an image.

        Args:
            x_min: left edge of the region
            y_min: top edge of the region
            x_max: right edge of the region
            y_max: bottom edge of the region
            overlay: draw current item boxes/ids (red/blue) and run paths (orange) on top
        """
        if log["views"] >= max_views:
            return {"status": "error", "content": [{"text": "View budget used up - make final edits and call finish."}]}
        b = valid_box([x_min, y_min, x_max, y_max])
        if not b:
            return {"status": "error", "content": [{"text": "Invalid region."}]}
        b = [max(0, b[0]), max(0, b[1]), min(1000, b[2]), min(1000, b[3])]
        log["views"] += 1
        crop = fit(sheet.crop((int(b[0] / 1000 * W), int(b[1] / 1000 * H),
                               int(b[2] / 1000 * W), int(b[3] / 1000 * H))), VIEW_SIDE)
        if overlay:
            crop = draw_state(crop, items, runs, region=b)
        inside = [it for it in items if it["bbox"][2] >= b[0] and it["bbox"][0] <= b[2]
                  and it["bbox"][3] >= b[1] and it["bbox"][1] <= b[3]]
        rs = [r for r in runs if any(b[0] <= p[0] <= b[2] and b[1] <= p[1] <= b[3]
                                     for p in r.get("path") or [] if len(p) == 2)]
        text = (f"Region [{', '.join(str(round(v)) for v in b)}] ({log['views']}/{max_views} views used).\n"
                f"Items here:\n{inventory(inside) or '(none)'}\nRuns here:\n" +
                ("\n".join(f'{r.get("id")} | {r.get("kind")} | {r.get("line_number")} | items={r.get("items")}'
                           for r in rs) or "(none)"))
        return {"status": "success", "content": [image_block(crop), {"text": text}]}

    @tool
    def add_item(category: str, type: str, bbox: list[float], tag: str | None = None, text: str | None = None) -> str:
        """Add a missing item. Returns its new id.

        Args:
            category: equipment | valve | instrument | fitting | offpage | line_label
            type: kind of symbol, e.g. "gate valve", "blind flange", "drain"
            bbox: [x_min, y_min, x_max, y_max] in sheet coords 0-1000
            tag: printed tag, if any
            text: other printed text (line number for line_label, size label for fittings)
        """
        b = valid_box(bbox)
        if category not in PREFIX or not b:
            return "Error: bad category or bbox."
        ids = {it["id"] for it in items}
        iid = tag if tag and tag not in ids and category != "line_label" else new_id(PREFIX[category], ids)
        items.append({"id": iid, "category": category, "type": type, "tag": tag, "text": text, "bbox": b})
        log["added"] += 1
        return f"Added {iid}."

    @tool
    def update_item(id: str, category: str | None = None, type: str | None = None, tag: str | None = None,
                    text: str | None = None, bbox: list[float] | None = None) -> str:
        """Correct fields of an existing item (only the fields you pass change).

        Args:
            id: item id
            category: new category
            type: new type
            tag: corrected tag
            text: corrected text
            bbox: corrected [x_min, y_min, x_max, y_max]
        """
        it = by_id(id)
        if not it:
            return f"Error: no item {id}."
        if bbox is not None:
            if not valid_box(bbox):
                return "Error: bad bbox."
            it["bbox"] = valid_box(bbox)
        for k, v in (("category", category), ("type", type), ("tag", tag), ("text", text)):
            if v is not None:
                it[k] = v
        log["updated"] += 1
        return f"Updated {id}."

    @tool
    def delete_item(id: str) -> str:
        """Delete an item that is not really on the drawing (or is a duplicate).

        Args:
            id: item id
        """
        it = by_id(id)
        if not it:
            return f"Error: no item {id}."
        items.remove(it)
        for r in runs:
            r["items"] = [i for i in r.get("items") or [] if i != id]
        log["deleted"] += 1
        return f"Deleted {id}."

    @tool
    def upsert_run(kind: str, items_along: list[str], path: list[list[float]], line_number: str | None = None,
                   id: str | None = None) -> str:
        """Create a run, or replace an existing run when id is given.

        Args:
            kind: process | signal | impulse
            items_along: ids in order along the run (ends may be run ids or "END")
            path: polyline [[x, y], ...] in sheet coords 0-1000 following the drawn line
            line_number: line-number text printed along the run, if any
            id: existing run id to replace
        """
        known = {it["id"] for it in items} | {r.get("id") for r in runs} | {"END"}
        unknown = [i for i in items_along if i not in known]
        if unknown:
            return f"Error: unknown ids {unknown} - add the items first."
        run = {"kind": kind, "line_number": line_number, "items": items_along,
               "path": [p for p in path if isinstance(p, list) and len(p) == 2]}
        if id and run_by_id(id):
            run_by_id(id).update(run)
            log["runs_updated"] += 1
            return f"Replaced {id}."
        run["id"] = new_id("R", {r.get("id") for r in runs})
        runs.append(run)
        log["runs_added"] += 1
        return f"Added {run['id']}."

    @tool
    def delete_run(id: str) -> str:
        """Delete a run that does not follow a drawn line.

        Args:
            id: run id
        """
        r = run_by_id(id)
        if not r:
            return f"Error: no run {id}."
        runs.remove(r)
        log["runs_deleted"] += 1
        return f"Deleted {id}."

    @tool
    def finish(summary: str) -> str:
        """Call once the draft matches the drawing.

        Args:
            summary: what was checked and changed
        """
        log["finished"], log["summary"] = True, summary
        return "Done."

    model = BedrockModel(model_id=model_id, region_name=REGION, boto_client_config=BOTO_CONFIG, max_tokens=32000)
    agent = Agent(model=model, system_prompt=SYSTEM, callback_handler=None,
                  tools=[view_region, add_item, update_item, delete_item, upsert_run, delete_run, finish])
    if not TOOL_RESULT_IMAGES.get(model_id.split(".")[1], True):
        agent.hooks.add_callback(BeforeModelCallEvent, _hoist_tool_images)
    runs_txt = "\n".join(f'{r.get("id")} | {r.get("kind")} | {r.get("line_number")} | items={r.get("items")}'
                         for r in runs)
    hints = ("Automatic graph checks flagged these (pipe/tee ids P*/T*/E* are derived from runs; fix the "
             "items or runs behind them, or leave them if the drawing really shows it):\n" +
             "\n".join(f"- {i.node or ''}: {i.message}" for i in issues) + "\n\n") if issues else ""
    t = time.time()
    result = agent([
        image_block(draw_state(fit(sheet), items, runs)),
        {"text": f"The image is the full sheet with the draft overlaid.\nItems (id | category | type | "
                 f"tag/text | bbox; {BBOX_DOC.split(' in ')[0]} in sheet coords):\n{inventory(items)}\n\n"
                 f"Runs (id | kind | line_number | items):\n{runs_txt or '(none)'}\n\n{hints}Review and fix the draft."},
    ])
    secs = time.time() - t
    u = result.metrics.accumulated_usage
    sink.save("review.json", {"log": log, "final_message": str(result)})
    return items, runs, log, {k: u.get(k, 0) for k in USAGE_KEYS}, secs
