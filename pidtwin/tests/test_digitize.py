"""Digitizer plumbing that runs without Bedrock: artifact sinks, stage resume, the per-sheet job.

Run: python -m unittest discover tests
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")  # pipeline creates its Bedrock client at import

from PIL import Image  # noqa: E402

from pidtwin.digitize import job, pipeline  # noqa: E402
from pidtwin.digitize.artifacts import LocalSink  # noqa: E402

ITEMS = [
    {"id": "P-101", "category": "equipment", "type": "pump", "tag": "P-101", "bbox": [100, 480, 140, 520]},
    {"id": "HV-1", "category": "valve", "type": "gate valve", "tag": "HV-1", "bbox": [290, 490, 310, 510]},
    {"id": "OP1", "category": "offpage", "type": "offpage", "text": "TO UNIT 2", "bbox": [880, 490, 920, 510]},
    {"id": "L1", "category": "line_label", "type": "line number", "text": '4"-P-100', "bbox": [400, 470, 460, 480]},
]
TRACED = {"drawing": {"number": "S1"},
          "runs": [{"id": "R1", "kind": "process", "line_number": '4"-P-100', "items": ["P-101", "HV-1", "OP1"],
                    "path": [[140, 500], [880, 500]]}]}
USAGE = dict.fromkeys(pipeline.USAGE_KEYS, 1000)


class Sinks(unittest.TestCase):
    def test_local_sink_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            sink = LocalSink(f"{d}/out/a.")
            sink.save("x.json", {"k": 1})
            sink.save("t.txt", "hi")
            sink.save("i.png", Image.new("RGB", (4, 4)))
            self.assertEqual(sink.load_json("x.json"), {"k": 1})
            self.assertEqual(sink.load("t.txt"), b"hi")
            self.assertTrue(Path(f"{d}/out/a.i.png").read_bytes().startswith(b"\x89PNG"))
            self.assertIsNone(sink.load("missing.json"))


class Resume(unittest.TestCase):
    def test_finished_stages_are_not_called_again(self):
        sheet = Image.new("L", (1000, 1000), 255)
        with tempfile.TemporaryDirectory() as d:
            sink = LocalSink(f"{d}/s.")
            sink.save("trace.json", {"items": ITEMS, "traced": TRACED, "usage": USAGE, "seconds": 5})
            with mock.patch.object(pipeline, "call", side_effect=AssertionError("Bedrock called")):
                out, usage, secs = pipeline.run_pipeline("us.anthropic.claude-sonnet-5-5", "s.png", sheet, sink,
                                                         review=False, resume=True)
            self.assertEqual(usage, USAGE)
            self.assertEqual([v["tag"] for v in out["valves"]], ["HV-1"])
            self.assertEqual(out["_pipeline"]["resumed_from"], "trace")
            # without resume the stages run again
            with mock.patch.object(pipeline, "call", side_effect=RuntimeError("Bedrock called")):
                with self.assertRaises(RuntimeError):
                    pipeline.run_pipeline("m", "s.png", sheet, sink, review=False)

    def test_trace_runs_after_saved_detect(self):
        sheet = Image.new("L", (1000, 1000), 255)
        reply = json.dumps(TRACED)
        with tempfile.TemporaryDirectory() as d:
            sink = LocalSink(f"{d}/s.")
            sink.save("detect.json", {"tiles": 1, "raw": 4, "items": ITEMS, "usage": USAGE, "seconds": 3})
            with mock.patch.object(pipeline, "call", return_value=(reply, USAGE, 2.0)) as call:
                out, usage, _ = pipeline.run_pipeline("m", "s.png", sheet, sink, review=False, resume=True)
            self.assertEqual(call.call_count, 1)  # trace only
            self.assertEqual(usage["inputTokens"], 2000)
            self.assertEqual(len(out["runs"]), 1)
            self.assertIsNotNone(sink.load_json("trace.json"))


class Job(unittest.TestCase):
    def test_digitize_sheet_writes_every_artifact(self):
        sheet = Image.new("L", (1000, 1000), 255)
        with tempfile.TemporaryDirectory() as d:
            sink = LocalSink(f"{d}/s.")
            sink.save("trace.json", {"items": ITEMS, "traced": TRACED, "usage": USAGE, "seconds": 5})
            res = job.digitize_sheet(sheet, sink, "us.anthropic.claude-sonnet-5-5", "drawing.p1", review=False)
            for name in ("sheet.json", "graph.json", "issues.json", "dexpi.xml", "graph.dot", "overlay.png"):
                self.assertIsNotNone(sink.load(name), name)
            graph = sink.load_json("graph.json")
            self.assertEqual(graph["sheets"][0]["id"], "drawing.p1")
            self.assertEqual(graph["sheets"][0]["number"], "S1")
            self.assertEqual(res["counts"]["valves"], 1)
            self.assertAlmostEqual(res["usd"], pipeline.cost("us.anthropic.claude-sonnet-5-5", USAGE))


if __name__ == "__main__":
    unittest.main()
