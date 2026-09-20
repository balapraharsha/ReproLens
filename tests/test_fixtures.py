"""
UNLIKE the other test files, these tests make REAL Bedrock calls and are
the actual T01/T02/T03/T07/T09 acceptance tests from the technical document.
They are automatically skipped unless BEDROCK_MODEL_ID and AWS_REGION are
set and valid AWS credentials are available -- run them yourself after your
Day-0 smoke test, from an environment with real AWS access (this sandbox
cannot reach *.amazonaws.com, so these were written but not executed here).

Run with:
    export AWS_REGION=...
    export BEDROCK_MODEL_ID=...
    pytest tests/test_fixtures.py -v -s
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "lambda"))

pytestmark = pytest.mark.skipif(
    not (os.environ.get("BEDROCK_MODEL_ID") and os.environ.get("AWS_REGION")),
    reason="Set BEDROCK_MODEL_ID and AWS_REGION with valid AWS credentials to run live Bedrock tests.",
)

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "..", "fixtures")


def _load(fixture_name):
    from normalize import build_evidence_bundle, evidence_bundle_to_prompt_text, ARTIFACT_NAMES

    fixture_path = os.path.join(FIXTURES_DIR, fixture_name)
    artifact_bytes = {}
    for name in ARTIFACT_NAMES:
        path = os.path.join(fixture_path, name)
        artifact_bytes[name] = open(path, "rb").read() if os.path.exists(path) else None
    bundle = build_evidence_bundle(f"test-{fixture_name}", artifact_bytes)
    return evidence_bundle_to_prompt_text(bundle)


def test_fixture_01_dataset_config_mismatch():
    from bedrock_client import diagnose

    diagnosis = diagnose(_load("01_dataset_config_mismatch"))
    print(json.dumps(diagnosis, indent=2))
    assert diagnosis["experiment_status"] in ("suspicious", "degraded", "failed")
    assert any("config.yaml" in e["artifact"] for e in diagnosis["evidence"])
    assert any("dataset_metadata.json" in e["artifact"] for e in diagnosis["evidence"])


def test_fixture_02_environment_incompatibility():
    from bedrock_client import diagnose

    diagnosis = diagnose(_load("02_environment_incompatibility"))
    print(json.dumps(diagnosis, indent=2))
    assert diagnosis["confidence"] in ("high", "medium")
    assert "cuda" in diagnosis["primary_diagnosis"].lower() or "compat" in diagnosis["primary_diagnosis"].lower()


def test_fixture_03_silent_generalization_failure_hero_scenario():
    from bedrock_client import diagnose

    diagnosis = diagnose(_load("03_silent_generalization_failure"))
    print(json.dumps(diagnosis, indent=2))
    # This is the fixture that must NOT claim unwarranted certainty.
    assert diagnosis["confidence"] != "high", (
        "Hero fixture should not be diagnosed with high confidence -- the "
        "evidence only suggests a generalization problem, it doesn't prove one."
    )
    assert len(diagnosis["competing_hypotheses"]) >= 2


def test_fixture_06_healthy_experiment_is_not_over_diagnosed():
    from bedrock_client import diagnose

    diagnosis = diagnose(_load("06_healthy_experiment"))
    print(json.dumps(diagnosis, indent=2))
    assert diagnosis["experiment_status"] == "healthy", (
        "ReproLens must not manufacture a problem for a genuinely healthy experiment."
    )
