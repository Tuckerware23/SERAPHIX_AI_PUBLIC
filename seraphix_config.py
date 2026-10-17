"""Public-review configuration; defaults contain no project-specific canon."""
import json
import os
from pathlib import Path

BASE = Path(__file__).resolve().parent
DEFAULTS = {
    "entities": [],
    "retrieval_rules": [],
    "identity_rules": [],
    "unsupported_patterns": [],
}

def load_settings(path=None):
    """Read an explicitly selected private config; never auto-load the example."""
    selected = path if path is not None else os.environ.get("SERAPHIX_CONFIG")
    if selected is None:
        return dict(DEFAULTS)
    config_path = Path(selected).expanduser()
    if not config_path.is_absolute():
        config_path = BASE / config_path
    data = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) - set(DEFAULTS):
        raise ValueError("Invalid configuration keys")
    result = dict(DEFAULTS)
    result.update(data)
    if not isinstance(result["entities"], list) or not all(
            isinstance(x, str) and x.strip() for x in result["entities"]):
        raise ValueError("Invalid entities")
    for key in ("retrieval_rules", "identity_rules"):
        rules = result[key]
        required = {"question_terms", "source_pattern"}
        if key == "identity_rules":
            required.add("answer")
        if not isinstance(rules, list):
            raise ValueError("Invalid configuration rules")
        for rule in rules:
            if not isinstance(rule, dict) or set(rule) != required:
                raise ValueError("Invalid configuration rule")
            if not isinstance(rule["question_terms"], list) or not rule["question_terms"] or not all(
                    isinstance(x, str) and x.strip() for x in rule["question_terms"]):
                raise ValueError("Invalid question terms")
            if not isinstance(rule["source_pattern"], str) or not rule["source_pattern"]:
                raise ValueError("Invalid source pattern")
            if key == "identity_rules" and (
                    not isinstance(rule["answer"], str) or not rule["answer"].strip()):
                raise ValueError("Invalid configured answer")
    patterns = result["unsupported_patterns"]
    if not isinstance(patterns, list) or not all(isinstance(x, str) and x for x in patterns):
        raise ValueError("Invalid unsupported patterns")
    # Patterns are trusted local configuration, not model-provided input.
    import re
    for key in ("retrieval_rules", "identity_rules"):
        for rule in result[key]:
            re.compile(rule["source_pattern"])
    for pattern in patterns:
        re.compile(pattern)
    return result

def configured_path(variable, default):
    """Resolve relative settings against this release directory."""
    value = Path(os.environ.get(variable, str(default))).expanduser()
    return value.resolve() if value.is_absolute() else (BASE / value).resolve()

SETTINGS = load_settings()
WORKSPACE_ROOT = configured_path("SERAPHIX_WORKSPACE_ROOT", "Assistant_Workspace")
CANON_FILE = configured_path("SERAPHIX_CANON_FILE", "Memory/Canon/reference.md")
MODEL = os.environ.get("SERAPHIX_MODEL", "qwen3:14b")
