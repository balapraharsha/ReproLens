from common import response, error_response, log_event, parse_body, path_param
from normalize import build_evidence_bundle, evidence_bundle_to_prompt_text
from storage import fetch_uploaded_artifacts, get_latest_diagnosis
from bedrock_client import explain, BedrockDiagnosisError


def lambda_handler(event, context):
    investigation_id = path_param(event, "id")
    if not investigation_id:
        return error_response(400, "", "Missing investigation id in path")

    body = parse_body(event)
    question = body.get("question", "")

    # The diagnosis is either resent by the frontend (it already has it in
    # state from the /investigate call -- the cheap path) or looked up from
    # DynamoDB as a fallback.
    prior_diagnosis = body.get("diagnosis") or get_latest_diagnosis(investigation_id)
    if not prior_diagnosis:
        return error_response(
            400, investigation_id,
            "No prior diagnosis found for this investigation.",
            "Run /investigate first, or include the diagnosis in the request body.",
        )

    try:
        artifact_bytes = fetch_uploaded_artifacts(investigation_id)
    except Exception as e:  # noqa: BLE001
        log_event("s3_fetch_failed", investigation_id, error=str(e))
        return error_response(502, investigation_id, "Could not retrieve artifacts for explanation.", str(e))

    bundle = build_evidence_bundle(investigation_id, artifact_bytes)
    prompt_text = evidence_bundle_to_prompt_text(bundle)

    log_event("explain_started", investigation_id)
    try:
        result = explain(prompt_text, prior_diagnosis, question)
    except BedrockDiagnosisError as e:
        log_event("explain_failed", investigation_id, error=str(e))
        return error_response(502, investigation_id, "Amazon Bedrock could not generate an explanation.", str(e))

    log_event("explain_completed", investigation_id)
    return response(200, result)
