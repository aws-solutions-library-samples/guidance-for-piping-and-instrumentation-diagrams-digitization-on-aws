"""Lambda handlers in cdk/lambda/, run against an in-memory S3 (no AWS calls).

Run: python -m unittest discover tests
"""
import importlib.util
import io
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

LAMBDA = Path(__file__).resolve().parents[2] / "cdk" / "lambda"
SHEET = json.loads((Path(__file__).parent / "data" / "synthetic.sonnet.digitized.json").read_text())
ALLOWED = ["us.anthropic.claude-sonnet-5-5", "us.openai.gpt-6.1-sol"]
DEFAULTS = {"modelId": ALLOWED[0], "review": {"enabled": True, "maxViews": 40}, "dashedAsPiping": False,
            "pdf": {"dpi": 150, "maxPages": 5}}


class FakeS3:
    class exceptions:
        NoSuchKey = KeyError

    def __init__(self):
        self.objects = {}

    def head_object(self, Bucket, Key):
        from botocore.exceptions import ClientError
        if (Bucket, Key) not in self.objects:
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")
        return {"ContentLength": len(self.objects[Bucket, Key]), "VersionId": "v1"}

    def download_file(self, Bucket, Key, Filename):
        Path(Filename).write_bytes(self.objects[Bucket, Key])

    def upload_file(self, Filename, Bucket, Key):
        self.objects[Bucket, Key] = Path(Filename).read_bytes()

    def put_object(self, Bucket, Key, Body, ContentType=None):
        self.objects[Bucket, Key] = Body.encode() if isinstance(Body, str) else Body

    def get_object(self, Bucket, Key):
        return {"Body": io.BytesIO(self.objects[Bucket, Key])}


def load(name, env):
    with mock.patch.dict(os.environ, {"AWS_DEFAULT_REGION": "us-east-1", **env}):
        spec = importlib.util.spec_from_file_location(f"lambda_{name}", LAMBDA / name / "index.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    mod.s3 = FakeS3()
    return mod


def png_bytes(size=(400, 300)):
    buf = io.BytesIO()
    Image.new("L", size, 255).save(buf, "PNG")
    return buf.getvalue()


class PrepareInput(unittest.TestCase):
    def setUp(self):
        self.mod = load("prepare_input", {"INPUT_BUCKET": "in", "OUTPUT_BUCKET": "out",
                                          "DEFAULT_CONFIG": json.dumps(DEFAULTS), "ALLOWED_MODEL_IDS": json.dumps(ALLOWED)})

    def test_image_becomes_one_page_with_merged_config(self):
        self.mod.s3.objects["in", "drawings/My Sheet 1.png"] = png_bytes()
        out = self.mod.lambda_handler({"bucket": "in", "key": "drawings/My+Sheet+1.png", "executionName": "ex1",
                                       "config": {"modelId": ALLOWED[1], "review": {"maxViews": 10}}}, None)
        self.assertEqual(out["config"]["modelId"], ALLOWED[1])
        self.assertEqual(out["config"]["review"], {"enabled": True, "maxViews": 10})
        self.assertEqual(out["pages"], [{"sheetId": "My_Sheet_1", "pageKey": "ex1/pages/My_Sheet_1.png",
                                         "outputPrefix": "ex1/sheets/My_Sheet_1/"}])
        self.assertIn(("out", "ex1/pages/My_Sheet_1.png"), self.mod.s3.objects)
        self.assertIn(("out", "ex1/input.json"), self.mod.s3.objects)

    def test_pdf_pages_are_rendered(self):
        from PIL import JpegImagePlugin  # noqa: F401 (the PDF writer needs the JPEG encoder)
        buf = io.BytesIO()
        im = Image.new("RGB", (600, 400), "white")
        im.save(buf, "PDF", save_all=True, append_images=[im])
        self.mod.s3.objects["in", "drawings/plant.pdf"] = buf.getvalue()
        out = self.mod.lambda_handler({"bucket": "in", "key": "drawings/plant.pdf", "executionName": "ex2"}, None)
        self.assertEqual([p["sheetId"] for p in out["pages"]], ["plant.p1", "plant.p2"])

    def test_bad_input_is_rejected(self):
        self.mod.s3.objects["in", "a.png"] = png_bytes()
        self.mod.s3.objects["in", "a.docx"] = b"x"
        self.mod.s3.objects["in", "fake.png"] = b"not a png"
        bad = [({"key": "a.png", "config": {"modelId": "us.example.unlisted-model"}}, "not allowed"),
               ({"key": "a.png", "config": {"review": {"maxViews": 0}}}, "maxViews"),
               ({"key": "a.docx"}, "unsupported"),
               ({"key": "missing.png"}, "not found"),
               ({"key": "a.png", "bucket": "elsewhere"}, "input bucket"),
               ({"key": "fake.png"}, "cannot read")]
        for event, msg in bad:
            with self.assertRaises(self.mod.InputError) as e:
                self.mod.lambda_handler({"bucket": "in", "executionName": "x", **event}, None)
            self.assertIn(msg, str(e.exception))


class MergeSheets(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
        self.mod = load("merge_sheets", {})

    def test_plant_outputs_and_partial_status(self):
        from pidtwin.graph.build import build_graph
        s3 = self.mod.s3
        for sid in ("a", "b"):
            s3.objects["out", f"ex/sheets/{sid}/graph.json"] = build_graph(SHEET, sheet=sid).model_dump_json().encode()
        usage = {"inputTokens": 10, "outputTokens": 5}
        results = [{"status": "SUCCEEDED", "sheetId": s, "outputPrefix": f"ex/sheets/{s}/", "usage": usage, "usd": 0.5}
                   for s in ("a", "b")] + [{"status": "FAILED", "sheetId": "c", "error": "ThrottlingException"}]
        out = self.mod.lambda_handler({"bucket": "out", "prefix": "ex/", "results": results,
                                       "config": {"modelId": ALLOWED[0]}}, None)
        self.assertEqual(out["status"], "PARTIAL")
        self.assertEqual(out["sheets"], {"total": 3, "succeeded": 2})
        self.assertEqual(out["usd"], 1.0)
        for name in ("plant.graph.json", "plant.issues.json", "plant.dexpi.xml", "plant.dot", "summary.json"):
            self.assertIn(("out", f"ex/{name}"), s3.objects)
        summary = json.loads(s3.objects["out", "ex/summary.json"])
        self.assertEqual(summary["usage"]["inputTokens"], 20)

    def test_all_failed(self):
        out = self.mod.lambda_handler({"bucket": "out", "prefix": "ex/",
                                       "results": [{"status": "FAILED", "sheetId": "a"}]}, None)
        self.assertEqual(out["status"], "FAILED")
        self.assertEqual(list(out["outputs"]), ["summary"])


class DispatchSheet(unittest.TestCase):
    def test_session_differs_per_retry_and_rejection_raises(self):
        mod = load("dispatch_sheet", {"AGENT_RUNTIME_ARN": "arn:aws:bedrock-agentcore:us-east-1:1:runtime/x"})
        calls = []

        class Agent:
            def invoke_agent_runtime(self, **kw):
                calls.append(kw)
                return {"response": io.BytesIO(json.dumps({"status": reply}).encode())}
        mod.agentcore = Agent()
        event = {"taskToken": "t", "execution": "arn:exec", "bucket": "out", "config": DEFAULTS,
                 "page": {"sheetId": "a", "pageKey": "ex/pages/a.png", "outputPrefix": "ex/sheets/a/"}}
        reply = "accepted"
        s0 = mod.lambda_handler({**event, "retryCount": 0}, None)["sessionId"]
        s1 = mod.lambda_handler({**event, "retryCount": 1}, None)["sessionId"]
        self.assertNotEqual(s0, s1)
        self.assertGreaterEqual(len(s0), 33)
        self.assertEqual(json.loads(calls[0]["payload"])["taskToken"], "t")
        reply = "busy"
        with self.assertRaises(RuntimeError):
            mod.lambda_handler(event, None)


if __name__ == "__main__":
    unittest.main()
