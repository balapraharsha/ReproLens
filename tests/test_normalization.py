"""
Runs entirely locally -- no AWS required. Proves the normalization layer
(YAML/JSON parsing, missing-artifact handling, malformed-YAML handling)
actually works before it ever touches Bedrock.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "lambda"))

from normalize import build_evidence_bundle, ARTIFACT_NAMES  # noqa: E402

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "..", "fixtures")


def load_fixture_bytes(fixture_dir_name: str) -> dict:
    fixture_path = os.path.join(FIXTURES_DIR, fixture_dir_name)
    artifact_bytes = {}
    for name in ARTIFACT_NAMES:
        path = os.path.join(fixture_path, name)
        if os.path.exists(path):
            with open(path, "rb") as f:
                artifact_bytes[name] = f.read()
        else:
            artifact_bytes[name] = None
    return artifact_bytes


def test_fixture_01_all_artifacts_present_and_parsed():
    bundle = build_evidence_bundle("test-01", load_fixture_bytes("01_dataset_config_mismatch"))
    assert bundle["artifacts"]["config.yaml"]["status"] == "available"
    assert bundle["artifacts"]["config.yaml"]["content"]["model"]["num_classes"] == 8
    assert bundle["artifacts"]["dataset_metadata.json"]["content"]["num_classes"] == 9
    assert bundle["known_missing_information"] == []


def test_fixture_04_missing_artifact_is_recorded_not_crashed():
    bundle = build_evidence_bundle("test-04", load_fixture_bytes("04_missing_artifact"))
    assert bundle["artifacts"]["dataset_metadata.json"]["status"] == "missing"
    assert any("dataset_metadata.json" in m for m in bundle["known_missing_information"])
    # The other four artifacts should still parse fine.
    assert bundle["artifacts"]["config.yaml"]["status"] == "available"


def test_malformed_yaml_does_not_crash():
    artifact_bytes = load_fixture_bytes("01_dataset_config_mismatch")
    artifact_bytes["config.yaml"] = b"model:\n  num_classes: [8\n  unclosed: bracket"
    bundle = build_evidence_bundle("test-malformed", artifact_bytes)
    assert bundle["artifacts"]["config.yaml"]["status"] == "parse_error"
    assert any("config.yaml" in m for m in bundle["known_missing_information"])


def test_all_six_fixtures_normalize_without_exceptions():
    for fixture_name in [
        "01_dataset_config_mismatch",
        "02_environment_incompatibility",
        "03_silent_generalization_failure",
        "04_missing_artifact",
        "05_contradictory_evidence",
        "06_healthy_experiment",
    ]:
        bundle = build_evidence_bundle(f"test-{fixture_name}", load_fixture_bytes(fixture_name))
        assert bundle["investigation_id"] == f"test-{fixture_name}"
        assert set(bundle["artifacts"].keys()) == set(ARTIFACT_NAMES)


def test_log_lines_are_numbered_for_citation():
    bundle = build_evidence_bundle("test-03", load_fixture_bytes("03_silent_generalization_failure"))
    log_content = bundle["artifacts"]["train.log"]["content"]
    assert log_content[0]["line"] == 1
    assert "Epoch 10" in log_content[0]["text"]
