import time

from common import response, error_response, log_event, parse_body, path_param
from normalize import build_evidence_bundle, evidence_bundle_to_prompt_text
from storage import fetch_uploaded_artifacts, history_write_safe
from bedrock_client import diagnose, BedrockDiagnosisError


def lambda_handler(event, context):
    investigation_id = path_param(event, "id")
    if not investigation_id:
        return error_response(400, "", "Missing investigation id in path")

    body = parse_body(event)
    experiment_name = body.get("experiment_name", "")

    total_start = time.time()

    # 1) Retrieve whatever was actually uploaded -- missing artifacts are a
    #    valid state, not a failure (rule: "user may upload fewer than five").
    try:
        artifact_bytes = fetch_uploaded_artifacts(investigation_id)
    except Exception as e:  # noqa: BLE001
        log_event("s3_fetch_failed", investigation_id, error=str(e))
        return error_response(
            502, investigation_id,
            "Could not retrieve uploaded artifacts from S3.",
            "Check that the investigation id is correct and artifacts were uploaded.",
        )
    log_event("artifact_validation", investigation_id,
              uploaded=[k for k, v in artifact_bytes.items() if v is not None])

    # 2) Normalize into the structured evidence bundle.
    norm_start = time.time()
    bundle = build_evidence_bundle(investigation_id, artifact_bytes)
    log_event("normalization_completed", investigation_id,
              duration_seconds=round(time.time() - norm_start, 3),
              missing_information=bundle["known_missing_information"])

    # 3) Bedrock investigation. Any failure here returns an explicit error
    #    state -- never a fabricated or partially-parsed diagnosis.
    log_event("bedrock_started", investigation_id)
    prompt_text = evidence_bundle_to_prompt_text(bundle)
    try:
        diagnosis = diagnose(prompt_text)
    except BedrockDiagnosisError as e:
        log_event("bedrock_failed", investigation_id, error=str(e))
        return error_response(
            502, investigation_id,
            "Amazon Bedrock could not complete the diagnosis.",
            f"{e} Check the model configuration or try again.",
        )
    except Exception as e:  # noqa: BLE001 -- covers throttling/access-denied/etc.
        log_event("bedrock_error", investigation_id, error=str(e))
        return error_response(
            502, investigation_id,
            "Amazon Bedrock request failed.",
            "This may be throttling, an access-denied error, or an invalid "
            "model ID -- check CloudWatch logs for this investigation id.",
        )

    log_event("bedrock_completed", investigation_id,
              latency_seconds=diagnosis.get("_meta", {}).get("bedrock_latency_seconds"))
    log_event("diagnosis_validated", investigation_id,
              experiment_status=diagnosis.get("experiment_status"),
              confidence=diagnosis.get("confidence"))

    # Deterministic preflight findings are computed before Bedrock ever runs
    # (see normalize.py / preflight.py) -- attached here, alongside the
    # Bedrock diagnosis, so the frontend can show real rule-based findings
    # rather than inventing "pre-investigation checks" it can't back up.
    diagnosis["_preflight"] = bundle["deterministic_findings"]

    # 4) Async, non-blocking history write. Deliberately after the point
    #    where we already have everything needed to respond to the user.
    history_write_safe(investigation_id, experiment_name, diagnosis)
    log_event("dynamodb_persist_attempted", investigation_id)

    log_event("investigation_total_latency", investigation_id,
              duration_seconds=round(time.time() - total_start, 3))

    return response(200, diagnosis)
