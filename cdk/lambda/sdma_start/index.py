"""SdmaStart: the Spatial Data Management on AWS (SDMA) connector's way into the workflow.

SDMA cannot sign requests to Step Functions, so the connector's lambdaInvoke step calls this function,
which starts one execution named after the connector invocation. The workflow then writes its results
under s3://<output bucket>/<runId>/, where the connector's wait step picks them up
(docs/SDMA_CONNECTOR.md). The drawing is read in place from SDMA's content store.

Event (the connector's field mappings):
  {"runId": "<parameters.connectorInvocationId>", "s3Uri": "<file.s3Uri>", "path": "<file.path>",
   "modelId": "", "detect": "", "reviewModelId": ""}   (empty = deployment default)
"""
import json
import logging
import os
import re
from pathlib import PurePosixPath

import boto3
from botocore.config import Config

log = logging.getLogger()
log.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# bundled without pidtwin, like DispatchSheet (pidtwin/src/pidtwin/solution.py explains the token)
sfn = boto3.client("stepfunctions", config=Config(user_agent_extra=os.environ.get("USER_AGENT_STRING", "")))
STATE_MACHINE_ARN = os.environ["STATE_MACHINE_ARN"]
CONTENT_BUCKET = os.environ["CONTENT_BUCKET"]
OUTPUT_BUCKET = os.environ["OUTPUT_BUCKET"]
EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"}
RUN_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")  # also a valid execution name


def run_config(event):
    """Per-run overrides from the trigger's parameters; PrepareInput validates them."""
    cfg = {}
    if event.get("modelId"):
        cfg["modelId"] = event["modelId"]
    if event.get("detect"):
        cfg["detect"] = event["detect"]
    if event.get("reviewModelId"):
        cfg["review"] = {"modelId": event["reviewModelId"]}
    return cfg


def lambda_handler(event, context):
    run_id = event.get("runId") or ""
    if not RUN_ID.match(run_id):
        raise ValueError(f"runId {run_id!r} must be 1-80 letters, digits, '-' or '_'")
    m = re.match(r"^s3://([^/]+)/(.+)$", event.get("s3Uri") or "")
    if not m or m.group(1) != CONTENT_BUCKET:
        raise ValueError(f"s3Uri {event.get('s3Uri')!r} is not in the SDMA content bucket {CONTENT_BUCKET}")
    name = PurePosixPath(event.get("path") or "").name
    if PurePosixPath(name).suffix.lower() not in EXTENSIONS:
        raise ValueError(f"{name!r} is not a PDF or image drawing")

    execution_input = {"bucket": m.group(1), "key": m.group(2), "fileName": name, "config": run_config(event)}
    # same name and input: Step Functions returns the existing execution, so a retried step starts nothing new
    resp = sfn.start_execution(stateMachineArn=STATE_MACHINE_ARN, name=run_id, input=json.dumps(execution_input))
    log.info("%s (%s) -> %s", name, m.group(2), resp["executionArn"])
    return {"executionArn": resp["executionArn"], "outputPrefix": f"s3://{OUTPUT_BUCKET}/{run_id}/"}
