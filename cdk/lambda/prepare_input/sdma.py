"""SDMA stage 1, "Render pages": PrepareInput for a drawing handed over by the SDMA render connector.

Runs PrepareInput (validation, config merge, PDF rendering, <runId>/input.json) with the connector
invocation as the run id, then copies each page to <runId>/sdma/pages/<sheetId>.page.png. The
connector ingests those as derived files of the drawing, and each one starts stage 2 (one sheet).

Stage 2 takes the sheet from the page's file name, and finds the run through
sdma-pages/<assetId>/<page hash>.json, keyed by the xxh128 of the page bytes, which is the hash SDMA
gives the ingested page (identical pages share an entry, so it holds only the run). Page metadata cannot carry the run id: SDMA
caches an asset's metadata for 10 s per container, and stage 2 starts within that window.

Event (the connector's field mappings):
  {"runId": "<parameters.connectorInvocationId>", "assetId": "<file.assetId>", "s3Uri": "<file.s3Uri>",
   "path": "<file.path>", "modelId": "", "detect": "", "reviewModelId": ""}   (empty = deployment default)
Returns {"runId", "pages", "pagesPrefix"} for the connector's output routing.
"""
import json
import re
from pathlib import PurePosixPath

import xxhash

import index

RUN_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


def run_config(event):
    cfg = {}
    if event.get("modelId"):
        cfg["modelId"] = event["modelId"]
    if event.get("detect"):
        cfg["detect"] = event["detect"]
    if event.get("reviewModelId"):
        cfg["review"] = {"modelId": event["reviewModelId"]}
    return cfg


def lambda_handler(event, context):
    run_id, asset_id = event.get("runId") or "", event.get("assetId") or ""
    for name, value in (("runId", run_id), ("assetId", asset_id)):
        if not RUN_ID.match(value):
            raise index.InputError(f"{name} {value!r} must be 1-80 letters, digits, '-' or '_'")
    m = re.match(r"^s3://([^/]+)/(.+)$", event.get("s3Uri") or "")
    if not m:
        raise index.InputError(f"s3Uri {event.get('s3Uri')!r} is not an S3 URI")
    manifest = index.lambda_handler({"bucket": m.group(1), "key": m.group(2),
                                     "fileName": PurePosixPath(event.get("path") or "").name,
                                     "config": run_config(event), "executionName": run_id}, context)
    pages_prefix = f"{run_id}/sdma/pages/"
    for p in manifest["pages"]:
        body = index.s3.get_object(Bucket=index.OUTPUT_BUCKET, Key=p["pageKey"])["Body"].read()
        index.s3.put_object(Bucket=index.OUTPUT_BUCKET, Key=f"{pages_prefix}{p['sheetId']}.page.png", Body=body,
                            ContentType="image/png")
        index.s3.put_object(Bucket=index.OUTPUT_BUCKET,
                            Key=f"sdma-pages/{asset_id}/{xxhash.xxh128(body).hexdigest()}.json",
                            Body=json.dumps({"runId": run_id}),
                            ContentType="application/json")
    index.log.info("run %s: %d page(s) for SDMA", run_id, len(manifest["pages"]))
    return {"runId": run_id, "pages": len(manifest["pages"]),
            "pagesPrefix": f"s3://{index.OUTPUT_BUCKET}/{pages_prefix}"}
