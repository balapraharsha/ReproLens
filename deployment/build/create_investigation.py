import uuid

from common import response, log_event, parse_body
from storage import generate_upload_urls


def lambda_handler(event, context):
    body = parse_body(event)
    experiment_name = body.get("experiment_name", "unnamed_experiment")

    investigation_id = f"INV-{uuid.uuid4().hex[:12]}"
    log_event("investigation_created", investigation_id, experiment_name=experiment_name)

    try:
        upload_urls = generate_upload_urls(investigation_id)
    except RuntimeError as e:
        # Misconfiguration (missing S3_BUCKET env var) -- surface clearly rather
        # than a generic 500 with no explanation.
        return response(500, {"error": "Server misconfiguration", "detail": str(e)})

    return response(
        200,
        {
            "investigation_id": investigation_id,
            "upload_urls": upload_urls,
        },
    )
