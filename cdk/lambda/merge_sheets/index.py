"""MergeSheets: last state of the workflow. Stitches the sheet graphs into one plant graph and writes
the execution summary.

Event: {"bucket", "prefix", "source", "config", "results": [one entry per page: the agent's summary
        ({"status": "SUCCEEDED", "sheetId", "outputPrefix", "usage", "usd", ...}) or
        {"status": "FAILED", "sheetId", "error", "cause"}]}
Writes <prefix>plant.graph.json, plant.issues.json, plant.dexpi.xml, plant.dot and summary.json.
"""
import json
import logging
import os

import boto3

from pidtwin.graph.dexpi import to_proteus
from pidtwin.graph.dot import to_dot
from pidtwin.graph.merge import merge
from pidtwin.graph.schema import Graph
from pidtwin.graph.validate import summary as issue_summary, validate

log = logging.getLogger()
log.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

s3 = boto3.client("s3")
USAGE_KEYS = ("inputTokens", "outputTokens", "cacheWriteInputTokens", "cacheReadInputTokens")


def put(bucket, key, body, content_type):
    s3.put_object(Bucket=bucket, Key=key, Body=body, ContentType=content_type)
    return f"s3://{bucket}/{key}"


def lambda_handler(event, context):
    bucket, prefix = event["bucket"], event["prefix"]
    results = event["results"]
    ok = [r for r in results if r.get("status") == "SUCCEEDED"]
    usage = {k: sum((r.get("usage") or {}).get(k, 0) for r in ok) for k in USAGE_KEYS}
    usd = sum(r["usd"] for r in ok if r.get("usd") is not None) if ok else 0.0
    out = {"status": "SUCCEEDED" if len(ok) == len(results) else "PARTIAL" if ok else "FAILED",
           "source": event.get("source"), "modelId": (event.get("config") or {}).get("modelId"),
           "sheets": {"total": len(results), "succeeded": len(ok)}, "usage": usage, "usd": round(usd, 4),
           "pages": results, "outputs": {}}
    if ok:
        graphs = [Graph.model_validate_json(s3.get_object(Bucket=bucket, Key=f"{r['outputPrefix']}graph.json")["Body"].read())
                  for r in ok]
        plant = merge(graphs)
        issues = validate(plant)
        out["plant"] = {"nodes": len(plant.nodes), "edges": len(plant.edges), "issues": issue_summary(issues),
                        "warnings": plant.warnings[-20:]}
        out["outputs"] = {
            "graph": put(bucket, f"{prefix}plant.graph.json", plant.model_dump_json(indent=2, exclude_none=True),
                         "application/json"),
            "issues": put(bucket, f"{prefix}plant.issues.json", json.dumps([i.model_dump() for i in issues], indent=2),
                          "application/json"),
            "dexpi": put(bucket, f"{prefix}plant.dexpi.xml", to_proteus(plant), "application/xml"),
            "dot": put(bucket, f"{prefix}plant.dot", to_dot(plant), "text/vnd.graphviz"),
        }
    out["outputs"]["summary"] = put(bucket, f"{prefix}summary.json", json.dumps(out, indent=2, default=str),
                                    "application/json")
    log.info("%s: %d/%d sheets, $%.2f", prefix, len(ok), len(results), usd)
    return {k: out[k] for k in ("status", "sheets", "usd", "outputs")}
