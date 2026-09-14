"""Read-only, bounded analysis of selected MaleCNS readouts.

No controller, RNG, network, or neural array reference is retained. Brain time is
the end of the integration window (AnalogController.step); wall time is supplied
by the Bridge's monotonic clock. The first applied frame is conservatively not
used in onset comparisons even though today's worker applies before step().
"""
from collections import deque
from copy import deepcopy
import math


ACTIONS = ('STOP', 'FORWARD', 'TURN_R', 'TURN_L', 'FORWARD_R', 'FORWARD_L')
IDENTITY_KEYS = ('instanceId', 'sessionId', 'backendId', 'datasetId', 'sourceHash', 'graphHash', 'configHash')
RATE_KEYS = ('DNa02_R_Hz', 'DNa02_L_Hz', 'DNg100_L_Hz', 'DNg100_R_Hz',
             'DNp09_L_Hz', 'DNp09_R_Hz', 'DNp09_Hz', 'DNa02Difference_Hz')


def number(value):
    return float(value) if type(value) in (int, float) and -1e12 <= value <= 1e12 and math.isfinite(value) else None


def integer(value):
    return type(value) is int and 0 <= value <= 2**63 - 1


def mapping(value):
    return value if type(value) is dict else {}


def text(value):
    return value if type(value) is str and 0 < len(value) <= 256 else None


class NeuralResponseAnalyzer:
    def __init__(self, config=None):
        config = mapping(config)
        self.enabled = config.get('enabled', True) is True
        self.stale_ms = number(config.get('staleMs', 750))
        if self.stale_ms is None or not 0 < self.stale_ms <= 60000:
            raise ValueError('invalid_neural_stale_ms')
        self.threshold_version = text(config.get('thresholdVersion'))
        self.calibration_evidence = text(config.get('calibrationEvidence'))
        self.thresholds = {}
        for key in ('rawThresholdMv', 'filteredThresholdMv', 'motorThreshold', 'changeThresholdMv'):
            value = config.get(key)
            if value is not None and (number(value) is None or value <= 0):
                raise ValueError('invalid_neural_threshold')
            self.thresholds[key] = number(value) if self.threshold_version and self.calibration_evidence else None
        self.body_threshold_version = text(config.get('bodyThresholdVersion'))
        self.body_calibration_evidence = text(config.get('bodyCalibrationEvidence'))
        self.body_thresholds = {}
        for key in ('bodyResponseGraceMs', 'bodySpeedThresholdMetersPerSecond',
                    'bodyYawThresholdDegPerSec', 'bodyMotorThreshold'):
            value = config.get(key)
            if value is not None and (number(value) is None or value <= 0):
                raise ValueError('invalid_body_response_threshold')
            self.body_thresholds[key] = number(value)
        self.body_yaw_sign = number(config.get('bodyYawSign'))
        if config.get('bodyYawSign') is not None and self.body_yaw_sign not in (-1., 1.):
            raise ValueError('invalid_body_yaw_sign')
        self._serial = 0
        self.reset()

    def reset(self):
        self._identity = None
        self._epoch = None
        self._generation = None
        self._sequence = None
        self._brain_end = None
        self._received_ms = None
        self._age_at_receive = None
        self._ring = deque(maxlen=512)
        self._episode = None
        self._references = {}
        self._event = None
        self._last_action = None
        self._mode = None
        self._body_stability = None

    @property
    def buffered_frames(self):
        return len(self._ring)

    def _unavailable(self, reason, epoch, generation, sequence=None):
        self._serial += 1
        self._event = {'schemaVersion': 1, 'eventId': 'neural-%d' % self._serial,
                       'eventType': 'OBSERVATION_UNAVAILABLE', 'controlEpoch': epoch,
                       'conversationGeneration': generation, 'sequence': sequence,
                       'identity': deepcopy(self._identity), 'fresh': False, 'current': None,
                       'comparison': {'eligible': False, 'reason': reason},
                       'currentCurve': [], 'previousCurve': [], 'allowedClaims': ['observation_unavailable'],
                       'causalStatus': 'unknown', 'cause': 'unknown', 'residualLayer': 'unresolved',
                       'bodyMovementVerified': False, 'suppressionReason': reason,
                       'priority': 0, 'expiresAt': None}
        if self._episode:
            self._episode['invalid'] = reason
            self._episode['presentMs'] = 0.
            self._episode['residualMs'] = 0.
        self._body_stability = None
        return deepcopy(self._event)

    def _finish_episode(self):
        episode = self._episode
        if (episode and episode['complete'] and not episode['invalid'] and not episode['continued']
                and episode['initialActionKnown'] and all(episode['identity'].values())):
            self._references[episode['action']] = deepcopy(episode)
        self._episode = None

    @staticmethod
    def _compatible_identity(identity):
        return all(identity.values()) and all(len(identity[key]) == 64 and all(c in '0123456789abcdefABCDEF' for c in identity[key])
                                             for key in ('sourceHash', 'graphHash', 'configHash'))

    def observe(self, frame, *, identity, epoch, generation, received_ms, age_ms,
                request=None, body=None, inhibited=False):
        if not self.enabled:
            return None
        if not integer(epoch) or not integer(generation):
            return self._unavailable('invalid_generation', None, None)
        identity = {key: text(mapping(identity).get(key)) for key in IDENTITY_KEYS}
        if self._epoch is not None and (epoch < self._epoch or generation < self._generation):
            return self._unavailable('old_generation', self._epoch, self._generation)
        if self._identity is not None and identity != self._identity:
            return self._unavailable('identity_changed_reset_required', epoch, generation)
        if self._epoch is not None and (epoch != self._epoch or generation != self._generation):
            self.reset()
        self._epoch, self._generation, self._identity = epoch, generation, identity
        frame = mapping(frame)
        metadata = mapping(frame.get('metadata'))
        mode = text(metadata.get('mode'))
        if mode != 'LIVE' or self._mode is not None and self._mode != mode:
            return self._unavailable('unverified_mode', epoch, generation)
        self._mode = mode
        for key in IDENTITY_KEYS:
            if key in metadata and metadata[key] != identity[key]:
                return self._unavailable('frame_identity_mismatch', epoch, generation)
        if not identity['instanceId'] or not identity['sessionId']:
            return self._unavailable('missing_session_identity', epoch, generation)
        sequence = frame.get('sequence')
        if not integer(sequence) or self._sequence is not None and sequence <= self._sequence:
            return self._unavailable('non_new_sequence', epoch, generation, self._sequence)
        end, window, received, age = map(number, (frame.get('brainTimeMs'), frame.get('windowMs'), received_ms, age_ms))
        if (end is None or window is None or not 0 < window <= 1000 or end < window
                or received is None or age is None or age < 0 or age > self.stale_ms
                or self._received_ms is not None and received < self._received_ms):
            return self._unavailable('invalid_or_stale_time', epoch, generation, sequence)
        if self._brain_end is not None and end <= self._brain_end:
            return self._unavailable('non_new_brain_time', epoch, generation, sequence)
        action = frame.get('requestedAction')
        if action not in ACTIONS:
            return self._unavailable('unknown_action', epoch, generation, sequence)
        gap = self._brain_end is not None and (
            sequence != self._sequence + 1 or abs(end - window - self._brain_end) > 1e-6)
        applied = frame.get('appliedRequestId')
        if applied is not None and not integer(applied):
            return self._unavailable('invalid_applied_request', epoch, generation, sequence)
        request = mapping(request)
        expected = request.get('requestId')
        if expected is not None and (not integer(expected) or request.get('action') not in ACTIONS):
            return self._unavailable('invalid_request_context', epoch, generation, sequence)
        if applied is not None and expected is not None and (applied != expected or action != request['action']):
            return self._unavailable('request_mismatch', epoch, generation, sequence)
        if (self._episode and expected == self._episode['requestId']
                and request.get('action') != self._episode['action']):
            return self._unavailable('request_mismatch', epoch, generation, sequence)
        if self._episode and expected is not None and expected != self._episode['requestId']:
            self._finish_episode()
        applied_now = applied is not None and (not self._episode or self._episode['requestId'] != applied)
        if applied_now:
            self._finish_episode()
            self._episode = {'requestId': applied, 'action': action, 'start': end,
                             'continued': self._last_action == action,
                             'initialActionKnown': self._last_action is not None,
                             'invalid': None, 'samples': [], 'duration': 0., 'complete': False,
                             'sequenceStart': sequence, 'reference': deepcopy(self._references.get(action)),
                             'identity': deepcopy(identity), 'onsetRawMs': None, 'onsetMotorMs': None,
                             'presentMs': 0., 'residualMs': 0., 'residualLayer': 'unresolved'}
            sent = number(request.get('sentMonotonicMs'))
            self._episode['applicationLatencyMs'] = received-sent if sent is not None and 0 <= sent <= received and expected == applied else None
            self._episode['appliedReceivedMonotonicMs'] = received
            self._body_stability = None
            # Strip recursive references from saved aggregates to keep memory bounded.
            if self._episode['reference']:
                self._episode['reference']['reference'] = None
        elif self._episode and action != self._episode['action']:
            self._finish_episode()
        if gap and self._episode:
            self._episode['invalid'] = 'missing_interval'
        raw, motor = mapping(frame.get('raw')), mapping(frame.get('motor'))
        filtered = raw.get('filteredRaw')
        filtered = filtered if type(filtered) in (list, tuple) and len(filtered) == 2 else (None, None)
        sample = {'brainStartMs': end - window, 'brainEndMs': end, 'windowMs': window,
                  'requestId': self._episode['requestId'] if self._episode else None,
                  'sequence': sequence, 'raw': {'forward': number(raw.get('forward_raw')), 'turn': number(raw.get('turn_raw'))},
                  'filteredRaw': {'forward': number(filtered[0]), 'turn': number(filtered[1])},
                  'motor': {'forward': number(motor.get('forward')), 'turn': number(motor.get('turn'))},
                  'populationDeltaMv': {axis: {side: number(mapping(mapping(raw.get('populationDeltaMv')).get(axis)).get(side))
                                               for side in ('L', 'R')} for axis in ('forward', 'turn')},
                  'readoutHz': {key: number(mapping(frame.get('brain')).get(key)) for key in RATE_KEYS},
                  'stepWallTimeMs': number(mapping(frame.get('performance')).get('stepWallTimeMs'))}
        self._sequence, self._brain_end = sequence, end
        self._received_ms, self._age_at_receive = received, age
        self._ring.append(sample)
        while self._ring and end - self._ring[0]['brainStartMs'] > 10000:
            self._ring.popleft()
        self._last_action = action
        valid_raw = all(value is not None for value in sample['raw'].values())
        if self._episode:
            self._episode['presentMs'] = (self._episode['presentMs'] + window
                if not applied_now and not gap and self._present(sample['raw'], 'rawThresholdMv', action) else 0.)
            layer = self._residual(sample) if action == 'STOP' else 'unresolved'
            self._episode['residualMs'] = (self._episode['residualMs'] + window
                if not applied_now and not gap and layer != 'unresolved' and layer == self._episode['residualLayer'] else 0.)
            self._episode['residualLayer'] = layer
        if self._episode and not applied_now and not self._episode['complete']:
            episode = self._episode
            if not valid_raw:
                episode['invalid'] = 'missing_raw'
            if len(episode['samples']) >= 512:
                episode['invalid'] = 'sample_limit'
            elif end - episode['start'] <= 200 + 1e-6:
                episode['samples'].append(sample)
                episode['duration'] += window
                episode['complete'] = abs(episode['duration'] - 200) < 1e-6
                relative = end - episode['start']
                if episode['onsetRawMs'] is None and self._present(sample['raw'], 'rawThresholdMv', action):
                    episode['onsetRawMs'] = {'windowStartMs': relative-window, 'windowEndMs': relative}
                if episode['onsetMotorMs'] is None and self._present(sample['motor'], 'motorThreshold', action):
                    episode['onsetMotorMs'] = {'windowStartMs': relative-window, 'windowEndMs': relative}
            elif not episode['complete']:
                episode['invalid'] = 'unaligned_window'
        self._serial += 1
        current_request = self._episode['requestId'] if self._episode else None
        applied_confirmed = current_request is not None and (expected is None or expected == current_request)
        claims = ['selected_readout_values'] if valid_raw else []
        if applied_confirmed:
            claims.append('stimulus_applied')
        event_type = 'OBSERVATION_MEASURED' if valid_raw else 'OBSERVATION_UNAVAILABLE'
        residual = 'unresolved'
        if valid_raw and applied_confirmed and self._episode['presentMs'] >= 100:
            event_type = 'RESPONSE_PRESENT'
            claims.append('selected_direction_response')
        if valid_raw and applied_confirmed and action == 'STOP':
            residual = self._residual(sample)
            if residual != 'unresolved' and self._episode['residualMs'] >= 100:
                event_type = 'POST_STOP_RESIDUAL'
                claims.append('post_stop_' + residual)
        comparison = self._comparison()
        if valid_raw and comparison.get('changed'):
            event_type = 'RESPONSE_CHANGED'
            claims.append('response_changed_observed_only')
        if inhibited:
            claims = []
        current = {**sample, 'requestedAction': request.get('action'), 'observedAction': action,
                   'requestedRequestId': expected, 'appliedRequestId': current_request,
                   'stimulusApplied': applied_confirmed, 'requestContinuation': bool(self._episode and self._episode['continued']),
                   'applicationLatencyMs': self._episode['applicationLatencyMs'] if self._episode else None}
        body_result = self._body(body, sequence, identity, epoch, generation, inhibited)
        event_id = 'neural-%d' % self._serial
        self._event = {'schemaVersion': 1, 'eventId': event_id, 'eventType': event_type,
                       'identity': deepcopy(identity), 'mode': text(metadata.get('mode')),
                       'controlEpoch': epoch, 'conversationGeneration': generation, 'sequence': sequence,
                       'fresh': True, 'ageMs': age, 'receivedMonotonicMs': received,
                       'expiresAt': received + self.stale_ms - age, 'current': current,
                       'comparison': comparison, 'currentCurve': self._curve(self._episode),
                       'previousCurve': self._curve(self._episode['reference']) if self._episode else [],
                       'body': body_result, 'bodyMovementVerified': False, 'outputInhibited': bool(inhibited),
                       'residualLayer': residual, 'allowedClaims': claims,
                       'causalStatus': 'observed_difference_only' if comparison.get('eligible') else 'unknown',
                       'cause': 'stimulus_variability_not_excluded',
                       'thresholdVersion': self.threshold_version, 'priority': 0,
                       'dedupKey': '%s:%s:%s:%s:%s' % (identity['sessionId'], epoch, generation, current_request, event_type),
                       'suppressionReason': 'output_inhibited' if inhibited else ('missing_raw' if not valid_raw else None)}
        return deepcopy(self._event)

    def _present(self, values, key, action):
        threshold = self.thresholds[key]
        if threshold is None or any(value is None for value in values.values()) or action == 'STOP':
            return False
        if action == 'FORWARD':
            return values['forward'] > threshold
        sign = -1 if action in ('TURN_L', 'FORWARD_L') else 1
        return sign * values['turn'] > threshold and (not action.startswith('FORWARD_') or values['forward'] > threshold)

    def _residual(self, sample):
        keys = ('rawThresholdMv', 'filteredThresholdMv', 'motorThreshold')
        if any(self.thresholds[key] is None for key in keys):
            return 'unresolved'
        if any(value is None for group in ('raw', 'filteredRaw', 'motor') for value in sample[group].values()):
            return 'unresolved'
        raw = any(abs(value) > self.thresholds['rawThresholdMv'] for value in sample['raw'].values())
        decoder = (any(abs(value) > self.thresholds['filteredThresholdMv'] for value in sample['filteredRaw'].values())
                   or any(abs(value) > self.thresholds['motorThreshold'] for value in sample['motor'].values()))
        return 'both' if raw and decoder else 'selected_neural_readout' if raw else 'decoder' if decoder else 'unresolved'

    def _comparison(self):
        episode = self._episode
        result = {'eligible': False, 'reason': 'application_unconfirmed', 'referenceId': None,
                  'changed': False, 'deltaMeanMv': None, 'relativeChange': None,
                  'causalStatus': 'observed_difference_only', 'intervalMs': 200,
                  'timeOrigin': 'end_of_excluded_application_frame',
                  'originBrainTimeMs': episode['start'] if episode else None}
        if not episode:
            return result
        result['onsetRawMs'], result['onsetMotorMs'] = episode['onsetRawMs'], episode['onsetMotorMs']
        result['sequenceStart'] = episode['samples'][0]['sequence'] if episode['samples'] else None
        result['sequenceEnd'] = episode['samples'][-1]['sequence'] if episode['samples'] else None
        reference = episode['reference']
        reason = (episode['invalid'] or ('continued_input' if episode['continued'] else None)
                  or ('initial_action_unknown' if not episode['initialActionKnown'] else None)
                  or ('missing_identity' if not self._compatible_identity(episode['identity']) else None)
                  or ('insufficient_window' if not episode['complete'] else None)
                  or ('no_reference' if not reference else None))
        if not reason and [s['windowMs'] for s in episode['samples']] != [s['windowMs'] for s in reference['samples']]:
            reason = 'window_mismatch'
        result['reason'] = reason
        result['currentMeanMv'] = self._means(episode)
        result['currentPeakMv'] = self._peaks(episode)
        if reference:
            result['referenceId'] = reference['requestId']
            result['previousMeanMv'] = self._means(reference)
        if reason:
            return result
        current, previous = self._means(episode), self._means(reference)
        if any(value is None for value in (*current.values(), *previous.values())):
            result['reason'] = 'missing_raw'
            return result
        result['eligible'] = True
        result['deltaMeanMv'] = {axis: current[axis]-previous[axis] for axis in ('forward', 'turn')}
        threshold = self.thresholds['changeThresholdMv']
        action = episode['action']
        axis = 'forward' if action == 'FORWARD' else 'turn'
        sign = -1 if action in ('TURN_L', 'FORWARD_L') else 1
        # Do not turn opposite-sign responses into expected-direction strength.
        if action != 'STOP' and sign * current[axis] > 0 and sign * previous[axis] > 0 and threshold is not None:
            result['changed'] = abs(result['deltaMeanMv'][axis]) > threshold
            result['directionalDeltaMv'] = sign * result['deltaMeanMv'][axis]
        return result

    @staticmethod
    def _means(episode):
        samples = episode['samples']
        return {axis: (sum(s['raw'][axis]*s['windowMs'] for s in samples)/episode['duration']
                       if samples and episode['duration'] > 0 and all(s['raw'][axis] is not None for s in samples) else None)
                for axis in ('forward', 'turn')}

    @staticmethod
    def _peaks(episode):
        return {axis: ((min if axis == 'turn' and episode['action'] in ('TURN_L', 'FORWARD_L') else max)
                      ((s['raw'][axis] for s in episode['samples']), default=None)
                       if all(s['raw'][axis] is not None for s in episode['samples']) else None)
                for axis in ('forward', 'turn')}

    @staticmethod
    def _curve(episode):
        if not episode:
            return []
        samples = episode['samples']
        stride = max(1, math.ceil(len(samples)/32))
        return [{'timeMs': s['brainEndMs']-episode['start'], 'rawForward': s['raw']['forward'],
                 'rawTurn': s['raw']['turn'], 'motorForward': s['motor']['forward'], 'motorTurn': s['motor']['turn']}
                for s in samples[::stride]]

    def _body(self, body, sequence, identity, epoch, generation, inhibited):
        body = mapping(body)
        body_sequence = body.get('brainSequence')
        matched = next((sample for sample in reversed(self._ring) if sample['sequence'] == body_sequence), None)
        fresh = (body.get('source') == 'unity' and body.get('fresh') is True and body.get('sessionId') == identity['sessionId']
                 and body.get('instanceId') == identity['instanceId']
                 and integer(body.get('controlEpoch')) and body['controlEpoch'] == epoch
                 and integer(body.get('conversationGeneration')) and body['conversationGeneration'] == generation
                 and integer(body_sequence) and matched is not None
                 and number(body.get('ageMs')) is not None and 0 <= body['ageMs'] <= self.stale_ms)
        return {'source': 'unity' if body.get('source') == 'unity' else None,
                'fresh': fresh, 'correlated': fresh, 'bodyMovementVerified': False,
                'brainSequence': body_sequence if integer(body_sequence) else None,
                'currentSequence': sequence, 'ageMs': number(body.get('ageMs')),
                'brainTimeOffsetMs': self._brain_end - matched['brainEndMs'] if fresh else None,
                'causalStatus': 'body_cause_unresolved',
                'horizontalSpeed': number(body.get('horizontalSpeed')) if fresh else None,
                'forwardSpeed': number(body.get('forwardSpeed')) if fresh else None,
                'yawRateDegPerSec': number(body.get('yawRateDegPerSec')) if fresh else None,
                'discrepancy': None, 'discrepancyReason': 'output_inhibited' if inhibited else 'uncalibrated'}

    def snapshot(self, now_ms, age_ms, epoch, generation, body=None):
        if not self.enabled or self._event is None:
            return None
        now, age = number(now_ms), number(age_ms)
        if (not integer(epoch) or not integer(generation) or epoch != self._epoch or generation != self._generation or now is None or age is None
                or self._received_ms is None or now < self._received_ms or age < 0
                or max(age, now-self._received_ms+self._age_at_receive) > self.stale_ms):
            if self._episode:
                self._episode['invalid'] = 'stale_or_generation_changed'
            self._body_stability = None
            result = deepcopy(self._event)
            result.update(eventType='OBSERVATION_UNAVAILABLE', fresh=False, current=None,
                          allowedClaims=['observation_unavailable'], suppressionReason='stale_or_generation_changed',
                          currentCurve=[], bodyMovementVerified=False, residualLayer='unresolved', causalStatus='unknown')
            result['comparison'] = {'eligible': False, 'reason': 'stale_or_generation_changed'}
            result['body'] = None
            return result
        result = deepcopy(self._event)
        result['ageMs'] = max(age, now-self._received_ms+self._age_at_receive)
        if body is not None and result.get('fresh') is True:
            result['body'] = self._body(body, self._sequence, self._identity, epoch, generation,
                                        result.get('outputInhibited', False))
            self._classify_body(result, body, now)
        elif result.get('body'):
            previous_body = result['body']
            if previous_body.get('ageMs') is not None:
                previous_body['ageMs'] += now-self._received_ms
                if previous_body['ageMs'] > self.stale_ms:
                    previous_body.update(fresh=False, correlated=False, horizontalSpeed=None,
                                         forwardSpeed=None, yawRateDegPerSec=None, brainTimeOffsetMs=None)
        return result

    def _classify_body(self, result, body, now):
        """Post-grace motor/velocity mismatch, not success or causal attribution.

        Unity timestamps are intentionally unused. now-age is a Bridge monotonic
        timestamp estimate; age is a duration supplied by the existing transport.
        Two consecutive new body samples spanning >=100ms are needed. Repeated
        snapshots cannot accumulate stability or turn missing data into motion.
        """
        body = mapping(body)
        observed = result['body']
        episode = self._episode
        calibrated = (self.body_threshold_version and self.body_calibration_evidence
                      and self.body_yaw_sign is not None and all(v is not None for v in self.body_thresholds.values()))
        reason = ('output_inhibited' if result.get('outputInhibited') or body.get('outputInhibited') is True else
                  'uncalibrated' if not calibrated else
                  'body_unavailable' if not observed['fresh'] or not observed['correlated'] else
                  'application_unconfirmed' if not episode or not result['current'].get('stimulusApplied') else
                  'stop_request' if episode['action'] == 'STOP' else None)
        matched = next((sample for sample in reversed(self._ring)
                        if sample['sequence'] == body.get('brainSequence')), None)
        if not reason and (matched is None or matched['requestId'] != episode['requestId']
                           or matched['sequence'] <= episode['sequenceStart']):
            reason = 'body_request_mismatch'
        observation_sequence = body.get('sequence')
        sample_ms = now - observed['ageMs'] if observed['ageMs'] is not None else None
        if not reason and (not integer(observation_sequence) or sample_ms is None
                           or sample_ms < episode['appliedReceivedMonotonicMs']):
            reason = 'invalid_body_clock_or_sequence'
        if not reason and sample_ms-episode['appliedReceivedMonotonicMs'] < self.body_thresholds['bodyResponseGraceMs']:
            reason = 'response_grace'
        if reason:
            self._body_stability = None
            observed['discrepancyReason'] = reason
            return
        axes = []
        motor = matched['motor']
        forward, yaw = observed['forwardSpeed'], observed['yawRateDegPerSec']
        motor_threshold = self.body_thresholds['bodyMotorThreshold']
        if any(value is None for value in (motor['forward'], motor['turn'], forward, yaw)):
            self._body_stability = None
            observed['discrepancyReason'] = 'missing_motor_or_signed_velocity'
            return
        if motor['forward'] > motor_threshold and forward <= self.body_thresholds['bodySpeedThresholdMetersPerSecond']:
            axes.append('forward')
        directed_yaw = (1 if motor['turn'] > 0 else -1) * self.body_yaw_sign * yaw
        if abs(motor['turn']) > motor_threshold and directed_yaw <= self.body_thresholds['bodyYawThresholdDegPerSec']:
            axes.append('turn')
        if not axes:
            self._body_stability = None
            observed.update(discrepancy=False, discrepancyReason='no_mismatch_observed')
            return
        previous = self._body_stability
        fingerprint = (body['brainSequence'], motor['forward'], motor['turn'], forward, yaw, tuple(axes))
        if previous and observation_sequence <= previous['sequence']:
            if observation_sequence != previous['sequence'] or fingerprint != previous['fingerprint']:
                self._body_stability = None
                observed['discrepancyReason'] = 'non_new_body_observation'
                return
            stable_ms = previous['lastMs'] - previous['firstMs']
        else:
            continuing = (previous is not None and observation_sequence == previous['sequence'] + 1
                          and previous['requestId'] == episode['requestId'] and previous['axes'] == axes
                          and sample_ms > previous['lastMs'] and sample_ms-previous['lastMs'] <= self.stale_ms)
            first_ms = previous['firstMs'] if continuing else sample_ms
            stable_ms = sample_ms-first_ms
            self._body_stability = {'sequence': observation_sequence, 'requestId': episode['requestId'],
                                    'axes': axes, 'firstMs': first_ms, 'lastMs': sample_ms,
                                    'fingerprint': fingerprint}
        observed.update(discrepancy=None, discrepancyReason='stability_window',
                        discrepancyAxes=axes, stableObservationMs=stable_ms,
                        bodyThresholdVersion=self.body_threshold_version,
                        responseGraceElapsedMs=sample_ms-episode['appliedReceivedMonotonicMs'],
                        matchedMotor=dict(motor))
        if stable_ms < 100:
            return
        observed.update(discrepancy=True, discrepancyReason='motor_body_mismatch_observed')
        result.update(eventType='MOTOR_BODY_DISCREPANCY', causalStatus='body_cause_unresolved',
                      cause='body_cause_unresolved', bodyMovementVerified=False,
                      dedupKey='%s:%s:%s:%s:MOTOR_BODY_DISCREPANCY:%s' % (
                          self._identity['sessionId'], self._epoch, self._generation, episode['requestId'], ','.join(axes)))
        result['allowedClaims'] = list(result['allowedClaims']) + ['motor_body_discrepancy']
        result['eventId'] = '%s:body-%s' % (result['eventId'], observation_sequence)
        result['expiresAt'] = min(result['expiresAt'], now + self.stale_ms-observed['ageMs'])
