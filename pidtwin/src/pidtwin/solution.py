"""AWS Solution identity: stack descriptions and SDK user-agent attribution.

Two independent reporting mechanisms read the same three values out of the
``solution`` block of ``solution.json`` at the repository root, so cutting a
release means editing one file and nothing else:

  1. **Deployment counting** keys off each deployed CloudFormation stack's
     ``Description``, which must carry the solution id — ``SO`` and digits —
     in parentheses:

         (<id>) (<secondary id>) - <solution name>. Version <version>

     with one parenthesised id per entry in ``secondary_ids`` (optional). The
     secondary ids are reported here only, not in the user agent. The CDK app is TypeScript, so it builds the description with
     ``cdk/lib/solution.ts``, a port of ``stack_description()`` below;
     ``tests/test_solution.py`` checks that the two agree.

  2. **API usage attribution** keys off a suffix appended to the ``User-Agent``
     header of every AWS SDK call:

         AWSSOLUTION/<id>/<version>

     ``get_client()`` / ``get_resource()`` attach it, and every boto3 call site
     in pidtwin, the agent (``cdk/agent/main.py``) and the PrepareInput and
     MergeSheets Lambdas goes through them. Deployed, those run where
     ``solution.json`` is not bundled, so the CDK app injects the token as the
     ``USER_AGENT_STRING`` environment variable, which wins here. The
     DispatchSheet Lambda is bundled without pidtwin and inlines the token
     from ``USER_AGENT_STRING`` directly.

Neither resource tags nor any other mechanism feeds these two pipelines, so
there is deliberately nothing else here.

Why ``user_agent_extra`` and not ``AWS_SDK_UA_APP_ID``: botocore sanitises the
app-id value and rewrites ``/`` to ``-``, so the token would arrive as
``AWSSOLUTION-<id>-<version>`` and match nothing. ``user_agent_extra`` is
passed through verbatim. There is no environment variable or shared-config key
for ``user_agent_extra``, which is why plain ``aws`` CLI invocations cannot be
attributed at all (README, "Solution metrics", lists them).

Failure behaviour is deliberately asymmetric. A missing or malformed config
degrades attribution to "no suffix" — it must never break a running pipeline —
but makes ``stack_description()`` raise, because a stack that deploys with a
description silently lacking the id is counted as zero installs forever.
"""
from __future__ import annotations

import functools
import json
import os
import re
import sys
from pathlib import Path

CONFIG_FILE = "solution.json"

# Deliberately the fixed path at the repository root, not cdk/config.json or
# any per-run config: the solution identity is release metadata, not a
# deployment setting, and a config that happened to omit the block would
# otherwise leave runs unattributed (or, worse, block a deploy). Bundled into
# a Lambda or the agent runtime, this file can sit fewer than four levels deep;
# the path then points at a file that does not exist, which degrades as above.
_HERE = Path(__file__).resolve()
CONFIG_PATH = (_HERE.parents[3] if len(_HERE.parents) > 3 else _HERE.parent) / CONFIG_FILE

# CloudFormation caps a template Description at 1024 bytes.
_DESCRIPTION_MAX_BYTES = 1024


@functools.lru_cache(maxsize=1)
def identity() -> dict:
    """The ``solution`` block of the project config, or {} (warns once)."""
    try:
        block = json.loads(CONFIG_PATH.read_text())["solution"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as e:
        # deployed, the token comes from USER_AGENT_STRING and the file is
        # expected to be absent: nothing to warn about
        if not os.environ.get("USER_AGENT_STRING"):
            print(f"note: no 'solution' block in {CONFIG_PATH} "
                  f"({type(e).__name__}) — AWS calls will not carry the solution "
                  f"user-agent suffix", file=sys.stderr)
        return {}
    if not isinstance(block, dict):
        print(f"note: 'solution' in {CONFIG_PATH} is "
              f"{type(block).__name__}, expected an object", file=sys.stderr)
        return {}
    return {k: v for k, v in block.items() if not k.startswith("_")}


SOLUTION_ID = identity().get("id", "")
SOLUTION_NAME = identity().get("name", "")
SOLUTION_VERSION = identity().get("version", "")
# reported in stack descriptions only, not in the user agent
SECONDARY_IDS = identity().get("secondary_ids", [])


def user_agent_string() -> str:
    """The ``AWSSOLUTION/<id>/<version>`` token, or "" if it cannot be built.

    ``USER_AGENT_STRING`` in the environment wins, so code running somewhere
    the repo is not checked out (the agent runtime and the Lambdas, where the
    CDK app injects it) reports the version of the app that deployed it.
    ``.get`` rather than ``[...]``: an unset variable must fall back to the
    project config, never raise at import time.
    """
    from_env = os.environ.get("USER_AGENT_STRING")
    if from_env:
        return from_env
    if SOLUTION_ID and SOLUTION_VERSION:
        return f"AWSSOLUTION/{SOLUTION_ID}/{SOLUTION_VERSION}"
    return ""


def solution_config(config=None):
    """A botocore ``Config`` carrying the solution user-agent suffix.

    Merges rather than replaces: everything already set on ``config``
    (timeouts, retries, pool size) survives, and an existing
    ``user_agent_extra`` is concatenated rather than clobbered — dropping
    another component's suffix would break whatever reporting depends on it.
    (Foreign suffixes are preserved token-for-token; runs of whitespace
    between them collapse to single spaces.)
    """
    from botocore.config import Config

    if config is not None and not isinstance(config, Config):
        # Catch the classic port-from-boto3.client mistake at the boundary:
        # boto3.client's own second positional argument is region_name, so a
        # copied positional-region call would otherwise die three frames deep
        # in Config.merge with an unhelpful AttributeError.
        raise TypeError(
            f"config must be a botocore Config, got {type(config).__name__}. "
            f"Note boto3.client's second positional argument is region_name — "
            f"pass region_name= (and everything except a Config) by keyword.")

    token = user_agent_string()
    # Idempotent: get_client() may be handed a config that already went through
    # here, and the suffix must appear exactly once — the metrics pipeline
    # matches whole space-delimited tokens.
    parts = (getattr(config, "user_agent_extra", None) or "").split()
    if token and token not in parts:
        parts.append(token)
    # Nothing to say (no id/version anywhere) → set nothing at all, rather than
    # merging an empty override over whatever the caller had.
    ours = Config(user_agent_extra=" ".join(parts)) if parts else Config()
    return ours if config is None else config.merge(ours)


def get_client(service_name: str, config=None, *, session=None, **kwargs):
    """``boto3.client`` with the solution user-agent suffix attached.

    ``config`` may be passed positionally as the second argument. Careful:
    that is NOT ``boto3.client``'s layout — its second positional is
    ``region_name`` — so when porting a call, pass ``region_name=`` and every
    other boto3 argument by keyword (a positional non-Config raises a
    TypeError naming the mistake). One extra keyword: ``session``, an optional
    ``boto3.Session``. Without it the ambient default session is used.
    """
    import boto3

    return (session or boto3).client(
        service_name, config=solution_config(config), **kwargs)


def get_resource(service_name: str, config=None, *, session=None, **kwargs):
    """``boto3.resource`` with the solution user-agent suffix attached."""
    import boto3

    return (session or boto3).resource(
        service_name, config=solution_config(config), **kwargs)


def stack_description(component: str | None = None,
                      id_suffix: str | None = None) -> str:
    """Build a CloudFormation ``Description`` that deployment counting matches.

        (<id>) (<secondary id>) - <solution name>. Version <version>
        (<id>) (<secondary id>) - <solution name> - <component>. Version <version>

    Both forms are counted; the ids in parentheses are the whole signal, one
    per entry in ``secondary_ids`` after the primary. Pass
    ``component`` only to tell several stacks of one solution apart in the
    CloudFormation console — with a single stack the name already says it, and
    a restated summary of the resources just goes stale.

    ``id_suffix`` exists for the multi-stack case: every stack carrying the
    bare id would make one install count as N, so only the stack at the top of
    the dependency graph (the one that consumes the others, since a foundation
    stack can survive an abandoned deploy) omits it, and each supporting stack
    passes its own, applied to every id —
    ``(<id>-network) (<secondary id>-network)`` for the network stack here.

    Standalone templates that are not part of an install must not be given a
    description from here at all, or they inflate the deployment count.
    """
    if not (SOLUTION_ID and SOLUTION_NAME and SOLUTION_VERSION):
        raise ValueError(
            f"cannot build a stack description: the 'solution' block in "
            f"{CONFIG_PATH} must define id, name and version (got "
            f"id={SOLUTION_ID!r}, name={SOLUTION_NAME!r}, "
            f"version={SOLUTION_VERSION!r}). Deploying without the id in the "
            f"description means the stack is never counted as an install.")
    if not isinstance(SECONDARY_IDS, list):
        raise ValueError(f"'secondary_ids' in {CONFIG_PATH} must be a list, "
                         f"got {type(SECONDARY_IDS).__name__}")
    ids = [SOLUTION_ID, *SECONDARY_IDS]
    for sid in ids:
        if not (isinstance(sid, str) and re.fullmatch(r"SO\d+", sid)):
            raise ValueError(
                f"solution id {sid!r} is not of the form SO<digits>; "
                f"deployment counting matches on the literal '(SO' prefix, so "
                f"a differently-shaped id is silently never counted")
    if len(set(ids)) != len(ids):
        raise ValueError(f"solution ids repeat in {CONFIG_PATH}: {ids}")
    suffix = ""
    # `is not None`, not truthiness: id_suffix='' must hit the regex and be
    # rejected — passing it through would silently emit the bare id from a
    # supporting stack, the exact double-count this parameter exists to stop.
    if id_suffix is not None:
        if not re.fullmatch(r"[A-Za-z0-9-]+", id_suffix):
            raise ValueError(f"stack id suffix {id_suffix!r} must match "
                             f"[A-Za-z0-9-]+")
        suffix = f"-{id_suffix}"
    # '' / whitespace-only mean "no component", not an empty label — a blank
    # would otherwise emit a dangling " - ." separator.
    component = (component or "").strip() or None
    subject = f"{SOLUTION_NAME} - {component}" if component else SOLUTION_NAME
    idents = " ".join(f"({sid}{suffix})" for sid in ids)
    desc = f"{idents} - {subject}. Version {SOLUTION_VERSION}"
    size = len(desc.encode("utf-8"))
    if size > _DESCRIPTION_MAX_BYTES:
        what = ("component text" if component
                else f"solution name/version in {CONFIG_PATH}")
        raise ValueError(
            f"stack description is {size} bytes; CloudFormation caps "
            f"Description at {_DESCRIPTION_MAX_BYTES}. Shorten the {what}: "
            f"{desc[:120]}...")
    return desc
