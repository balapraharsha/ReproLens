"""
S3 (artifact storage, pre-signed URLs) and DynamoDB (investigation history)
helpers. No account IDs, bucket names, or table names are hardcoded -- all
come from environment variables set at deploy time (see deployment/deploy.md).

DynamoDB writes here are called only from the async path in
investigate_handler.py -- a failure in this module must never be allowed to
block a diagnosis response reaching the user (see history_write_safe below).
"""
import json
import logging
import os
import time

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger("reprolens.storage")

ARTIFACT_NAMES = [
    "config.yaml",
    "requirements.txt",
    "train.log",
    "dataset_metadata.json",
    "traceback.txt",
]

PRESIGNED_URL_EXPIRY_SECONDS = 900  # 15 minutes -- short-lived by design


def _bucket():
    bucket = os.environ.get("S3_BUCKET")
    if not bucket:
        raise RuntimeError("S3_BUCKET environment variable is not set")
    return bucket


def _table_name():
    table = os.environ.get("DYNAMODB_TABLE")
    if not table:
        raise RuntimeError("DYNAMODB_TABLE environment variable is not set")
    return table


def s3_key(investigation_id: str, artifact_name: str) -> str:
    return f"experiments/{investigation_id}/{artifact_name}"


def generate_upload_urls(investigation_id: str) -> dict:
    """Pre-signed PUT URLs for all 5 artifact slots. The caller may upload
    fewer than five -- missing artifacts are handled downstream in normalize.py."""
    s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION"))
    bucket = _bucket()
    urls = {}
    for name in ARTIFACT_NAMES:
        urls[name] = s3.generate_presigned_url(
            "put_object",
            Params={"Bucket": bucket, "Key": s3_key(investigation_id, name)},
            ExpiresIn=PRESIGNED_URL_EXPIRY_SECONDS,
        )
    return urls


def fetch_uploaded_artifacts(investigation_id: str) -> dict:
    """Returns {artifact_name: bytes_or_None} -- None means that artifact
    was never uploaded, which is a valid state, not an error."""
    s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION"))
    bucket = _bucket()
    result = {}
    for name in ARTIFACT_NAMES:
        try:
            obj = s3.get_object(Bucket=bucket, Key=s3_key(investigation_id, name))
            result[name] = obj["Body"].read()
        except ClientError as e:
            if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
                result[name] = None
            else:
                raise
    return result


def history_write_safe(investigation_id: str, experiment_name: str, diagnosis: dict):
    """Async, best-effort write to DynamoDB. Deliberately swallows all
    exceptions and only logs them -- per the locked architecture, a history
    persistence failure must never fail the user-facing diagnosis response.
    This function must only ever be called AFTER the diagnosis has already
    been returned/queued to the caller, never awaited on the critical path."""
    try:
        table = boto3.resource("dynamodb").Table(_table_name())
        table.put_item(
            Item={
                "investigation_id": investigation_id,
                "created_at": str(int(time.time())),
                "experiment_name": experiment_name or "unnamed_experiment",
                "primary_diagnosis": diagnosis.get("primary_diagnosis", ""),
                "confidence": diagnosis.get("confidence", ""),
                "experiment_status": diagnosis.get("experiment_status", ""),
                "diagnosis_json": json.dumps({k: v for k, v in diagnosis.items() if k != "_meta"}),
            }
        )
    except Exception as e:  # noqa: BLE001 -- intentionally broad, see docstring
        logger.error("dynamodb_persist_failed investigation_id=%s error=%s", investigation_id, e)


def get_latest_diagnosis(investigation_id: str):
    """Fallback lookup used by explain_handler.py if the frontend doesn't
    resend the diagnosis it already has in state. Returns None if not found
    or if DynamoDB is unavailable -- this must never raise, since a missing
    history record just means the explain endpoint asks the client to resend
    the diagnosis instead (see explain_handler.py)."""
    try:
        table = boto3.resource("dynamodb").Table(_table_name())
        result = table.query(
            KeyConditionExpression=boto3.dynamodb.conditions.Key("investigation_id").eq(investigation_id),
            ScanIndexForward=False,
            Limit=1,
        )
        items = result.get("Items", [])
        if not items:
            return None
        return json.loads(items[0]["diagnosis_json"])
    except Exception as e:  # noqa: BLE001
        logger.error("dynamodb_lookup_failed investigation_id=%s error=%s", investigation_id, e)
        return None


def list_history(limit: int = 25):
    table = boto3.resource("dynamodb").Table(_table_name())
    response = table.scan(Limit=limit)
    return response.get("Items", [])
