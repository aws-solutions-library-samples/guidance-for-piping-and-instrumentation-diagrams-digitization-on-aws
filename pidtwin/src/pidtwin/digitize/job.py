"""One sheet end to end: digitize, build the sheet graph, validate, export. Used by the AgentCore
Runtime entrypoint (cdk/agent/main.py) with an S3Sink, and usable locally with a LocalSink.

Artifacts written to the sink:
  detect.json, trace.json, trace.raw.txt, draft.json, review.json   intermediate stages
  sheet.json      digitizer result (items, runs, connections, usage)
  graph.json      sheet graph (pidtwin.graph.schema)
  issues.json     rule violations still present after review
  dexpi.xml       DEXPI-style Proteus XML (not schema-validated)
  graph.dot       Graphviz topology view
  overlay.png     the result drawn over the sheet, for checking by eye
"""
from ..graph.build import build_graph
from ..graph.dexpi import to_proteus
from ..graph.dot import to_dot
from ..graph.validate import summary, validate
from .pipeline import cost, draw_state, fit, run_pipeline

OVERLAY_SIDE = 4096  # long edge of overlay.png


def digitize_sheet(sheet, sink, model_id, sheet_id, image_ref=None, review=True, max_views=None,
                   dashed_as_piping=False, resume=True):
    """sheet: PIL image. Returns a small summary (counts, issues, usage, cost) for the orchestrator."""
    out, usage, secs = run_pipeline(model_id, image_ref or sheet_id, sheet, sink, review=review,
                                    max_views=max_views, dashed_as_piping=dashed_as_piping, resume=resume)
    usd = cost(model_id, usage)
    out["_usage"] = {**usage, "seconds": round(secs), "usd": usd, "model_id": model_id}
    sink.save("sheet.json", out)

    g = build_graph(out, sheet=sheet_id, dashed_as_piping=dashed_as_piping)
    issues = validate(g)
    sink.save("graph.json", g.model_dump_json(indent=2, exclude_none=True))
    sink.save("issues.json", [i.model_dump() for i in issues])
    sink.save("dexpi.xml", to_proteus(g))
    sink.save("graph.dot", to_dot(g))
    boxes = [{"id": it.get("id") or it.get("label"), "bbox": it["bbox"]}
             for cat in ("equipment", "valves", "instruments", "fittings", "offpage") for it in out.get(cat, [])
             if it.get("bbox")]
    sink.save("overlay.png", draw_state(fit(sheet, OVERLAY_SIDE), boxes, out.get("runs", [])))

    counts = {k: len(out.get(k, [])) for k in ("equipment", "valves", "instruments", "fittings", "offpage",
                                                 "lines", "runs", "connections")}
    return {"sheet_id": sheet_id, "drawing": out.get("drawing") or {}, "counts": counts,
            "graph": {"nodes": len(g.nodes), "edges": len(g.edges)}, "issues": summary(issues),
            "usage": usage, "seconds": round(secs), "usd": usd, "model_id": model_id,
            "review": (out.get("_pipeline") or {}).get("review")}
