"""SDMA stage 3, "Merge plant": MergeSheets once every sheet of a run has a result.

The merge connector runs on each <sheetId>.result.json that stage 2 attaches to the drawing. It reads
that result (in SDMA's content store) for the run, and checks the run's pages in <runId>/input.json
against the sheets' own result.json files. Until all are there it returns status PENDING, and the
connector ingests nothing; the run of the last sheet to finish sees them all and merges. Each
trigger fires only after its own sheet's results were written, so the last one cannot miss any.

Event (the connector's field mappings): {"s3Uri": "<file.s3Uri of the result.json>"}
When the merged result needs a review, it also writes <runId>/review/<drawing>.review.json. The merge
connector attaches that file next to the drawing, and its upload starts the review alert: SDMA 1.7.0
raises no asset event for a connector's metadata write, so the alert cannot trigger on the metadata.

Returns plantPrefix and reviewPrefix (always: the connector's siblingDerivedFiles read them, and their
filters match nothing until there is something to attach), status (PENDING, SUCCEEDED, PARTIAL or
FAILED), the run's counts, and the review decision (reviewNeeded, reviewReasons).
"""
import json
import re
from pathlib import PurePosixPath

import index

OUTPUT_BUCKET = index.os.environ["OUTPUT_BUCKET"]
CONTENT_BUCKET = index.os.environ["CONTENT_BUCKET"]


def _json(bucket, key):
    return json.loads(index.s3.get_object(Bucket=bucket, Key=key)["Body"].read())


def lambda_handler(event, context):
    m = re.match(r"^s3://([^/]+)/(.+)$", event.get("s3Uri") or "")
    if not m or m.group(1) != CONTENT_BUCKET:
        raise ValueError(f"s3Uri {event.get('s3Uri')!r} is not in the SDMA content bucket {CONTENT_BUCKET}")
    run_id = _json(m.group(1), m.group(2))["outputPrefix"].split("/", 1)[0]
    manifest = _json(OUTPUT_BUCKET, f"{run_id}/input.json")

    results = []
    for page in manifest["pages"]:
        try:  # a missing result is NoSuchKey (not AccessDenied) because the role can list the bucket
            results.append(_json(OUTPUT_BUCKET, f"{page['outputPrefix']}result.json"))
        except index.s3.exceptions.NoSuchKey:
            pass
    total = len(manifest["pages"])
    base = f"s3://{OUTPUT_BUCKET}/{run_id}/"
    out = {"plantPrefix": base, "reviewPrefix": f"{base}review/", "sheets": total, "sheetsDone": len(results),
           "nodes": 0, "edges": 0, "usd": 0.0, "reviewNeeded": False, "reviewReasons": ""}
    if len(results) < total:
        index.log.info("run %s: %d/%d sheets done, merge later", run_id, len(results), total)
        return {**out, "status": "PENDING"}

    merged = index.lambda_handler({"bucket": OUTPUT_BUCKET, "prefix": f"{run_id}/", "source": manifest["source"],
                                   "config": manifest["config"], "results": results}, context)
    summary = _json(OUTPUT_BUCKET, f"{run_id}/summary.json")
    plant, rev = summary.get("plant") or {}, summary.get("review") or {}
    if rev.get("needed"):
        source = manifest.get("source") or {}
        drawing = index.sheet_id(PurePosixPath(source.get("fileName") or source.get("key") or run_id).stem)
        index.put(OUTPUT_BUCKET, f"{run_id}/review/{drawing}.review.json",
                  json.dumps({"status": merged["status"], "reasons": rev.get("reasons") or [],
                              "summary": f"s3://{OUTPUT_BUCKET}/{run_id}/summary.json"}, indent=2), "application/json")
    return {**out, "status": merged["status"], "nodes": plant.get("nodes", 0), "edges": plant.get("edges", 0),
            "usd": merged["usd"], "reviewNeeded": bool(rev.get("needed")),
            "reviewReasons": "; ".join(rev.get("reasons") or [])}
