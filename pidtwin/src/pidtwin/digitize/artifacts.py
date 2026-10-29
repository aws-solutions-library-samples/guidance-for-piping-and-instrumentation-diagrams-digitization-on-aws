"""Where the digitizer writes its intermediate and final files.

A sink stores named artifacts ("detect.json", "draft.json", "overlay.png", ...) under a prefix:
  LocalSink("results/1.Claude_Sonnet_55.")  -> results/1.Claude_Sonnet_55.detect.json
  S3Sink("bucket", "exec-id/sheet1/")      -> s3://bucket/exec-id/sheet1/detect.json
load() returns None for a missing artifact, so a re-run can resume after the last stage it finished.
"""
import io
import json
from pathlib import Path

CONTENT_TYPES = {".json": "application/json", ".png": "image/png", ".xml": "application/xml",
                 ".txt": "text/plain", ".dot": "text/vnd.graphviz"}


def _encode(data):
    if isinstance(data, bytes):
        return data
    if isinstance(data, str):
        return data.encode()
    if hasattr(data, "save"):  # PIL image
        buf = io.BytesIO()
        data.save(buf, "PNG", optimize=True)
        return buf.getvalue()
    return json.dumps(data, indent=2).encode()


class Sink:
    def save(self, name, data):
        raise NotImplementedError

    def load(self, name):
        raise NotImplementedError

    def load_json(self, name):
        raw = self.load(name)
        return json.loads(raw) if raw is not None else None


class LocalSink(Sink):
    def __init__(self, prefix):
        self.prefix = str(prefix)
        Path(self.prefix).parent.mkdir(parents=True, exist_ok=True)

    def save(self, name, data):
        path = Path(self.prefix + name)
        path.write_bytes(_encode(data))
        return str(path)

    def load(self, name):
        path = Path(self.prefix + name)
        return path.read_bytes() if path.exists() else None


class S3Sink(Sink):
    def __init__(self, bucket, prefix, client=None):
        import boto3
        self.bucket, self.prefix = bucket, prefix
        self.s3 = client or boto3.client("s3")

    def save(self, name, data):
        key = self.prefix + name
        self.s3.put_object(Bucket=self.bucket, Key=key, Body=_encode(data),
                           ContentType=CONTENT_TYPES.get(Path(name).suffix, "application/octet-stream"))
        return f"s3://{self.bucket}/{key}"

    def load(self, name):
        try:
            return self.s3.get_object(Bucket=self.bucket, Key=self.prefix + name)["Body"].read()
        except self.s3.exceptions.NoSuchKey:
            return None
