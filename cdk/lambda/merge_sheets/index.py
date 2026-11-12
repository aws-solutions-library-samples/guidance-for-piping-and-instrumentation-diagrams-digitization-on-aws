"""MergeSheets: last state of the workflow. Stitches the sheet graphs into one plant graph and writes
the execution summary.

Event: {"bucket", "prefix", "source", "config", "execution" (ARN), "results": [one entry per page: the
        agent's summary ({"status": "SUCCEEDED", "sheet_id", "outputPrefix", "usage", "usd", ...}) or
        {"status": "FAILED", "sheetId", "error", "cause"}]}
summary.json also says whether a person should review the result ("review": {"needed", "reasons"}),
see review().

Writes <prefix>plant.graph.json, plant.issues.json, plant.dexpi.xml, plant.dot, summary.json, and a copy of
each sheet's overlay at overlays/<sheetId>.overlay.png (one flat prefix, for the SDMA connector). When no
sheet succeeded it also writes _FAILED.json, the marker the SDMA connector's wait step fails on.
"""
import json
import logging
import os
import re
from collections import Counter

from botocore.exceptions import ClientError

from pidtwin.graph.dexpi import to_proteus
from pidtwin.graph.dot import to_dot
from pidtwin.graph.merge import merge
from pidtwin.graph.schema import Graph
from pidtwin.graph.validate import summary as issue_summary, validate
from pidtwin.solution import get_client

log = logging.getLogger()
log.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

s3 = get_client("s3")
USAGE_KEYS = ("inputTokens", "outputTokens", "cacheWriteInputTokens", "cacheReadInputTokens")
# rule violations that usually mean a misread or missed item; routine ones (valve_degree, tee_degree,
# tag_pattern, ...) do not ask for a review on their own
REVIEW_CODES = {"dangling_pipe": "dangling pipe", "equipment_unpiped": "unpiped equipment",
                "isolated": "isolated item", "duplicate_tag": "duplicate tag"}


def sheet_id(stem):
    """File-name-safe id, as PrepareInput names sheets."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", stem)[:80] or "sheet"


def put(bucket, key, body, content_type):
    s3.put_object(Bucket=bucket, Key=key, Body=body, ContentType=content_type)
    return f"s3://{bucket}/{key}"


def review(results, plant=None, issues=()):
    """Whether a person should check the result, and why: a sheet failed, the review agent ran out of
    views on a sheet, an error or one of REVIEW_CODES remains, or off-page connectors were not
    stitched across sheets."""
    reasons = []
    failed = [r.get("sheet_id") or r.get("sheetId") for r in results if r.get("status") != "SUCCEEDED"]
    if failed:
        reasons.append(f"{len(failed)} sheet(s) failed: {', '.join(map(str, failed))}")
    unfinished = [r["sheet_id"] for r in results
                  if r.get("status") == "SUCCEEDED" and r.get("review") and not r["review"].get("finished")]
    if unfinished:
        reasons.append(f"review stopped early on {', '.join(unfinished)}")
    counts = Counter(i.code for i in issues if i.level == "error" or i.code in REVIEW_CODES)
    reasons += [f"{n} {REVIEW_CODES.get(code, code.replace('_', ' '))}{'s' if n > 1 else ''}"
                for code, n in sorted(counts.items())]
    if plant is not None and len(plant.sheets) > 1:
        loose = [n for n in plant.nodes if n.category == "offpage" and not n.attrs.get("stitched_to")]
        if loose:
            reasons.append(f"{len(loose)} off-page connector(s) not joined across sheets")
    return {"needed": bool(reasons), "reasons": reasons}


def lambda_handler(event, context):
    bucket, prefix = event["bucket"], event["prefix"]
    results = event["results"]
    ok = [r for r in results if r.get("status") == "SUCCEEDED"]
    usage = {k: sum((r.get("usage") or {}).get(k, 0) for r in ok) for k in USAGE_KEYS}
    usd = sum(r["usd"] for r in ok if r.get("usd") is not None) if ok else 0.0
    out = {"status": "SUCCEEDED" if len(ok) == len(results) else "PARTIAL" if ok else "FAILED",
           "execution": event.get("execution"), "source": event.get("source"),
           "modelId": (event.get("config") or {}).get("modelId"),
           "sheets": {"total": len(results), "succeeded": len(ok)}, "usage": usage, "usd": round(usd, 4),
           "pages": results, "outputs": {}}
    if ok:
        graphs = [Graph.model_validate_json(s3.get_object(Bucket=bucket, Key=f"{r['outputPrefix']}graph.json")["Body"].read())
                  for r in ok]
        plant = merge(graphs)
        issues = validate(plant)
        out["plant"] = {"nodes": len(plant.nodes), "edges": len(plant.edges), "issues": issue_summary(issues),
                        "warnings": plant.warnings[-20:]}
        out["review"] = review(results, plant, issues)
        for r in ok:
            sid = r["sheet_id"]
            try:
                s3.copy_object(Bucket=bucket, Key=f"{prefix}overlays/{sid}.overlay.png",
                               CopySource={"Bucket": bucket, "Key": f"{r['outputPrefix']}overlay.png"})
            except ClientError as e:
                log.warning("no overlay for sheet %s: %s", sid, e)
        out["outputs"] = {
            "graph": put(bucket, f"{prefix}plant.graph.json", plant.model_dump_json(indent=2, exclude_none=True),
                         "application/json"),
            "issues": put(bucket, f"{prefix}plant.issues.json", json.dumps([i.model_dump() for i in issues], indent=2),
                          "application/json"),
            "dexpi": put(bucket, f"{prefix}plant.dexpi.xml", to_proteus(plant), "application/xml"),
            "dot": put(bucket, f"{prefix}plant.dot", to_dot(plant), "text/vnd.graphviz"),
        }
    out.setdefault("review", review(results))
    out["outputs"]["summary"] = put(bucket, f"{prefix}summary.json", json.dumps(out, indent=2, default=str),
                                    "application/json")
    if not ok:
        put(bucket, f"{prefix}_FAILED.json", json.dumps({"message": f"all {len(results)} sheet(s) failed",
                                                         "summary": out["outputs"]["summary"]}), "application/json")
    log.info("%s: %d/%d sheets, $%.2f", prefix, len(ok), len(results), usd)
    return {k: out[k] for k in ("status", "sheets", "usd", "outputs")}
