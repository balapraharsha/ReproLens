import json
import os
import time
import urllib.request
import urllib.error

import jsonschema

from evidence import (
    DIAGNOSIS_JSON_SCHEMA,
    SYSTEM_PROMPT,
    TOOL_NAME,
    build_explain_system_prompt,
)


class BedrockDiagnosisError(Exception):
    """Compatibility exception used by the existing Lambda handlers."""


def _api_key():
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY environment variable is not set")
    return key


def _model():
    return os.environ.get("OPENAI_MODEL", "gpt-4o")


def _post_openai(payload):
    data = json.dumps(payload).encode("utf-8")

    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {_api_key()}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise BedrockDiagnosisError(
            f"OpenAI API HTTP {exc.code}: {body}"
        ) from exc
    except Exception as exc:
        raise BedrockDiagnosisError(
            f"OpenAI API request failed: {exc}"
        ) from exc


def _diagnosis_tool():
    return {
        "type": "function",
        "name": TOOL_NAME,
        "description": (
            "Return an evidence-grounded diagnosis of an ML experiment "
            "by correlating configuration, environment, dataset metadata, "
            "training logs, and traceback evidence."
        ),
        "parameters": DIAGNOSIS_JSON_SCHEMA,
        "strict": True,
    }


def _extract_function_call(response):
    for item in response.get("output", []):
        if item.get("type") == "function_call":
            if item.get("name") == TOOL_NAME:
                arguments = item.get("arguments")

                if not arguments:
                    raise BedrockDiagnosisError(
                        "OpenAI returned an empty diagnosis function call."
                    )

                try:
                    return json.loads(arguments)
                except json.JSONDecodeError as exc:
                    raise BedrockDiagnosisError(
                        f"OpenAI returned invalid JSON arguments: {exc}"
                    ) from exc

    raise BedrockDiagnosisError(
        f"OpenAI did not return the required {TOOL_NAME} function call."
    )


def _validate(diagnosis):
    try:
        jsonschema.validate(
            instance=diagnosis,
            schema=DIAGNOSIS_JSON_SCHEMA,
        )
    except jsonschema.ValidationError as exc:
        raise BedrockDiagnosisError(
            f"Diagnosis failed local schema validation: {exc.message}"
        ) from exc

    return diagnosis


def diagnose(evidence_prompt_text):
    model = _model()

    payload = {
        "model": model,
        "instructions": SYSTEM_PROMPT,
        "input": evidence_prompt_text,
        "tools": [_diagnosis_tool()],
        "tool_choice": {
            "type": "function",
            "name": TOOL_NAME,
        },
        "parallel_tool_calls": False,
    }

    start = time.time()

    response = _post_openai(payload)

    latency = time.time() - start

    diagnosis = _extract_function_call(response)
    diagnosis = _validate(diagnosis)

    diagnosis["_meta"] = {
        "llm_latency_seconds": round(latency, 2),
        "model_id": model,
        "provider": "openai",
    }

    return diagnosis


def explain(
    evidence_prompt_text,
    prior_diagnosis,
    question,
):
    model = _model()

    user_content = (
        evidence_prompt_text
        + "\n\nYour previous diagnosis was:\n"
        + json.dumps(
            {
                k: v
                for k, v in prior_diagnosis.items()
                if k != "_meta"
            },
            indent=2,
        )
        + f"\n\nUser question: "
        f"{question or 'Why did you reach this conclusion?'}"
        + "\n\nAnswer using only the evidence bundle and the "
        "diagnosis above. Cite specific evidence items in your answer."
    )

    payload = {
        "model": model,
        "instructions": build_explain_system_prompt(),
        "input": user_content,
    }

    response = _post_openai(payload)

    text = response.get("output_text", "")

    return {
        "explanation": text.strip(),
        "cited_evidence": prior_diagnosis.get(
            "evidence",
            [],
        ),
    }