"""PrepareInput: first state of the P&ID digitization workflow.

Checks the uploaded drawing, merges the per-execution config over the deployment defaults, and
writes one PNG per sheet to <execution>/pages/ in the output bucket (PDFs are rendered page by page;
images are copied). Returns the page list the Map state fans out over.

Event (manual StartExecution or the S3 upload rule):
  {"bucket": "<input bucket>", "key": "drawings/x.pdf", "config": {...optional overrides...},
   "executionName": "<from the state machine context>"}
"""
import copy
import json
import logging
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import unquote_plus

from botocore.exceptions import ClientError
from PIL import Image

from pidtwin.digitize.pdf import render
from pidtwin.solution import get_client

log = logging.getLogger()
log.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

s3 = get_client("s3")
INPUT_BUCKET = os.environ["INPUT_BUCKET"]
OUTPUT_BUCKET = os.environ["OUTPUT_BUCKET"]
DEFAULT_CONFIG = json.loads(os.environ["DEFAULT_CONFIG"])
ALLOWED_MODEL_IDS = json.loads(os.environ["ALLOWED_MODEL_IDS"])
IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"}
MAX_INPUT_BYTES = int(os.environ.get("MAX_INPUT_MB", "200")) * 1024 * 1024
Image.MAX_IMAGE_PIXELS = 400_000_000


class InputError(Exception):
    """Bad input or config: the workflow fails without retrying."""


def merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        out[k] = merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def check_config(cfg):
    if cfg.get("modelId") not in ALLOWED_MODEL_IDS:
        raise InputError(f"modelId {cfg.get('modelId')!r} is not allowed; choose one of {ALLOWED_MODEL_IDS} "
                         "(the list is set by digitization.allowedModelIds in cdk/config.json)")
    views = cfg["review"].get("maxViews")
    if not isinstance(views, int) or not 1 <= views <= 200:
        raise InputError("review.maxViews must be an integer from 1 to 200")
    if not isinstance(cfg["review"].get("enabled"), bool) or not isinstance(cfg.get("dashedAsPiping"), bool):
        raise InputError("review.enabled and dashedAsPiping must be true or false")
    dpi, pages = cfg["pdf"].get("dpi"), cfg["pdf"].get("maxPages")
    if not isinstance(dpi, int) or not 72 <= dpi <= 600:
        raise InputError("pdf.dpi must be an integer from 72 to 600")
    if not isinstance(pages, int) or not 1 <= pages <= 500:
        raise InputError("pdf.maxPages must be an integer from 1 to 500")
    return cfg


def head(bucket, key):
    """S3 event keys can arrive URL-encoded; try the key as given, then decoded."""
    for k in dict.fromkeys([key, unquote_plus(key)]):
        try:
            return k, s3.head_object(Bucket=bucket, Key=k)
        except ClientError as e:
            if e.response["Error"]["Code"] not in ("404", "NoSuchKey", "NotFound"):
                raise
    raise InputError(f"s3://{bucket}/{key} not found")


def sheet_id(stem):
    return re.sub(r"[^A-Za-z0-9._-]", "_", stem)[:80] or "sheet"


def lambda_handler(event, context):
    bucket = event.get("bucket") or INPUT_BUCKET
    if bucket != INPUT_BUCKET:
        raise InputError(f"drawings must be uploaded to the input bucket {INPUT_BUCKET}")
    key, meta = head(bucket, event["key"])
    ext = Path(key).suffix.lower()
    if ext not in IMAGE_TYPES | {".pdf"}:
        raise InputError(f"unsupported file type {ext!r}; use PDF or one of {sorted(IMAGE_TYPES)}")
    if meta["ContentLength"] > MAX_INPUT_BYTES:
        raise InputError(f"file is {meta['ContentLength'] / 2**20:.0f} MB; the limit is {MAX_INPUT_BYTES / 2**20:.0f} MB")
    cfg = check_config(merge(DEFAULT_CONFIG, event.get("config")))
    prefix = f"{event['executionName']}/"
    stem = sheet_id(Path(key).stem)

    pages = []
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / f"{stem}{ext}"
        s3.download_file(bucket, key, str(src))
        # reject files that are not what they claim before paying for model calls
        try:
            if ext == ".pdf":
                files = render(src, Path(tmp) / "pages", dpi=cfg["pdf"]["dpi"], max_pages=cfg["pdf"]["maxPages"])
            else:
                with Image.open(src) as im:
                    im.verify()
                files = [src]
        except Exception as e:
            raise InputError(f"cannot read {key}: {e}") from e
        for f in files:
            sid = sheet_id(f.stem)
            page_key = f"{prefix}pages/{f.name}"
            s3.upload_file(str(f), OUTPUT_BUCKET, page_key)
            pages.append({"sheetId": sid, "pageKey": page_key, "outputPrefix": f"{prefix}sheets/{sid}/"})
    log.info("s3://%s/%s -> %d page(s), model %s", bucket, key, len(pages), cfg["modelId"])

    manifest = {"source": {"bucket": bucket, "key": key, "versionId": meta.get("VersionId")},
                "config": cfg, "pages": pages}
    s3.put_object(Bucket=OUTPUT_BUCKET, Key=f"{prefix}input.json", Body=json.dumps(manifest, indent=2),
                  ContentType="application/json")
    return {"bucket": OUTPUT_BUCKET, "prefix": prefix, **manifest}
