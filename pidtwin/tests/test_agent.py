"""AgentCore entrypoint (cdk/agent/main.py): task-token callbacks, with S3, Step Functions and the
digitizer replaced by fakes. Needs the test extra: pip install -e '.[test]'.

Run: python -m unittest discover tests
"""
import importlib.util
import io
import json
import os
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

AGENT = Path(__file__).resolve().parents[2] / "cdk" / "agent" / "main.py"
PAYLOAD = {"bucket": "out", "pageKey": "ex/pages/a.png", "outputPrefix": "ex/sheets/a/", "sheetId": "a",
           "config": {"modelId": "us.anthropic.claude-sonnet-5-5", "review": {"enabled": False, "maxViews": 5}},
           "taskToken": "tok"}


def load():
    env = {"AWS_DEFAULT_REGION": "us-east-1", "OUTPUT_BUCKET": "out", "HEARTBEAT_SECONDS": "3600",
           "ALLOWED_MODEL_IDS": json.dumps(["us.anthropic.claude-sonnet-5-5"])}
    with mock.patch.dict(os.environ, env):
        spec = importlib.util.spec_from_file_location("agent_main", AGENT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    buf = io.BytesIO()
    Image.new("L", (200, 100), 255).save(buf, "PNG")
    mod.s3 = mock.Mock()
    mod.s3.get_object.return_value = {"Body": io.BytesIO(buf.getvalue())}
    mod.sfn = mock.Mock()
    return mod


class Callbacks(unittest.TestCase):
    def test_success_resumes_the_execution(self):
        mod = load()
        with mock.patch.object(mod, "digitize_sheet", return_value={"sheet_id": "a", "usd": 0.1}) as dz:
            task = mod.app.add_async_task("t")
            mod._background(dict(PAYLOAD), task)
        kwargs = dz.call_args.kwargs
        self.assertEqual((kwargs["review"], kwargs["max_views"]), (False, 5))
        out = json.loads(mod.sfn.send_task_success.call_args.kwargs["output"])
        self.assertEqual((out["status"], out["outputPrefix"]), ("SUCCEEDED", "ex/sheets/a/"))
        mod.sfn.send_task_failure.assert_not_called()

    def test_failure_is_reported_with_the_exception_name(self):
        mod = load()
        with mock.patch.object(mod, "digitize_sheet", side_effect=TimeoutError("model timed out")):
            mod._background(dict(PAYLOAD), mod.app.add_async_task("t"))
        kw = mod.sfn.send_task_failure.call_args.kwargs
        self.assertEqual((kw["taskToken"], kw["error"]), ("tok", "TimeoutError"))

    def test_disallowed_model_and_foreign_bucket_fail(self):
        mod = load()
        for change in ({"config": {"modelId": "us.example.unlisted-model"}}, {"bucket": "someone-elses"}):
            mod.sfn.reset_mock()
            mod._background({**PAYLOAD, **change}, mod.app.add_async_task("t"))
            self.assertEqual(mod.sfn.send_task_failure.call_args.kwargs["error"], "ValueError")

    def test_entrypoint_returns_at_once(self):
        mod = load()
        with mock.patch.object(mod.threading, "Thread") as thread:
            self.assertEqual(mod.invoke(dict(PAYLOAD))["status"], "accepted")
        thread.return_value.start.assert_called_once()


if __name__ == "__main__":
    unittest.main()
