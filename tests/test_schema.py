"""
Validates the diagnosis JSON Schema itself, and confirms both a well-formed
and a deliberately-broken sample diagnosis behave as expected against it.
This is what T06 (schema validity) in the technical document refers to --
it does not require a live Bedrock call to be meaningful.
"""
import json
import os

import jsonschema
import pytest

SCHEMA_PATH = os.path.join(
    os.path.dirname(__file__), "..", "backend", "schemas", "diagnosis_schema.json"
)

with open(SCHEMA_PATH) as f:
    SCHEMA = json.load(f)


VALID_SAMPLE = {
    "experiment_status": "suspicious",
    "primary_diagnosis": "Dataset / configuration mismatch",
    "confidence": "high",
    "severity": "high",
    "competing_hypotheses": [
        {"hypothesis": "Dataset/config mismatch", "confidence": "high", "reason": "Directly contradicted by two artifacts."}
    ],
    "evidence": [
        {
            "artifact": "config.yaml",
            "field_or_location": "model.num_classes",
            "observed_value": "8",
            "significance": "Model expects eight output classes.",
        }
    ],
    "recommended_checks": ["Verify label mapping"],
    "missing_information": [],
}


def test_schema_itself_is_valid_json_schema():
    jsonschema.Draft7Validator.check_schema(SCHEMA)


def test_valid_sample_passes():
    jsonschema.validate(instance=VALID_SAMPLE, schema=SCHEMA)  # should not raise


def test_missing_required_field_is_rejected():
    broken = dict(VALID_SAMPLE)
    del broken["evidence"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=broken, schema=SCHEMA)


def test_invalid_enum_value_is_rejected():
    broken = dict(VALID_SAMPLE)
    broken["confidence"] = "extremely high"  # not in the enum
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=broken, schema=SCHEMA)


def test_additional_properties_are_rejected():
    broken = dict(VALID_SAMPLE)
    broken["made_up_field"] = "should not be allowed"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=broken, schema=SCHEMA)
