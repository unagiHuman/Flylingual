"""Bounded startup-only artifact verification; no Brain state or per-frame I/O."""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

AXES = ('forward', 'turn')
THRESHOLD_KEYS = ('rawThresholdMv', 'filteredThresholdMv', 'motorThreshold', 'changeThresholdMv')
HASH_KEYS = ('sourceHash', 'graphHash', 'configHash')
ROOT = Path(__file__).resolve().parents[2]


def axis_thresholds(config):
    result = {}
    for key in THRESHOLD_KEYS:
        value = config.get(key)
        if type(value) is dict:
            if set(value) - set(AXES):
                raise ValueError('invalid_neural_threshold_axis')
            values = {axis: value.get(axis) for axis in AXES}
        else:
            values = dict.fromkeys(AXES)  # Legacy scalars never enable claims.
            if value is not None and (type(value) not in (int, float) or not 0 < value <= 1e6):
                raise ValueError('invalid_neural_threshold')
        for item in values.values():
            if item is not None and (type(item) not in (int, float) or not math.isfinite(item) or not 0 < item <= 1e6):
                raise ValueError('invalid_neural_threshold')
        result[key] = values
    return result


class Calibration:
    def __init__(self, config, thresholds):
        self.data = {}
        self.status = 'not_configured'
        calibration = config.get('calibration')
        if not calibration:
            return
        self.status = 'invalid_calibration'
        if type(calibration) is not dict:
            return
        version = calibration.get('version')
        if not isinstance(version, str) or not 0 < len(version) <= 256 or version != config.get('thresholdVersion'):
            self.status = 'version_mismatch'
            return
        for key in (*HASH_KEYS, 'artifactSha256'):
            value = calibration.get(key)
            if type(value) is not str or len(value) != 64 or any(c not in '0123456789abcdefABCDEF' for c in value):
                return
        artifact = calibration.get('artifact')
        if type(artifact) is not str or not artifact or len(artifact) > 4096:
            return
        try:
            path = Path(artifact)
            if not path.is_absolute():
                path = ROOT / path
            with path.open('rb') as stream:
                raw = stream.read(65537)
            if len(raw) > 65536:
                self.status = 'artifact_too_large'
                return
            if hashlib.sha256(raw).hexdigest() != calibration['artifactSha256'].lower():
                self.status = 'artifact_hash_mismatch'
                return
            data = json.loads(raw)
        except (OSError, ValueError, UnicodeError, RecursionError):
            self.status = 'artifact_unavailable_or_invalid'
            return
        if type(data) is not dict or data.get('version') != version:
            self.status = 'artifact_version_mismatch'
            return
        if any(data.get(key) != calibration[key] for key in HASH_KEYS):
            self.status = 'artifact_identity_mismatch'
            return
        if (any(type(config.get(key)) is not dict for key in THRESHOLD_KEYS)
                or data.get('thresholds') != thresholds):
            self.status = 'artifact_threshold_mismatch'
            return
        try:
            if axis_thresholds(data['thresholds']) != thresholds:
                return
        except ValueError:
            return
        self.data = deepcopy(calibration)
        self.status = 'verified'

    def matches(self, identity):
        return bool(self.data) and all(identity.get(key) == self.data[key] for key in HASH_KEYS)

    def summary(self, identity):
        valid = self.matches(identity)
        return {'valid': valid, 'status': self.status if not self.data or valid else 'brain_identity_mismatch',
                'version': self.data.get('version'), 'artifactSha256': self.data.get('artifactSha256')}
