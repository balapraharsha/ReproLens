"""
Runs locally -- no AWS required. Proves the rule-based checks actually fire
correctly against the real fixtures, since these are facts Bedrock is now
told to trust without re-deriving them -- if these are wrong, the diagnosis
inherits the error.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "lambda"))

from normalize import build_evidence_bundle, ARTIFACT_NAMES  # noqa: E402

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "..", "fixtures")


def _load(fixture_name):
    fixture_path = os.path.join(FIXTURES_DIR, fixture_name)
    artifact_bytes = {}
    for name in ARTIFACT_NAMES:
        path = os.path.join(fixture_path, name)
        artifact_bytes[name] = open(path, "rb").read() if os.path.exists(path) else None
    return build_evidence_bundle(f"test-{fixture_name}", artifact_bytes)


def _finding(bundle, check_name):
    return next(f for f in bundle["deterministic_findings"] if f["check"] == check_name)


def test_fixture_01_class_count_contradiction_detected():
    bundle = _load("01_dataset_config_mismatch")
    finding = _finding(bundle, "class_count_consistency")
    assert finding["result"] == "contradiction"
    values = {e["observed_value"] for e in finding["evidence"]}
    assert values == {"8", "9"}


def test_fixture_06_healthy_class_counts_consistent():
    bundle = _load("06_healthy_experiment")
    finding = _finding(bundle, "class_count_consistency")
    assert finding["result"] == "consistent"


def test_fixture_02_cuda_incompatibility_detected():
    bundle = _load("02_environment_incompatibility")
    finding = _finding(bundle, "cuda_compatibility")
    assert finding["result"] == "contradiction"
    values = {e["observed_value"] for e in finding["evidence"]}
    assert "12.4" in values
    assert "11.8" in values


def test_fixture_03_cuda_check_not_applicable_no_false_positive():
    # Fixture 3 (silent generalization failure) has no environment/CUDA
    # mismatch at all -- the check must report not_applicable, not invent one.
    bundle = _load("03_silent_generalization_failure")
    finding = _finding(bundle, "cuda_compatibility")
    assert finding["result"] == "not_applicable"


def test_fixture_04_missing_artifact_does_not_crash_preflight():
    # dataset_metadata.json is absent in this fixture -- the class-count
    # check must degrade to not_applicable, not raise.
    bundle = _load("04_missing_artifact")
    finding = _finding(bundle, "class_count_consistency")
    assert finding["result"] == "not_applicable"


def test_all_six_fixtures_run_preflight_without_exceptions():
    for name in [
        "01_dataset_config_mismatch", "02_environment_incompatibility",
        "03_silent_generalization_failure", "04_missing_artifact",
        "05_contradictory_evidence", "06_healthy_experiment",
    ]:
        bundle = _load(name)
        assert len(bundle["deterministic_findings"]) == 2
        for finding in bundle["deterministic_findings"]:
            assert finding["result"] in ("contradiction", "consistent", "not_applicable")
