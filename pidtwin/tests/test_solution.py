"""pidtwin.solution and cdk/lib/solution.ts: the user-agent suffix and the stack description.

Both mechanisms fail silently in production — a client built without the suffix still works, and a stack
deployed with a description lacking the id still deploys — so these tests assert on the artifacts themselves.
For the user agent that means the actual outbound ``User-Agent`` header (captured from a real signed request,
intercepted before it leaves the process, so no credentials and no network are needed) rather than the Config
object passed in, because botocore is free to rewrite what it is given: the same string handed to
``user_agent_appid`` instead of ``user_agent_extra`` arrives with its slashes rewritten to dashes and matches
nothing.

Run: python -m unittest discover tests
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from botocore.config import Config

from pidtwin import solution

TOKEN = f"AWSSOLUTION/{solution.SOLUTION_ID}/{solution.SOLUTION_VERSION}"
REPO = solution.CONFIG_PATH.parent
CDK = REPO / "cdk"


def idents(suffix=""):
    """The parenthesised ids a description starts with: primary first, then each secondary."""
    return " ".join(f"({i}{suffix})" for i in [solution.SOLUTION_ID, *solution.SECONDARY_IDS])


class _Intercept(Exception):
    """Carries the request headers up out of botocore's send path."""

    def __init__(self, headers):
        self.headers = headers


def sent_user_agent(client, call="get_caller_identity", **params):
    """The User-Agent of a real request from `client`, without sending it."""
    def grab(request, **_kw):
        raise _Intercept(request.headers)

    client.meta.events.register("before-send.*.*", grab)
    try:
        getattr(client, call)(**params)
    except _Intercept as e:
        ua = e.headers["User-Agent"]
        return ua.decode() if isinstance(ua, bytes) else ua
    raise AssertionError("request was not intercepted; nothing was captured")


def signed_session():
    """A session with dummy credentials: enough to sign, nothing is ever sent."""
    import boto3
    return boto3.Session(aws_access_key_id="AKIAIOSFODNN7EXAMPLE",
                         aws_secret_access_key="test-secret-not-a-real-key", region_name="us-east-1")


def sts(**config_kwargs):
    config = Config(**config_kwargs) if config_kwargs else None
    return solution.get_client("sts", session=signed_session(), config=config)


@mock.patch.dict(os.environ, {"USER_AGENT_STRING": ""})
class UserAgentTest(unittest.TestCase):
    def test_token_reaches_the_wire_verbatim_and_once(self):
        ua = sent_user_agent(sts())
        # whole-token match: the metrics pipeline splits on whitespace, so the token with anything appended to
        # it (TOKEN + 'extra') would not count
        self.assertEqual(ua.split().count(TOKEN), 1, ua)
        # botocore's appid path would have rewritten the slashes
        self.assertNotIn(TOKEN.replace("/", "-"), ua)

    def test_existing_config_survives_the_merge(self):
        """A caller's timeouts/retries/pool size must not be dropped for the suffix."""
        merged = solution.solution_config(Config(read_timeout=120, connect_timeout=13,
                                                 retries={"max_attempts": 7}, max_pool_connections=25))
        self.assertEqual(merged.read_timeout, 120)
        self.assertEqual(merged.connect_timeout, 13)
        self.assertEqual(merged.retries, {"max_attempts": 7})
        self.assertEqual(merged.max_pool_connections, 25)

        client = sts(read_timeout=120, connect_timeout=13, retries={"max_attempts": 7}, max_pool_connections=25)
        cfg = client.meta.config
        self.assertEqual(cfg.read_timeout, 120)
        self.assertEqual(cfg.connect_timeout, 13)
        # botocore itself restates max_attempts (7 retries) as total_max_attempts (8 tries) when it builds the
        # client; the value survived the merge
        self.assertEqual(cfg.retries["total_max_attempts"], 8, cfg.retries)
        self.assertEqual(cfg.max_pool_connections, 25)
        self.assertEqual(sent_user_agent(client).split().count(TOKEN), 1)

    def test_foreign_user_agent_extra_is_concatenated_not_clobbered(self):
        fields = sent_user_agent(sts(user_agent_extra="SomeOtherComponent/1.2.3")).split()
        self.assertIn("SomeOtherComponent/1.2.3", fields)
        self.assertEqual(fields.count(TOKEN), 1, fields)

    def test_applying_the_config_twice_does_not_duplicate_the_token(self):
        """get_client may be handed a config that already went through here (pipeline.BOTO_CONFIG does)."""
        twice = solution.solution_config(solution.solution_config())
        self.assertEqual(twice.user_agent_extra.split().count(TOKEN), 1, twice.user_agent_extra)

    def test_config_may_be_passed_positionally(self):
        """Config is the second positional argument for both helpers (not boto3.client's layout, whose second
        positional is region_name). Locked down because call sites are often copied in."""
        client = solution.get_client("sts", Config(read_timeout=11), session=signed_session())
        self.assertEqual(client.meta.config.read_timeout, 11)
        self.assertEqual(sent_user_agent(client).split().count(TOKEN), 1)
        resource = solution.get_resource("s3", Config(read_timeout=11), session=signed_session())
        cfg = resource.meta.client.meta.config
        self.assertEqual(cfg.read_timeout, 11)
        self.assertEqual(cfg.user_agent_extra.split().count(TOKEN), 1, cfg.user_agent_extra)

    def test_a_positional_region_string_fails_at_the_boundary(self):
        """boto3.client('sts', 'us-west-2') copied over must raise an actionable TypeError at the call
        boundary, not an AttributeError three frames deep in Config.merge."""
        with self.assertRaisesRegex(TypeError, "region_name"):
            solution.get_client("sts", "us-west-2", session=signed_session())

    def test_env_var_overrides_the_config(self):
        """Deployed code (agent, Lambdas) reads the token the CDK app injected."""
        # deliberately not this solution's real version: proves the env value is used rather than
        # coincidentally matching the config
        override = f"AWSSOLUTION/{solution.SOLUTION_ID}/v9.9.9"
        with mock.patch.dict(os.environ, {"USER_AGENT_STRING": override}):
            self.assertEqual(solution.user_agent_string(), override)
            self.assertEqual(sent_user_agent(sts()).split().count(override), 1)
        self.assertEqual(solution.user_agent_string(), TOKEN)

    def test_bedrock_runtime_and_the_review_agent_carry_the_token(self):
        """pipeline.BOTO_CONFIG feeds both the Bedrock client and the Strands BedrockModel (review.py)."""
        os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
        from pidtwin.digitize import pipeline
        self.assertEqual(pipeline.BOTO_CONFIG.user_agent_extra.split().count(TOKEN), 1)
        self.assertEqual(pipeline.BOTO_CONFIG.read_timeout, 900)
        from strands.models.bedrock import BedrockModel
        model = BedrockModel(model_id="us.anthropic.claude-sonnet-5-5", boto_client_config=pipeline.BOTO_CONFIG,
                             boto_session=signed_session())
        fields = sent_user_agent(model.client, "converse", modelId="m",
                                 messages=[{"role": "user", "content": [{"text": "x"}]}]).split()
        self.assertEqual(fields.count(TOKEN), 1, fields)
        self.assertIn("strands-agents", fields)

    def test_dispatch_sheet_lambda_inlines_the_token_from_the_environment(self):
        """DispatchSheet is bundled without pidtwin, so it reads USER_AGENT_STRING itself."""
        override = f"AWSSOLUTION/{solution.SOLUTION_ID}/v9.9.9"
        env = {"AWS_DEFAULT_REGION": "us-east-1", "AGENT_RUNTIME_ARN": "arn", "USER_AGENT_STRING": override,
               "AWS_ACCESS_KEY_ID": "AKIAIOSFODNN7EXAMPLE", "AWS_SECRET_ACCESS_KEY": "test-secret-not-a-real-key"}
        with mock.patch.dict(os.environ, env):
            spec = importlib.util.spec_from_file_location(
                "lambda_dispatch_ua", CDK / "lambda" / "dispatch_sheet" / "index.py")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            ua = sent_user_agent(mod.agentcore, "invoke_agent_runtime",
                                 agentRuntimeArn="arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/x",
                                 runtimeSessionId="s" * 40, payload=b"{}")
        self.assertEqual(ua.split().count(override), 1, ua)


class StackDescriptionTest(unittest.TestCase):
    def test_shape(self):
        """The no-component form is what the application stack deploys."""
        desc = solution.stack_description()
        self.assertEqual(desc, f"{idents()} - {solution.SOLUTION_NAME}. Version {solution.SOLUTION_VERSION}")
        # deployment counting matches on the literal '(SO' prefix
        self.assertTrue(desc.startswith("(SO"), desc)
        # no dangling separator or a stray 'None' where the component would go
        for bad in (" -  ", " - .", "None"):
            self.assertNotIn(bad, desc)
        # '' and whitespace-only mean "no component"
        self.assertEqual(solution.stack_description(""), desc)
        self.assertEqual(solution.stack_description("   "), desc)

    def test_with_a_component(self):
        desc = solution.stack_description("test component")
        self.assertEqual(desc, f"{idents()} - {solution.SOLUTION_NAME} - test component. "
                               f"Version {solution.SOLUTION_VERSION}")

    def test_id_suffix_keeps_one_bare_id_per_install(self):
        supporting = solution.stack_description("network", id_suffix="network")
        self.assertTrue(supporting.startswith(f"{idents('-network')} - "), supporting)
        # no bare id at all, primary or secondary: each would double-count its own solution
        for sid in [solution.SOLUTION_ID, *solution.SECONDARY_IDS]:
            self.assertNotIn(f"({sid})", supporting)
        # '' included: passed through, a supporting stack would silently carry the bare id and double-count
        for bad in ("has space", "under_score", ""):
            with self.assertRaises(ValueError, msg=bad):
                solution.stack_description("x", id_suffix=bad)

    def test_secondary_ids_are_in_the_description_but_not_the_user_agent(self):
        self.assertTrue(solution.SECONDARY_IDS, "solution.json lists no secondary_ids")
        desc = solution.stack_description()
        for sid in solution.SECONDARY_IDS:
            self.assertIn(f"({sid})", desc)
            self.assertNotIn(sid, solution.user_agent_string())

    def test_malformed_secondary_ids_block_a_deploy(self):
        for bad in ("SO0378", ["S0378"], [0], [solution.SOLUTION_ID]):
            with mock.patch.object(solution, "SECONDARY_IDS", bad), self.assertRaises(ValueError, msg=bad):
                solution.stack_description()

    def test_over_the_cloudformation_cap_raises(self):
        """1024 bytes is a hard CloudFormation limit; failing at synth beats failing at deploy, and beats
        silently truncating the version off the end."""
        self.assertLessEqual(len(solution.stack_description("x" * 900).encode()), 1024)
        with self.assertRaisesRegex(ValueError, "1024"):
            solution.stack_description("x" * 1100)

    def test_missing_solution_block_degrades_attribution_but_blocks_a_deploy(self):
        """A broken config must not break a running pipeline, but must never let a stack deploy uncounted."""
        src = Path(solution.__file__).resolve()
        # reproduce this repo's layout inside the temp dir: the module at its real depth, the config at the root
        rel = src.parent.relative_to(REPO)
        with tempfile.TemporaryDirectory() as tmp:
            pkg = Path(tmp) / rel
            pkg.mkdir(parents=True, exist_ok=True)
            shutil.copy(src, pkg / "solution.py")
            (Path(tmp) / solution.CONFIG_FILE).write_text(json.dumps({"some_other_block": {"unrelated": True}}))
            script = (
                "import sys; sys.path.insert(0, sys.argv[1]); import solution\n"
                "assert solution.user_agent_string() == '', solution.user_agent_string()\n"
                "import botocore.config\n"
                # `is None`, not just falsy: with no identity, nothing at all is merged over the caller's config
                "assert solution.solution_config().user_agent_extra is None\n"
                "cfg = solution.solution_config(botocore.config.Config(user_agent_extra='Foreign/1.0', "
                "read_timeout=42))\n"
                "assert cfg.user_agent_extra == 'Foreign/1.0', cfg.user_agent_extra\n"
                "assert cfg.read_timeout == 42, cfg.read_timeout\n"
                "try:\n"
                "    solution.stack_description('c')\n"
                "except ValueError:\n"
                "    print('OK')\n"
                "else:\n"
                "    raise AssertionError('stack_description must refuse to build an uncountable description')\n")
            env = dict(os.environ)
            env.pop("USER_AGENT_STRING", None)
            r = subprocess.run([sys.executable, "-c", script, str(pkg)], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, f"{r.stdout}\n{r.stderr}")
        self.assertIn("OK", r.stdout)
        self.assertIn("no 'solution' block", r.stderr)

    @unittest.skipUnless(shutil.which("node") and (CDK / "node_modules" / ".bin" / "ts-node").exists(),
                         "needs node and cdk/node_modules (npm install in cdk/)")
    def test_the_cdk_app_builds_the_same_description_and_token(self):
        """cdk/lib/solution.ts is a port of solution.py; the CDK app is what actually deploys the stacks."""
        script = (
            "const s = require('./lib/solution');"
            "const bad = ['', 'has space'].map((x) => { try { s.stackDescription('x', x); return x; }"
            " catch { return null; } }).filter((x) => x !== null);"
            "console.log(JSON.stringify({bare: s.stackDescription(), network: s.stackDescription('network', 'network'),"
            " blank: s.stackDescription('   '), token: s.userAgentString(), env: s.userAgentEnvironment(), bad}));")
        r = subprocess.run([str(CDK / "node_modules" / ".bin" / "ts-node"), "-T", "-e", script],
                           cwd=CDK, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        ts = json.loads(r.stdout)
        self.assertEqual(ts["bare"], solution.stack_description())
        self.assertEqual(ts["blank"], solution.stack_description())
        self.assertEqual(ts["network"], solution.stack_description("network", id_suffix="network"))
        self.assertEqual(ts["token"], TOKEN)
        self.assertEqual(ts["env"], {"USER_AGENT_STRING": TOKEN})
        self.assertEqual(ts["bad"], [], "id suffixes the TypeScript port accepted")


class SingleSourceTest(unittest.TestCase):
    def test_the_identity_path_is_fixed(self):
        """The identity must not travel with cdk/config.json: it is release metadata, and a config that omitted
        the block would leave runs unattributed or block a deploy."""
        self.assertEqual(solution.CONFIG_PATH.name, solution.CONFIG_FILE)
        self.assertTrue(solution.CONFIG_PATH.is_absolute())
        self.assertEqual(solution.identity()["id"], solution.SOLUTION_ID)
        self.assertNotIn("solution", json.loads((CDK / "config.json.template").read_text()))

    def test_config_is_the_only_place_the_values_are_written(self):
        """A second literal of these values would go stale at the next release.

        Prose may restate the *format* (the README does, with placeholders); what must not be duplicated
        anywhere is the id, the version, or a built token. The version is the one that drifts, so it is
        checked in documentation too.
        """
        data = json.loads(solution.CONFIG_PATH.read_text())["solution"]
        self.assertEqual((data["id"], data["name"], data["version"]),
                         (solution.SOLUTION_ID, solution.SOLUTION_NAME, solution.SOLUTION_VERSION))
        # the config file, its two readers and this test; every name here is a place a stale value can hide
        skip = {solution.CONFIG_FILE, "solution.py", "solution.ts", "test_solution.py"}
        # git's own file list, so ignored paths (local scratch, cdk.out) are out of scope: this asserts about
        # what ships, not what is lying around
        listed = subprocess.run(["git", "-C", str(REPO), "ls-files", "--cached", "--others", "--exclude-standard"],
                                capture_output=True, text=True)
        if listed.returncode != 0:
            self.skipTest(f"not a git checkout ({listed.stderr.strip()})")
        offenders = []
        for rel in listed.stdout.split("\n"):
            path = REPO / rel
            if not rel or path.name in skip:
                continue
            if path.suffix in {".py", ".json", ".sh", ".yaml", ".ts"}:
                banned = (solution.SOLUTION_ID, *solution.SECONDARY_IDS, solution.SOLUTION_VERSION, "AWSSOLUTION/")
            elif path.suffix == ".md":
                banned = (solution.SOLUTION_VERSION,)
            else:
                continue
            try:
                text = path.read_text()
            except (OSError, UnicodeDecodeError):
                continue
            hits = [b for b in banned if b in text]
            if hits:
                offenders.append(f"{rel} {hits}")
        self.assertFalse(offenders, f"solution id / version / user-agent token hardcoded outside "
                                    f"{solution.CONFIG_FILE} and its readers: {offenders}")


if __name__ == "__main__":
    unittest.main()
