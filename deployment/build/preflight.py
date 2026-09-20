"""
Deterministic, rule-based checks run BEFORE Bedrock sees the evidence bundle.
These establish observable facts (a class-count mismatch is either true or
false -- it doesn't need an LLM to decide that two integers differ). Bedrock
then receives these as pre-verified findings and focuses its reasoning on
the parts that actually require judgment: which hypothesis best explains
the combination of facts, how confident that explanation is, what to check
next.

This is intentionally small and rule-based, not a second AI system. Each
check either fires with a "contradiction"/"consistent" result, or reports
"not_applicable" when it doesn't have enough of the two artifacts it needs
to compare -- it never guesses.
"""
import re


def _get_config_num_classes(config_content):
    if not isinstance(config_content, dict):
        return None
    model = config_content.get("model", {})
    if isinstance(model, dict) and "num_classes" in model:
        return model["num_classes"]
    return config_content.get("num_classes")


def _get_dataset_num_classes(dataset_content):
    if not isinstance(dataset_content, dict):
        return None
    if "num_classes" in dataset_content:
        return dataset_content["num_classes"]
    classes = dataset_content.get("classes")
    if isinstance(classes, list):
        return len(classes)
    return None


def check_class_count_consistency(bundle):
    config = bundle["artifacts"].get("config.yaml", {})
    dataset = bundle["artifacts"].get("dataset_metadata.json", {})
    if config.get("status") != "available" or dataset.get("status") != "available":
        return {"check": "class_count_consistency", "result": "not_applicable",
                "reason": "config.yaml or dataset_metadata.json unavailable"}

    config_n = _get_config_num_classes(config.get("content"))
    dataset_n = _get_dataset_num_classes(dataset.get("content"))
    if config_n is None or dataset_n is None:
        return {"check": "class_count_consistency", "result": "not_applicable",
                "reason": "num_classes not present in one or both artifacts"}

    if config_n == dataset_n:
        return {"check": "class_count_consistency", "result": "consistent",
                "detail": f"Both config.yaml and dataset_metadata.json report {config_n} classes."}

    return {
        "check": "class_count_consistency",
        "result": "contradiction",
        "evidence": [
            {"artifact": "config.yaml", "field_or_location": "model.num_classes",
             "observed_value": str(config_n),
             "significance": "Deterministically verified: model is configured for this many output classes."},
            {"artifact": "dataset_metadata.json", "field_or_location": "num_classes",
             "observed_value": str(dataset_n),
             "significance": "Deterministically verified: dataset reports this many classes -- differs from the model configuration."},
        ],
    }


_CUDA_PATTERN = re.compile(r"CUDA[^0-9]{0,20}(\d{1,2}\.\d)", re.IGNORECASE)
_SPCONV_CU_PATTERN = re.compile(r"spconv-cu(\d{2,3})", re.IGNORECASE)


def _extract_cuda_version(text):
    if not text:
        return None
    match = _CUDA_PATTERN.search(text)
    return match.group(1) if match else None


def _extract_compiled_extension_cuda(requirements_text):
    if not requirements_text:
        return None
    match = _SPCONV_CU_PATTERN.search(requirements_text)
    if not match:
        return None
    digits = match.group(1)  # e.g. "118" -> "11.8"
    return f"{digits[:-1]}.{digits[-1]}"


def check_cuda_compatibility(bundle):
    config = bundle["artifacts"].get("config.yaml", {})
    requirements = bundle["artifacts"].get("requirements.txt", {})
    traceback_artifact = bundle["artifacts"].get("traceback.txt", {})

    config_content = config.get("content") if config.get("status") == "available" else None
    runtime_cuda = None
    if isinstance(config_content, dict):
        env = config_content.get("environment", {})
        runtime_cuda = env.get("cuda") if isinstance(env, dict) else None
        if runtime_cuda is None:
            runtime_cuda = config_content.get("cuda")

    requirements_text = requirements.get("content") if requirements.get("status") == "available" else None
    compiled_cuda = _extract_compiled_extension_cuda(requirements_text)

    if runtime_cuda is None or compiled_cuda is None:
        return {"check": "cuda_compatibility", "result": "not_applicable",
                "reason": "Could not find both a runtime CUDA version and a compiled-extension CUDA version"}

    runtime_cuda_str = str(runtime_cuda)
    if runtime_cuda_str == compiled_cuda:
        return {"check": "cuda_compatibility", "result": "consistent",
                "detail": f"Runtime CUDA {runtime_cuda_str} matches the compiled extension's target CUDA {compiled_cuda}."}

    return {
        "check": "cuda_compatibility",
        "result": "contradiction",
        "evidence": [
            {"artifact": "config.yaml", "field_or_location": "environment.cuda",
             "observed_value": runtime_cuda_str,
             "significance": "Deterministically verified: this is the runtime CUDA version."},
            {"artifact": "requirements.txt", "field_or_location": "spconv package suffix",
             "observed_value": compiled_cuda,
             "significance": "Deterministically verified: the installed extension was compiled against a different CUDA version."},
        ],
    }


ALL_CHECKS = [check_class_count_consistency, check_cuda_compatibility]


def run_preflight_checks(bundle: dict) -> list:
    """Returns a list of finding dicts, each with a 'check' name and
    'result' in {'contradiction', 'consistent', 'not_applicable'}.
    Contradictions include an 'evidence' array in the same shape as the
    diagnosis schema's evidence items, so Bedrock (and the frontend) can
    treat them identically to model-derived evidence."""
    return [check(bundle) for check in ALL_CHECKS]
