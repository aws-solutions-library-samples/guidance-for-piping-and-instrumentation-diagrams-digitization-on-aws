"""DispatchSheet: start one AgentCore Runtime session for one sheet and return within seconds.

Step Functions calls this with lambda:invoke.waitForTaskToken and stays paused (no compute billed)
until the agent calls SendTaskSuccess / SendTaskFailure with the token (see cdk/agent/main.py).
Each attempt gets its own session id (execution, sheet, retry count), so a retry after a heartbeat
timeout never lands on a session that is still busy with the earlier attempt.

Event: {"taskToken", "execution", "retryCount", "bucket", "page": {"sheetId", "pageKey", "outputPrefix"},
        "config"}
"""
import hashlib
import json
import logging
import os

import boto3
from botocore.config import Config

log = logging.getLogger()
log.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# bundled without pidtwin, so the solution user-agent token comes straight from the environment the CDK app
# sets (pidtwin/src/pidtwin/solution.py explains the token)
agentcore = boto3.client("bedrock-agentcore", config=Config(user_agent_extra=os.environ.get("USER_AGENT_STRING", "")))
RUNTIME_ARN = os.environ["AGENT_RUNTIME_ARN"]


def lambda_handler(event, context):
    page = event["page"]
    session = hashlib.sha256(f"{event['execution']}|{page['sheetId']}|{event.get('retryCount', 0)}".encode()).hexdigest()
    payload = {"bucket": event["bucket"], "pageKey": page["pageKey"], "outputPrefix": page["outputPrefix"],
               "sheetId": page["sheetId"], "config": event["config"], "taskToken": event["taskToken"]}
    resp = agentcore.invoke_agent_runtime(agentRuntimeArn=RUNTIME_ARN, runtimeSessionId=session,
                                          payload=json.dumps(payload).encode(), contentType="application/json",
                                          accept="application/json")
    body = resp["response"].read().decode()
    try:
        reply = json.loads(body)
    except ValueError:
        reply = None
    if not isinstance(reply, dict) or reply.get("status") != "accepted":
        raise RuntimeError(f"agent did not accept sheet {page['sheetId']}: {body[:500]}")
    log.info("sheet %s dispatched to session %s", page["sheetId"], session)
    return {"dispatched": True, "sessionId": session}
