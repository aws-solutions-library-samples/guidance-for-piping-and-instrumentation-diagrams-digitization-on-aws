"""SDMA stage 2, "Digitize sheet": start the agent for one page that stage 1 rendered.

The digitize connector runs once per <sheetId>.page.png derived file. The sheet is the page's file
name; the run comes from sdma-pages/<assetId>/<page hash>.json (written by stage 1; identical pages
share one entry, which is why it holds only the run) and its config from <runId>/input.json. It
starts an AgentCore session in export mode: the agent writes the sheet's outputs to the run's
sheets/<sheetId>/ as usual, then copies the ones SDMA ingests to sdma-sheets/<invocation>/ and writes
<sheetId>.result.json last, which the connector's wait step completes on.

Event (the connector's field mappings):
  {"invocationId": "<parameters.connectorInvocationId>", "assetId": "<file.assetId>", "hash": "<file.hash>",
   "path": "<file.path>"}
"""
import hashlib
import json
import re
from pathlib import PurePosixPath

import boto3

import index

OUTPUT_BUCKET = index.os.environ["OUTPUT_BUCKET"]
s3 = boto3.client("s3", config=index.Config(user_agent_extra=index.os.environ.get("USER_AGENT_STRING", "")))
ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
HASH = re.compile(r"^[0-9a-f]{32}$")


def lambda_handler(event, context):
    inv, asset_id, page_hash = event.get("invocationId") or "", event.get("assetId") or "", event.get("hash") or ""
    for name, value in (("invocationId", inv), ("assetId", asset_id)):
        if not ID.match(value):
            raise ValueError(f"{name} {value!r} must be 1-80 letters, digits, '-' or '_'")
    if not HASH.match(page_hash):
        raise ValueError(f"hash {page_hash!r} is not an xxh128 digest")
    page_name = PurePosixPath(event.get("path") or "").name
    if not page_name.endswith(".page.png"):
        raise ValueError(f"{page_name!r} is not a rendered page (<sheetId>.page.png)")
    sheet_id = page_name[: -len(".page.png")]
    try:
        index_key = f"sdma-pages/{asset_id}/{page_hash}.json"
        entry = json.loads(s3.get_object(Bucket=OUTPUT_BUCKET, Key=index_key)["Body"].read())
    except s3.exceptions.NoSuchKey:
        raise ValueError(f"{event.get('path')!r} is not a page rendered by stage 1 (no run for hash {page_hash})")
    run_id = entry["runId"]

    manifest = json.loads(s3.get_object(Bucket=OUTPUT_BUCKET, Key=f"{run_id}/input.json")["Body"].read())
    page = next((p for p in manifest["pages"] if p["sheetId"] == sheet_id), None)
    if page is None:
        raise ValueError(f"run {run_id} has no sheet {sheet_id!r}")
    payload = {"bucket": OUTPUT_BUCKET, "pageKey": page["pageKey"], "outputPrefix": page["outputPrefix"],
               "sheetId": sheet_id, "config": manifest["config"],
               "export": {"prefix": f"sdma-sheets/{inv}/", "name": sheet_id}}
    resp = index.agentcore.invoke_agent_runtime(
        agentRuntimeArn=index.RUNTIME_ARN, runtimeSessionId=hashlib.sha256(f"sdma|{inv}".encode()).hexdigest(),
        payload=json.dumps(payload).encode(), contentType="application/json", accept="application/json")
    body = resp["response"].read().decode()
    try:
        reply = json.loads(body)
    except ValueError:
        reply = None
    if not isinstance(reply, dict) or reply.get("status") != "accepted":
        raise RuntimeError(f"agent did not accept sheet {sheet_id}: {body[:500]}")
    index.log.info("run %s sheet %s dispatched (invocation %s)", run_id, sheet_id, inv)
    return {"runId": run_id, "sheetId": sheet_id, "exportPrefix": f"s3://{OUTPUT_BUCKET}/sdma-sheets/{inv}/"}
