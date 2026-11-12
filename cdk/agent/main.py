"""AgentCore Runtime entrypoint: digitize one P&ID sheet (detect -> trace -> review agent -> graph).

Invoked by the DispatchSheet Lambda once per sheet, with a Step Functions task token. The entrypoint
returns {"status": "accepted"} at once and digitizes in a background thread; the session reports
HealthyBusy while it works, heartbeats the task token, and resumes the state machine with
SendTaskSuccess / SendTaskFailure when done.

Payload:
  {"bucket": "...", "pageKey": "<exec>/pages/x.png", "outputPrefix": "<exec>/sheets/x/",
   "sheetId": "x", "config": {"modelId": ..., "detect": "tiled",
                               "review": {"enabled": true, "maxViews": 40, "modelId": null},
   "dashedAsPiping": false}, "taskToken": "..."}
Without taskToken the sheet is digitized synchronously and the summary returned (local testing only:
a long synchronous call blocks the ping endpoint).

SDMA stage mode (docs/SDMA_STAGES.md), from the SDMA DispatchSheet handler: no taskToken but
"export": {"prefix": "sdma-sheets/<invocation>/", "name": "<sheetId>"}. The sheet is digitized in the
background as above; then the outputs SDMA ingests are copied to <prefix><name>.<file>, the result
(the sheet summary, or {"status": "FAILED", ...}) is written to the sheet's own result.json, where
the SDMA merge stage counts finished sheets, and <prefix><name>.result.json is written last: it is
what the digitize connector's wait step completes on, success or not.
"""
import io
import json
import logging
import os
import threading

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from PIL import Image

from pidtwin.digitize.artifacts import S3Sink
from pidtwin.digitize.job import digitize_sheet
from pidtwin.solution import get_client

Image.MAX_IMAGE_PIXELS = 400_000_000  # PrepareInput caps rendered pages at 20,000 px per side

log = logging.getLogger("digitizer")
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))

app = BedrockAgentCoreApp()
s3 = get_client("s3")
sfn = get_client("stepfunctions")
HEARTBEAT_SECONDS = int(os.environ.get("HEARTBEAT_SECONDS", "60"))
ALLOWED_MODEL_IDS = set(json.loads(os.environ.get("ALLOWED_MODEL_IDS", "[]")))
OUTPUT_BUCKET = os.environ.get("OUTPUT_BUCKET")
# per-sheet outputs copied for the SDMA connector; distinct names, since they all land under one drawing
EXPORTED = ("graph.json", "dexpi.xml", "issues.json", "overlay.png")


def digitize(payload):
    cfg = payload["config"]
    model_id = cfg["modelId"]
    review = cfg.get("review") or {}
    for m in (model_id, review.get("modelId")):
        if m and ALLOWED_MODEL_IDS and m not in ALLOWED_MODEL_IDS:
            raise ValueError(f"model {m} is not in the allowed list {sorted(ALLOWED_MODEL_IDS)}")
    bucket = payload["bucket"]
    if OUTPUT_BUCKET and bucket != OUTPUT_BUCKET:
        raise ValueError(f"bucket {bucket} is not the pipeline's output bucket")
    body = s3.get_object(Bucket=bucket, Key=payload["pageKey"])["Body"].read()
    sheet = Image.open(io.BytesIO(body))
    sheet.load()
    log.info("sheet %s: %sx%s px, model %s", payload["sheetId"], *sheet.size, model_id)
    result = digitize_sheet(sheet, S3Sink(bucket, payload["outputPrefix"], s3), model_id, payload["sheetId"],
                            image_ref=f"s3://{bucket}/{payload['pageKey']}",
                            review=review.get("enabled", True), max_views=review.get("maxViews"),
                            dashed_as_piping=cfg.get("dashedAsPiping", False), detect=cfg.get("detect", "tiled"),
                            review_model_id=review.get("modelId"))
    return {**result, "status": "SUCCEEDED", "outputPrefix": payload["outputPrefix"]}


def _heartbeat(token, stop):
    while not stop.wait(HEARTBEAT_SECONDS):
        try:
            sfn.send_task_heartbeat(taskToken=token)
        except (sfn.exceptions.TaskTimedOut, sfn.exceptions.InvalidToken, sfn.exceptions.TaskDoesNotExist):
            log.warning("task token no longer valid (execution timed out or stopped)")
            return


def _background(payload, task_id):
    token, stop = payload["taskToken"], threading.Event()
    threading.Thread(target=_heartbeat, args=(token, stop), daemon=True).start()
    try:
        result = digitize(payload)
        sfn.send_task_success(taskToken=token, output=json.dumps(result, default=str))
    except Exception as e:  # report every failure to the state machine; it decides whether to retry
        log.exception("sheet %s failed", payload.get("sheetId"))
        try:
            sfn.send_task_failure(taskToken=token, error=type(e).__name__[:256], cause=str(e)[:32_000])
        except Exception:
            log.exception("could not report the failure to Step Functions")
    finally:
        stop.set()
        app.complete_async_task(task_id)


def _export(payload, result):
    """Copy the outputs to the export prefix, then write <name>.result.json last (SDMA stage mode).

    result.json carries exportPrefix: the connector's siblingDerivedFiles entries read it as
    ${response.exportPrefix}, because SDMA 1.7.0 does not resolve ${...} in siblingDerivedFiles URIs
    of an output-driven wait.
    """
    bucket, ex = payload["bucket"], payload["export"]
    out = f"{ex['prefix']}{ex['name']}"
    result = {**result, "exportPrefix": f"s3://{bucket}/{ex['prefix']}"}
    if result.get("status") == "SUCCEEDED":
        for f in EXPORTED:
            s3.copy_object(Bucket=bucket, Key=f"{out}.{f}",
                           CopySource={"Bucket": bucket, "Key": f"{payload['outputPrefix']}{f}"})
    body = json.dumps(result, default=str)
    s3.put_object(Bucket=bucket, Key=f"{payload['outputPrefix']}result.json", Body=body,
                  ContentType="application/json")
    s3.put_object(Bucket=bucket, Key=f"{out}.result.json", Body=body, ContentType="application/json")


def _background_export(payload, task_id):
    try:
        try:
            result = digitize(payload)
        except Exception as e:  # recorded in result.json, so the sheet still completes in SDMA
            log.exception("sheet %s failed", payload.get("sheetId"))
            result = {"status": "FAILED", "sheet_id": payload.get("sheetId"),
                      "outputPrefix": payload.get("outputPrefix"), "error": type(e).__name__,
                      "cause": str(e)[:32_000]}
        _export(payload, result)
    except Exception:
        log.exception("could not export sheet %s", payload.get("sheetId"))
    finally:
        app.complete_async_task(task_id)


@app.entrypoint
def invoke(payload):
    if payload.get("export"):
        task_id = app.add_async_task("digitize_sheet", {"sheetId": payload.get("sheetId")})
        threading.Thread(target=_background_export, args=(payload, task_id), daemon=True).start()
        return {"status": "accepted", "sheetId": payload.get("sheetId")}
    if not payload.get("taskToken"):
        return digitize(payload)
    task_id = app.add_async_task("digitize_sheet", {"sheetId": payload.get("sheetId")})
    threading.Thread(target=_background, args=(payload, task_id), daemon=True).start()
    return {"status": "accepted", "sheetId": payload.get("sheetId")}


if __name__ == "__main__":
    app.run()
