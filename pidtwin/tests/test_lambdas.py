"""Lambda handlers in cdk/lambda/, run against an in-memory S3 (no AWS calls).

Run: python -m unittest discover tests
"""
import importlib
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
DEFAULTS = {"modelId": ALLOWED[0], "detect": "tiled", "review": {"enabled": True, "maxViews": 40, "modelId": None},
            "dashedAsPiping": False,
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

    def copy_object(self, Bucket, Key, CopySource):
        from botocore.exceptions import ClientError
        src = CopySource["Bucket"], CopySource["Key"]
        if src not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "CopyObject")
        self.objects[Bucket, Key] = self.objects[src]


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
        self.assertEqual(out["config"]["review"], {"enabled": True, "maxViews": 10, "modelId": None})
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
               ({"key": "a.png", "config": {"detect": "fast"}}, "detect"),
               ({"key": "a.png", "config": {"review": {"modelId": "us.example.unlisted-model"}}}, "review.modelId"),
               ({"key": "a.docx"}, "unsupported"),
               ({"key": "missing.png"}, "not found"),
               ({"key": "a.png", "bucket": "elsewhere"}, "input bucket"),
               ({"key": "fake.png"}, "cannot read")]
        for event, msg in bad:
            with self.assertRaises(self.mod.InputError) as e:
                self.mod.lambda_handler({"bucket": "in", "executionName": "x", **event}, None)
            self.assertIn(msg, str(e.exception))

    def test_sdma_content_is_named_by_file_name(self):
        mod = load("prepare_input", {"INPUT_BUCKET": "in", "OUTPUT_BUCKET": "out", "SOURCE_BUCKETS": '["in", "sdma"]',
                                     "DEFAULT_CONFIG": json.dumps(DEFAULTS), "ALLOWED_MODEL_IDS": json.dumps(ALLOWED)})
        mod.s3.objects["sdma", "9f86d081884c7d65"] = png_bytes()
        out = mod.lambda_handler({"bucket": "sdma", "key": "9f86d081884c7d65", "fileName": "Area 1.png",
                                  "executionName": "run1"}, None)
        self.assertEqual(out["pages"][0]["sheetId"], "Area_1")
        self.assertEqual(out["source"]["fileName"], "Area 1.png")
        with self.assertRaises(mod.InputError):  # without the name there is no file type
            mod.lambda_handler({"bucket": "sdma", "key": "9f86d081884c7d65", "executionName": "run2"}, None)


class MergeSheets(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
        self.mod = load("merge_sheets", {})

    def test_plant_outputs_and_partial_status(self):
        from pidtwin.graph.build import build_graph
        s3 = self.mod.s3
        for sid in ("a", "b"):
            s3.objects["out", f"ex/sheets/{sid}/graph.json"] = build_graph(SHEET, sheet=sid).model_dump_json().encode()
        s3.objects["out", "ex/sheets/a/overlay.png"] = b"png"
        usage = {"inputTokens": 10, "outputTokens": 5}
        # successes are the agent's sheet summary (sheet_id); failures come from the SheetFailed state (sheetId)
        results = [{"status": "SUCCEEDED", "sheet_id": s, "outputPrefix": f"ex/sheets/{s}/", "usage": usage, "usd": 0.5}
                   for s in ("a", "b")] + [{"status": "FAILED", "sheetId": "c", "error": "ThrottlingException"}]
        out = self.mod.lambda_handler({"bucket": "out", "prefix": "ex/", "results": results,
                                       "config": {"modelId": ALLOWED[0]}}, None)
        self.assertEqual(out["status"], "PARTIAL")
        self.assertEqual(out["sheets"], {"total": 3, "succeeded": 2})
        self.assertEqual(out["usd"], 1.0)
        for name in ("plant.graph.json", "plant.issues.json", "plant.dexpi.xml", "plant.dot", "summary.json"):
            self.assertIn(("out", f"ex/{name}"), s3.objects)
        self.assertEqual(s3.objects["out", "ex/overlays/a.overlay.png"], b"png")
        self.assertNotIn(("out", "ex/overlays/b.overlay.png"), s3.objects)  # b has no overlay: skipped, not fatal
        self.assertNotIn(("out", "ex/_FAILED.json"), s3.objects)
        summary = json.loads(s3.objects["out", "ex/summary.json"])
        self.assertEqual(summary["usage"]["inputTokens"], 20)

    def test_all_failed(self):
        out = self.mod.lambda_handler({"bucket": "out", "prefix": "ex/",
                                       "results": [{"status": "FAILED", "sheetId": "a"}]}, None)
        self.assertEqual(out["status"], "FAILED")
        self.assertEqual(list(out["outputs"]), ["summary"])
        self.assertIn("1 sheet", json.loads(self.mod.s3.objects["out", "ex/_FAILED.json"])["message"])


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


class SdmaStart(unittest.TestCase):
    def setUp(self):
        self.mod = load("sdma_start", {"STATE_MACHINE_ARN": "arn:aws:states:us-east-1:1:stateMachine:sm",
                                       "CONTENT_BUCKET": "sdma", "OUTPUT_BUCKET": "out"})
        self.calls = []
        calls = self.calls

        class Sfn:
            def start_execution(self, **kw):
                calls.append(kw)
                return {"executionArn": f"arn:aws:states:us-east-1:1:execution:sm:{kw['name']}"}
        self.mod.sfn = Sfn()

    def test_starts_named_execution_with_overrides(self):
        out = self.mod.lambda_handler({"runId": "inv-1", "s3Uri": "s3://sdma/ab/cd", "path": "plans/Area 1.PDF",
                                       "modelId": ALLOWED[1], "detect": "", "reviewModelId": ALLOWED[0]}, None)
        self.assertEqual(out["outputPrefix"], "s3://out/inv-1/")
        self.assertEqual(self.calls[0]["name"], "inv-1")
        self.assertEqual(json.loads(self.calls[0]["input"]),
                         {"bucket": "sdma", "key": "ab/cd", "fileName": "Area 1.PDF",
                          "config": {"modelId": ALLOWED[1], "review": {"modelId": ALLOWED[0]}}})

    def test_rejects_bad_events(self):
        ok = {"runId": "inv-1", "s3Uri": "s3://sdma/ab", "path": "a.png"}
        for bad, msg in [({"runId": "a b"}, "runId"), ({"s3Uri": "s3://other/ab"}, "content bucket"),
                         ({"path": "model.ifc"}, "drawing")]:
            with self.assertRaises(ValueError) as e:
                self.mod.lambda_handler({**ok, **bad}, None)
            self.assertIn(msg, str(e.exception))
        self.assertEqual(self.calls, [])


def load_sdma(name, env):
    """The SDMA stage handler (sdma.py) next to a Lambda's index.py, which it imports."""
    sys.path.insert(0, str(LAMBDA / name))
    try:
        with mock.patch.dict(os.environ, {"AWS_DEFAULT_REGION": "us-east-1", **env}):
            sys.modules.pop("index", None)
            index = importlib.import_module("index")
            spec = importlib.util.spec_from_file_location(f"sdma_{name}", LAMBDA / name / "sdma.py")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
    finally:
        sys.path.remove(str(LAMBDA / name))
        sys.modules.pop("index", None)
    return mod, index


class SdmaStages(unittest.TestCase):
    def test_render_pages_names_each_page_for_stage_2(self):
        mod, index = load_sdma("prepare_input", {"INPUT_BUCKET": "out", "OUTPUT_BUCKET": "out", "SOURCE_BUCKETS": '["sdma"]',
                                                 "DEFAULT_CONFIG": json.dumps(DEFAULTS),
                                                 "ALLOWED_MODEL_IDS": json.dumps(ALLOWED)})
        index.s3 = FakeS3()
        index.s3.objects["sdma", "p/Data/ab.xxh128"] = png_bytes()
        out = mod.lambda_handler({"runId": "inv-1", "assetId": "asset-1", "s3Uri": "s3://sdma/p/Data/ab.xxh128",
                                  "path": "dir/Area 1.png", "modelId": ALLOWED[1], "detect": "", "reviewModelId": ""},
                                 None)
        self.assertEqual(out, {"runId": "inv-1", "pages": 1, "pagesPrefix": "s3://out/inv-1/sdma/pages/"})
        page = index.s3.objects["out", "inv-1/sdma/pages/Area_1.page.png"]
        # stage 2 finds the run by the page's xxh128, the hash SDMA gives the ingested page
        entry = json.loads(index.s3.objects["out", f"sdma-pages/asset-1/{mod.xxhash.xxh128(page).hexdigest()}.json"])
        self.assertEqual(entry, {"runId": "inv-1"})
        manifest = json.loads(index.s3.objects["out", "inv-1/input.json"])
        self.assertEqual(manifest["config"]["modelId"], ALLOWED[1])
        with self.assertRaises(index.InputError):
            mod.lambda_handler({"runId": "bad id", "assetId": "asset-1", "s3Uri": "s3://sdma/x", "path": "a.png"}, None)

    def test_digitize_sheet_starts_the_agent_in_export_mode(self):
        mod, index = load_sdma("dispatch_sheet", {"AGENT_RUNTIME_ARN": "arn:aws:bedrock-agentcore:us-east-1:1:runtime/x",
                                                  "OUTPUT_BUCKET": "out"})
        mod.s3 = FakeS3()
        mod.s3.objects["out", f"sdma-pages/asset-1/{'a' * 32}.json"] = b'{"runId": "inv-1"}'
        mod.s3.objects["out", "inv-1/input.json"] = json.dumps({"config": DEFAULTS, "pages": [
            {"sheetId": "Area_1", "pageKey": "inv-1/pages/Area_1.png", "outputPrefix": "inv-1/sheets/Area_1/"}]}).encode()
        calls = []

        class Agent:
            def invoke_agent_runtime(self, **kw):
                calls.append(kw)
                return {"response": io.BytesIO(b'{"status": "accepted"}')}
        index.agentcore = Agent()
        ok = {"invocationId": "inv-2", "assetId": "asset-1", "hash": "a" * 32, "path": "x/Area_1.page.png"}
        out = mod.lambda_handler(ok, None)
        self.assertEqual(out["exportPrefix"], "s3://out/sdma-sheets/inv-2/")
        payload = json.loads(calls[0]["payload"])
        self.assertEqual((payload["pageKey"], payload["outputPrefix"], payload["export"]),
                         ("inv-1/pages/Area_1.png", "inv-1/sheets/Area_1/", {"prefix": "sdma-sheets/inv-2/", "name": "Area_1"}))
        for bad, msg in [({"hash": "b" * 32}, "not a page rendered by stage 1"), ({"hash": "xyz"}, "xxh128"),
                         ({"assetId": ""}, "assetId"), ({"path": "x/overlay.png"}, "rendered page"),
                         ({"path": "x/B.page.png"}, "no sheet")]:
            with self.assertRaises(ValueError) as e:
                mod.lambda_handler({**ok, **bad}, None)
            self.assertIn(msg, str(e.exception))

    def test_merge_plant_waits_for_every_sheet_then_merges(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
        from pidtwin.graph.build import build_graph
        mod, index = load_sdma("merge_sheets", {"OUTPUT_BUCKET": "out", "CONTENT_BUCKET": "sdma"})
        index.s3 = s3 = FakeS3()
        pages = [{"sheetId": s, "pageKey": f"r1/pages/{s}.png", "outputPrefix": f"r1/sheets/{s}/"} for s in ("a", "b")]
        s3.objects["out", "r1/input.json"] = json.dumps({"source": {}, "config": {"modelId": ALLOWED[0]},
                                                         "pages": pages}).encode()
        result_a = {"status": "SUCCEEDED", "sheet_id": "a", "outputPrefix": "r1/sheets/a/", "usage": {}, "usd": 0.2}
        s3.objects["out", "r1/sheets/a/graph.json"] = build_graph(SHEET, sheet="a").model_dump_json().encode()
        s3.objects["out", "r1/sheets/a/result.json"] = json.dumps(result_a).encode()
        s3.objects["sdma", "p/Data/h1.xxh128"] = json.dumps(result_a).encode()
        event = {"s3Uri": "s3://sdma/p/Data/h1.xxh128"}

        out = mod.lambda_handler(event, None)  # sheet b not done yet
        self.assertEqual((out["status"], out["sheetsDone"], out["sheets"]), ("PENDING", 1, 2))
        self.assertEqual(out["plantPrefix"], "s3://out/r1/")
        self.assertNotIn(("out", "r1/plant.graph.json"), s3.objects)

        s3.objects["out", "r1/sheets/b/result.json"] = json.dumps(
            {"status": "FAILED", "sheet_id": "b", "outputPrefix": "r1/sheets/b/", "error": "TimeoutError"}).encode()
        out = mod.lambda_handler(event, None)  # the last sheet's run merges
        self.assertEqual((out["status"], out["sheetsDone"]), ("PARTIAL", 2))
        self.assertGreater(out["nodes"], 0)
        for name in ("plant.graph.json", "plant.dexpi.xml", "plant.issues.json", "summary.json"):
            self.assertIn(("out", f"r1/{name}"), s3.objects)
        with self.assertRaises(ValueError):
            mod.lambda_handler({"s3Uri": "s3://other/x"}, None)


if __name__ == "__main__":
    unittest.main()
