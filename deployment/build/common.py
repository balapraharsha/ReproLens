"""Shared helpers: JSON API responses (API Gateway HTTP API v2 proxy format)
and structured CloudWatch logging. Uploaded file CONTENTS are never logged --
only status/timing/IDs, per the security rules in the technical document."""
import json
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("reprolens")

CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
}


def response(status_code: int, body: dict):
    return {
        "statusCode": status_code,
        "headers": CORS_HEADERS,
        "body": json.dumps(body),
    }


def error_response(status_code: int, investigation_id: str, message: str, detail: str = ""):
    """Actionable error body -- never a bare 'Something went wrong.'"""
    return response(
        status_code,
        {
            "error": message,
            "detail": detail,
            "investigation_id": investigation_id,
        },
    )


def log_event(event_name: str, investigation_id: str = "", **fields):
    payload = {"event": event_name, "investigation_id": investigation_id, **fields}
    logger.info(json.dumps(payload))


def parse_body(event) -> dict:
    body = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        import base64

        body = base64.b64decode(body).decode("utf-8")
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return {}


def path_param(event, name):
    params = event.get("pathParameters") or {}
    return params.get(name)
