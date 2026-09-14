"""Validated, cwd-independent configuration for the local Flylingual Bridge."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import sys
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

from .neural_calibration import axis_thresholds
from .conversation_settings import DEFAULT_SETTINGS, SettingsError, settings_from_config


ROOT = Path(__file__).resolve().parents[2]
CONFIG_ROOT = ROOT / "Runtime" / "Config"
PROFILE_ROOT = CONFIG_ROOT / "profiles"

_HASH = re.compile(r"^[0-9a-fA-F]{64}$")
_LOOPBACK = {"localhost", "127.0.0.1", "::1"}
_GRAPH_FILES = ("body_ids.npy", "indptr.npy", "targets.npy", "weights.npy")
_SOURCE_FILES = (
    "brain_server_bridge.py",
    "brain_server_analog.py",
    "brain_server_malecns.py",
    "analog_controller.py",
    "neural_visualization.py",
    "visual_threat.py",
    "config/visual_threat_v1.json",
    "analog_motor_decoder.py",
    "game_controller.py",
    "shiu_compatible.py",
    "lif_kernels.py",
    "temporal_motor_decoder.py",
)
_TOP_LEVEL = {"profile", "bridge", "brain", "conversation", "control", "logPath", "neuralFeedback"}
_CHILD_KEYS = {
    "neuralFeedback": {"enabled", "spontaneousEnabled", "cooldownMs", "rawThresholdMv", "filteredThresholdMv", "motorThreshold", "changeThresholdMv", "thresholdVersion", "calibrationEvidence", "calibration",
                       "bodyResponseGraceMs", "bodySpeedThresholdMetersPerSecond", "bodyYawThresholdDegPerSec", "bodyMotorThreshold", "bodyCalibrationEvidence", "bodyYawSign", "bodyThresholdVersion"},
    "bridge": {"host", "tcpPort", "controlPort"},
    "brain": {
        "host", "port", "expectedBackend", "expectedDataset", "expectedConfigHash",
        "expectedGraphHash", "expectedSourceHash", "graph", "config", "python",
        "visualizationAtlas",
    },
    "conversation": {"mode", "model", "intentModel", "intentProvider", "cloudIntentUrl", "localIntentUrl", "localIntentModel", "localIntentFormat", "localIntentCachePrompt", "localIntentResponsesFallback", "intentTimeoutMs", *DEFAULT_SETTINGS},
    "control": {"owner", "maxActionMs", "defaultActionMs", "maxIntentAgeMs", "staleMs", "stopTimeoutMs"},
}

_DEFAULT: dict[str, Any] = {
    "neuralFeedback": {"enabled": True, "spontaneousEnabled": True, "cooldownMs": 4000,
                       "rawThresholdMv": {"forward": None, "turn": None}, "filteredThresholdMv": {"forward": None, "turn": None}, "motorThreshold": {"forward": None, "turn": None},
                       "changeThresholdMv": {"forward": None, "turn": None}, "thresholdVersion": None, "calibrationEvidence": None, "calibration": None,
                       "bodyResponseGraceMs": None, "bodySpeedThresholdMetersPerSecond": None,
                       "bodyYawThresholdDegPerSec": None, "bodyMotorThreshold": None,
                       "bodyCalibrationEvidence": None, "bodyYawSign": None, "bodyThresholdVersion": None},
    "profile": "mac-local",
    "bridge": {"host": "127.0.0.1", "tcpPort": 8770, "controlPort": 8771},
    "brain": {
        "host": "127.0.0.1", "port": 8766,
        "expectedBackend": "MALECNS_EXPERIMENTAL", "expectedDataset": "male-cns:v1.0",
        "expectedConfigHash": None, "expectedGraphHash": None, "expectedSourceHash": None,
        "graph": "artifacts/neuron_checkpoint",
        "config": "Brain/MaleCNS/config/analog_temporal_v1.json",
        "python": sys.executable,
        "visualizationAtlas": None,
    },
    "conversation": {
        "mode": "off", "model": "gpt-live-1", "intentModel": "gpt-5.6-luna",
        "intentProvider": "responses", "cloudIntentUrl": "", "localIntentUrl": "http://127.0.0.1:11435",
        "localIntentModel": "qwen3.5:4b", "localIntentFormat": "compact", "localIntentCachePrompt": True, "localIntentResponsesFallback": False, "intentTimeoutMs": 8000,
        **DEFAULT_SETTINGS,
    },
    "control": {"owner": "observer", "maxActionMs": 8000, "defaultActionMs": 4000,
                "maxIntentAgeMs": 8000, "staleMs": 750, "stopTimeoutMs": 12000},
    "logPath": "artifacts/bridge/events.jsonl",
}


class ConfigError(ValueError):
    """A configuration cannot be used safely before this error is fixed."""


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"{label} not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{label} is not valid JSON: {path}: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{label} must be a JSON object: {path}")
    return data


def _check_known(data: Mapping[str, Any], label: str) -> None:
    unknown = set(data) - _TOP_LEVEL
    if unknown:
        raise ConfigError(f"{label} has unknown key(s): {', '.join(sorted(unknown))}")
    for group, allowed in _CHILD_KEYS.items():
        if group not in data:
            continue
        value = data[group]
        if not isinstance(value, Mapping):
            raise ConfigError(f"{label}.{group} must be an object")
        bad = set(value) - allowed
        if bad:
            raise ConfigError(f"{label}.{group} has unknown key(s): {', '.join(sorted(bad))}")


def _merge(base: dict[str, Any], extra: Mapping[str, Any], label: str) -> None:
    _check_known(extra, label)
    for key, value in extra.items():
        if key in _CHILD_KEYS:
            base[key].update(value)
        else:
            base[key] = value


def _resolve_path(value: str) -> str:
    path = Path(value)
    return str(path if path.is_absolute() else ROOT / path)


def _digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _aggregate_hash(digests: Mapping[str, str]) -> str:
    encoded = json.dumps(dict(digests), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _set_default_expected_hashes(config: dict[str, Any]) -> None:
    """Set provenance expectations without loading the potentially large graph NPY files."""
    brain = config["brain"]
    if brain["expectedConfigHash"] is None:
        config_path = Path(brain["config"])
        if not config_path.is_file():
            raise ConfigError(f"brain config required for expectedConfigHash is missing: {config_path}")
        brain["expectedConfigHash"] = _digest_file(config_path)

    if brain["expectedGraphHash"] is None:
        manifest_path = ROOT / "Brain/MaleCNS/config/analog_handoff_manifest.json"
        manifest = _read_json(manifest_path, "graph manifest")
        graph_files = manifest.get("graphFiles")
        if not isinstance(graph_files, Mapping):
            raise ConfigError(f"graph manifest has no graphFiles object: {manifest_path}")
        digests: dict[str, str] = {}
        for name in _GRAPH_FILES:
            item = graph_files.get(name)
            value = item.get("sha256") if isinstance(item, Mapping) else None
            if not isinstance(value, str) or not _HASH.fullmatch(value):
                raise ConfigError(f"graph manifest has invalid SHA-256 for {name}: {manifest_path}")
            digests[name] = value
        brain["expectedGraphHash"] = _aggregate_hash(digests)

    if brain["expectedSourceHash"] is None:
        source_root = ROOT / "Brain/MaleCNS"
        paths = {name: source_root / name for name in _SOURCE_FILES}
        missing = [str(path) for path in paths.values() if not path.is_file()]
        if missing:
            raise ConfigError("Brain source required for expectedSourceHash is missing: " + ", ".join(missing))
        brain["expectedSourceHash"] = _aggregate_hash({name: _digest_file(path) for name, path in paths.items()})


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _require_port(value: Any, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 65535:
        raise ConfigError(f"{name} must be an integer from 1 through 65535")


def _require_timeout(value: Any, name: str) -> None:
    if not _is_number(value) or not 0 < value <= 60000 or not math.isfinite(value):
        raise ConfigError(f"{name} must be a positive finite number")


def _require_loopback(value: Any, name: str) -> None:
    if not isinstance(value, str) or value.lower() not in _LOOPBACK:
        raise ConfigError(
            f"{name} must be localhost or an IP loopback literal; direct LAN targets are disabled "
            "until authentication and encryption exist. Use an SSH tunnel endpoint instead."
        )


def _validate(config: dict[str, Any]) -> None:
    feedback = config['neuralFeedback']
    for key in ('enabled', 'spontaneousEnabled'):
        if type(feedback[key]) is not bool:
            raise ConfigError('neuralFeedback.' + key + ' must be boolean')
    if type(feedback['cooldownMs']) is not int or not 4000 <= feedback['cooldownMs'] <= 60000:
        raise ConfigError('neuralFeedback.cooldownMs must be an integer from 4000 through 60000')
    try:
        axis_thresholds(feedback)
    except ValueError as error:
        raise ConfigError('neuralFeedback: ' + str(error)) from error
    calibration = feedback.get('calibration')
    if calibration is not None and (type(calibration) is not dict or set(calibration) - {'version', 'artifact', 'artifactSha256', 'sourceHash', 'graphHash', 'configHash'}):
        raise ConfigError('neuralFeedback.calibration must be null or a calibration object')
    for key in ('bodyResponseGraceMs', 'bodySpeedThresholdMetersPerSecond', 'bodyYawThresholdDegPerSec', 'bodyMotorThreshold'):
        value = feedback[key]
        if value is not None and (not _is_number(value) or not math.isfinite(value) or not 0 < value <= 1e6):
            raise ConfigError('neuralFeedback.' + key + ' must be null or a positive finite number')
    if feedback['bodyYawSign'] is not None and (type(feedback['bodyYawSign']) is not int or feedback['bodyYawSign'] not in (-1, 1)):
        raise ConfigError('neuralFeedback.bodyYawSign must be null or -1/+1')
    for key in ('thresholdVersion', 'calibrationEvidence', 'bodyThresholdVersion', 'bodyCalibrationEvidence'):
        value = feedback[key]
        if value is not None and (not isinstance(value, str) or not 0 < len(value) <= 256):
            raise ConfigError('neuralFeedback.' + key + ' must be null or a bounded string')
    if not isinstance(config["profile"], str) or not config["profile"]:
        raise ConfigError("profile must be a non-empty string")
    _require_loopback(config["bridge"]["host"], "bridge.host")
    _require_loopback(config["brain"]["host"], "brain.host")
    _require_port(config["bridge"]["tcpPort"], "bridge.tcpPort")
    _require_port(config["bridge"]["controlPort"], "bridge.controlPort")
    _require_port(config["brain"]["port"], "brain.port")
    if config["bridge"]["tcpPort"] == config["bridge"]["controlPort"]:
        raise ConfigError("bridge.tcpPort and bridge.controlPort must be different")
    for key in ("maxActionMs", "defaultActionMs", "maxIntentAgeMs", "staleMs", "stopTimeoutMs"):
        _require_timeout(config["control"][key], f"control.{key}")
    if not config['control']['defaultActionMs'] <= config['control']['maxActionMs'] <= 8000:
        raise ConfigError('control durations must satisfy defaultActionMs <= maxActionMs <= 8000')
    if config['control']['maxIntentAgeMs'] > 8000:
        raise ConfigError('control.maxIntentAgeMs must not exceed 8000')
    if config['control']['staleMs'] > 750:
        raise ConfigError('control.staleMs must not exceed the 750 ms contract')
    if config['control']['stopTimeoutMs'] > 60000:
        raise ConfigError('control.stopTimeoutMs must not exceed 60000')
    if config["control"]["owner"] not in {"manual", "gpt", "observer"}:
        raise ConfigError("control.owner must be manual, gpt, or observer")
    if config["conversation"]["mode"] not in {"off", "mock", "live", "text"}:
        raise ConfigError("conversation.mode must be off, mock, live, or text")
    if config['conversation']['intentProvider'] not in ('responses', 'ollama', 'llama_cpp', 'vercel'):
        raise ConfigError('conversation.intentProvider must be responses, ollama, llama_cpp or vercel')
    if config['conversation']['intentProvider'] == 'vercel':
        from .cloud_intent import cloud_endpoint
        try:
            cloud_endpoint(config['conversation']['cloudIntentUrl'])
        except ValueError as exc:
            raise ConfigError('conversation.cloudIntentUrl is invalid') from exc
    if config['conversation']['localIntentFormat'] not in ('compact', 'full', 'label'):
        raise ConfigError('conversation.localIntentFormat must be compact, full or label')
    if type(config['conversation']['localIntentCachePrompt']) is not bool:
        raise ConfigError('conversation.localIntentCachePrompt must be boolean')
    if type(config['conversation']['localIntentResponsesFallback']) is not bool:
        raise ConfigError('conversation.localIntentResponsesFallback must be boolean')
    if config['conversation']['intentProvider'] == 'llama_cpp' and config['conversation']['localIntentFormat'] == 'full':
        raise ConfigError('llama_cpp requires compact or label format')
    local_url = config['conversation']['localIntentUrl']
    try:
        endpoint = urlsplit(local_url) if isinstance(local_url, str) else None
        valid_url = (endpoint is not None and not any(c.isspace() for c in local_url)
                     and endpoint.scheme == 'http' and endpoint.hostname in _LOOPBACK
                     and endpoint.port is not None and 1 <= endpoint.port <= 65535
                     and endpoint.path in ('', '/') and not endpoint.query and not endpoint.fragment
                     and endpoint.username is None and endpoint.password is None)
    except ValueError:
        valid_url = False
    if not valid_url:
        raise ConfigError('conversation.localIntentUrl must be an explicit loopback HTTP origin with port')
    timeout = config['conversation']['intentTimeoutMs']
    if type(timeout) is not int or not 100 <= timeout <= 60000:
        raise ConfigError('conversation.intentTimeoutMs must be an integer in 100..60000')
    try:
        config["conversation"].update(settings_from_config(config))
    except SettingsError as exc:
        raise ConfigError("conversation settings are invalid") from exc
    for key in ("expectedConfigHash", "expectedGraphHash", "expectedSourceHash"):
        value = config["brain"][key]
        if value is not None and (not isinstance(value, str) or not _HASH.fullmatch(value)):
            raise ConfigError(f"brain.{key} must be null or a 64-character hexadecimal SHA-256")
    for group, keys in (("brain", ("expectedBackend", "expectedDataset", "graph", "config", "python")),
                        ("conversation", ("model", "intentModel", "localIntentModel"))):
        for key in keys:
            if not isinstance(config[group][key], str) or not config[group][key]:
                raise ConfigError(f"{group}.{key} must be a non-empty string")
    atlas = config["brain"]["visualizationAtlas"]
    if atlas is not None:
        if not isinstance(atlas, str) or not atlas:
            raise ConfigError("brain.visualizationAtlas must be null or a non-empty string")
        atlas_path = Path(atlas)
        if not atlas_path.is_file():
            raise ConfigError(f"brain.visualizationAtlas file is missing: {atlas_path}")
    if not isinstance(config["logPath"], str) or not config["logPath"]:
        raise ConfigError("logPath must be a non-empty string")


def _env_overrides() -> dict[str, Any]:
    result: dict[str, Any] = {}
    values = {
        "FLY_BRAIN_HOST": ("brain", "host", str),
        "FLY_BRAIN_PORT": ("brain", "port", int),
        "FLY_BRAIN_PYTHON": ("brain", "python", str),
        "FLY_BRAIN_GRAPH": ("brain", "graph", str),
        "FLY_CONVERSATION_MODE": ("conversation", "mode", str),
        "FLY_CONVERSATION_LANGUAGE": ("conversation", "language", str),
        "FLY_CONVERSATION_VOICE": ("conversation", "voice", str),
        "FLY_CONVERSATION_PERSONA": ("conversation", "persona", str),
    }
    for env_name, (section, key, convert) in values.items():
        if env_name not in os.environ:
            continue
        raw = os.environ[env_name]
        try:
            value = convert(raw)
        except ValueError as exc:
            raise ConfigError(f"{env_name} has an invalid value") from exc
        result.setdefault(section, {})[key] = value
    return result


def load_config(
    profile: str = "mac-local", local: str | Path | None = None,
    overrides: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Load config with CLI overrides > allowlisted env > local > profile > defaults."""
    if not isinstance(profile, str) or not profile:
        raise ConfigError("profile must be a non-empty string")
    config = copy.deepcopy(_DEFAULT)
    profile_path = PROFILE_ROOT / f"{profile}.json"
    _merge(config, _read_json(profile_path, "profile"), f"profile {profile}")
    config["profile"] = profile

    local_path = Path(local) if local is not None else CONFIG_ROOT / "local.json"
    if not local_path.is_absolute():
        local_path = ROOT / local_path
    if local_path.exists():
        _merge(config, _read_json(local_path, "local config"), f"local config {local_path}")
    elif local is not None:
        raise ConfigError(f"local config not found: {local_path}")

    _merge(config, _env_overrides(), "environment")
    if overrides is not None:
        if not isinstance(overrides, Mapping):
            raise ConfigError("overrides must be an object")
        _merge(config, overrides, "CLI overrides")

    # The selected profile is the identity of this configuration, not a terminal-local override.
    config["profile"] = profile
    for key in ("graph", "config", "python"):
        config["brain"][key] = _resolve_path(config["brain"][key])
    if config["brain"]["visualizationAtlas"] is not None:
        config["brain"]["visualizationAtlas"] = _resolve_path(config["brain"]["visualizationAtlas"])
    config["logPath"] = _resolve_path(config["logPath"])
    _set_default_expected_hashes(config)
    _validate(config)
    return config
