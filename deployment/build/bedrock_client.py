"""
Calls the OpenAI API directly (api.openai.com) instead of Amazon Bedrock.
Same two hard rules as before:

1. The response MUST be the schema-validated function call. If the model ever
   returns free text instead, this raises BedrockDiagnosisError rather than
   trying to regex a diagnosis out of prose.
2. Every returned diagnosis is re-validated locally against the same JSON
   Schema used to build the tool spec, using the `jsonschema` package.

OPENAI_API_KEY and OPENAI_MODEL are read from the environment.
"""
import json
import os
import time

import requests
import jsonschema

from evidence import DIAGNOSIS_JSON_SCHEMA, SYSTEM_PROMPT, TOOL_NAME, build_explain_system_prompt

OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"


class BedrockDiagnosisError(Exception):
    """Raised whenever the model does not return a schema-valid diagnosis."""


def _api_key():
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY environment variable is not set")
    return key


def _model_id():
    model_id = os.environ.get("OPENAI_MODEL")
    if not model_id:
        raise RuntimeError("OPENAI_MODEL environment variable is not set")
    return model_id


def _headers():
    return {
        "Authorization": f"Bearer {_api_key()}",
        "Content-Type": "application/json",
    }


def _post(payload: dict) -> dict:
    resp = requests.post(OPENAI_API_URL, headers=_headers(), json=payload, timeout=60)
    if resp.status_code != 200:
        raise BedrockDiagnosisError(f"OpenAI API error {resp.status_code}: {resp.text}")
    return resp.json()


def _extract_tool_call(response: dict):
    try:
        message = response["choices"][0]["message"]
    except (KeyError, IndexError) as e:
        raise BedrockDiagnosisError(f"Unexpected OpenAI API response shape: {e}")

    tool_calls = message.get("tool_calls") or []
    for call in tool_calls:
        if call.get("type") == "function" and call["function"].get("name") == TOOL_NAME:
            try:
                return json.loads(call["function"]["arguments"])
            except json.JSONDecodeError as e:
                raise BedrockDiagnosisError(f"Model returned invalid JSON arguments: {e}")

    raise BedrockDiagnosisError(
        "The model did not return a report_experiment_diagnosis function call."
    )


def _validate(diagnosis: dict):
    try:
        jsonschema.validate(instance=diagnosis, schema=DIAGNOSIS_JSON_SCHEMA)
    except jsonschema.ValidationError as e:
        raise BedrockDiagnosisError(f"Diagnosis failed local schema validation: {e.message}")
    return diagnosis


def diagnose(evidence_prompt_text: str) -> dict:
    model_id = _model_id()

    payload = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": evidence_prompt_text},
        ],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": TOOL_NAME,
                    "description": (
                        "Return an evidence-grounded diagnosis of an ML experiment by "
                        "correlating configuration, environment, dataset metadata, "
                        "training logs, and traceback evidence."
                    ),
                    "parameters": DIAGNOSIS_JSON_SCHEMA,
                },
            }
        ],
        "tool_choice": {"type": "function", "function": {"name": TOOL_NAME}},
    }

    start = time.time()
    response = _post(payload)
    latency = time.time() - start

    diagnosis = _extract_tool_call(response)
    diagnosis = _validate(diagnosis)
    diagnosis["_meta"] = {"bedrock_latency_seconds": round(latency, 2), "model_id": model_id}
    return diagnosis


def explain(evidence_prompt_text: str, prior_diagnosis: dict, question: str) -> dict:
    model_id = _model_id()

    user_content = (
        evidence_prompt_text
        + "\n\nYour previous diagnosis was:\n"
        + json.dumps({k: v for k, v in prior_diagnosis.items() if k != "_meta"}, indent=2)
        + f"\n\nUser question: {question or 'Why did you reach this conclusion?'}"
        + "\n\nAnswer using only the evidence bundle and the diagnosis above. "
        "Cite specific evidence items in your answer."
    )

    payload = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": build_explain_system_prompt()},
            {"role": "user", "content": user_content},
        ],
    }

    response = _post(payload)

    try:
        text = response["choices"][0]["message"].get("content") or ""
    except (KeyError, IndexError) as e:
        raise BedrockDiagnosisError(f"Unexpected OpenAI API response shape on explain call: {e}")

    return {
        "explanation": text.strip(),
        "cited_evidence": prior_diagnosis.get("evidence", []),
    }