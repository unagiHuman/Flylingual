"""Fail-closed, local-only visual observation memory for Blind Sugar Run."""
import math
import time

from .control import ControlError


_DIRECTIONS = ('front', 'front-right', 'right', 'back-right', 'back', 'back-left', 'left', 'front-left')
_KINDS = {'unknown', 'desk', 'ruler', 'book', 'plate', 'sugar', 'path', 'obstacle'}
_EDGES = {'unknown', 'clear', 'near', 'very_near'}
_TRENDS = {'unknown', 'steady', 'closer', 'farther'}
_ALIGNMENTS = {'unknown', 'left', 'right', 'center'}
_SLOPES = {'unknown', 'level', 'up', 'down'}
_DIRECTION_LABELS = {'front': '前', 'front-right': '前右', 'right': '右', 'back-right': '後右',
                     'back': '後ろ', 'back-left': '後左', 'left': '左', 'front-left': '前左'}
_KIND_LABELS = {'unknown': '未確認', 'desk': '机', 'ruler': '定規', 'book': '本',
                'plate': '皿', 'sugar': '砂糖', 'path': '通路', 'obstacle': '障害物'}


def bridge_guidance(sector, language='ja'):
    direction=sector['direction']; alignment=sector['alignment']
    if language == 'en':
        place={'front':'ahead','front-right':'ahead to the right','front-left':'ahead to the left',
               'right':'to the right','left':'to the left','back':'behind','back-right':'behind to the right','back-left':'behind to the left'}[direction]
        turn={'right':' Turn slightly right to align with it.','left':' Turn slightly left to align with it.',
              'center':' It is aligned with your heading.','unknown':' Its alignment is unknown.'}[alignment]
        return 'A bridge (ruler) is '+place+'.'+turn
    turn={'right':'少し右に向きを合わせて。','left':'少し左に向きを合わせて。',
          'center':'橋の向きは今の正面に合っている。','unknown':'橋の向きはまだ未確認。'}[alignment]
    return _DIRECTION_LABELS[direction]+'に橋（定規）。'+turn


class LocalVisualObservation:
    """The latest bounded snapshot; expired or superseded generations are unusable."""

    def __init__(self):
        self.clear()

    def clear(self):
        self.sequence = 0
        self.sample = None
        self.sample_at = 0.0
        self.control_epoch = None
        self.conversation_generation = None
        self.last_spoken_at = -float('inf')
        self.last_spoken_signature = None
        self.saw_motion = False
        self.last_bridge_signature = None

    @staticmethod
    def _number(value, allow_unknown=True):
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ControlError('invalid_local_visual_observation')
        if allow_unknown and value == -1:
            return
        if value < 0 or value > 3:
            raise ControlError('invalid_local_visual_observation')

    def accept(self, event, now=None):
        fields = {'type', 'controlEpoch', 'conversationGeneration', 'sequence', 'ageMs', 'facts'}
        if set(event) != fields or event.get('type') != 'local_visual_observation':
            raise ControlError('invalid_local_visual_observation')
        if type(event['controlEpoch']) is not int or type(event['conversationGeneration']) is not int:
            raise ControlError('invalid_local_visual_observation')
        if type(event['sequence']) is not int or not 0 < event['sequence'] <= 2**53:
            raise ControlError('invalid_local_visual_observation')
        if event['sequence'] <= self.sequence:
            raise ControlError('invalid_or_stale_local_visual_observation')
        if type(event['ageMs']) not in (int, float) or not math.isfinite(event['ageMs']) or not 0 <= event['ageMs'] <= 750:
            raise ControlError('invalid_or_stale_local_visual_observation')
        facts = event['facts']
        if not isinstance(facts, dict) or set(facts) != {'ground', 'moving', 'stable', 'revisited', 'directions'}:
            raise ControlError('invalid_local_visual_observation')
        if not isinstance(facts['ground'], str) or facts['ground'] not in _KINDS or any(type(facts[k]) is not bool for k in ('moving', 'stable', 'revisited')):
            raise ControlError('invalid_local_visual_observation')
        directions = facts['directions']
        if not isinstance(directions, list) or len(directions) != 8:
            raise ControlError('invalid_local_visual_observation')
        seen = set()
        normalized = []
        for sector in directions:
            if not isinstance(sector, dict) or set(sector) != {'direction', 'surface', 'distance', 'edge', 'edgeDistance', 'trend', 'alignment', 'slope'}:
                raise ControlError('invalid_local_visual_observation')
            direction = sector['direction']
            if not isinstance(direction, str) or direction not in _DIRECTIONS or direction in seen:
                raise ControlError('invalid_local_visual_observation')
            seen.add(direction)
            if (any(not isinstance(sector[k], str) for k in ('surface', 'edge', 'trend', 'alignment', 'slope'))
                    or sector['surface'] not in _KINDS or sector['edge'] not in _EDGES
                    or sector['trend'] not in _TRENDS or sector['alignment'] not in _ALIGNMENTS
                    or sector['slope'] not in _SLOPES):
                raise ControlError('invalid_local_visual_observation')
            self._number(sector['distance'])
            self._number(sector['edgeDistance'])
            normalized.append({k: sector[k] for k in ('direction', 'surface', 'distance', 'edge', 'edgeDistance', 'trend', 'alignment', 'slope')})
        if seen != set(_DIRECTIONS):
            raise ControlError('invalid_local_visual_observation')
        stamp = time.monotonic() if now is None else now
        self.control_epoch = event['controlEpoch']
        self.conversation_generation = event['conversationGeneration']
        self.sequence = event['sequence']
        self.sample_at = stamp - event['ageMs'] / 1000
        self.sample = {'ground': facts['ground'], 'moving': facts['moving'], 'stable': facts['stable'],
                       'revisited': facts['revisited'], 'directions': normalized}
        self.saw_motion |= facts['moving']

    def describe(self, direction='all', language='ja', now=None, *, include_body=True):
        """Compact, fresh-only description for a question or GPT context."""
        summary = self.summary(now)
        if not summary['fresh']:
            return '局所視界は古く、現在の周囲は確認できない。' if language == 'ja' else 'The local view is stale; the current surroundings are unknown.'
        facts = summary['facts']
        wanted = None if direction in (None, 'all') else direction
        sectors = [s for s in facts['directions'] if wanted is None or s['direction'] == wanted]
        if wanted is not None and not sectors:
            return 'その方向は局所センサーで未確認。' if language == 'ja' else 'That direction was not observed locally.'
        def distance(value):
            return '未確認' if value == -1 else ('%.1fm' % value)
        def sector_text(s):
            label = _DIRECTION_LABELS[s['direction']]
            if s['surface'] == 'ruler':
                slope = ('上り坂。' if s['slope']=='up' else '下り坂。' if s['slope']=='down' else '')
                if language == 'en': slope = 'Uphill. ' if s['slope']=='up' else 'Downhill. ' if s['slope']=='down' else ''
                edge = ('端が非常に近い。' if s['edge']=='very_near' else '端が近い。' if s['edge']=='near' else '')
                if language == 'en': edge = 'Edge very close. ' if s['edge']=='very_near' else 'Edge nearby. ' if s['edge']=='near' else ''
                return edge + bridge_guidance(s, language) + slope
            if language == 'en':
                bits = []
                if s['surface'] != 'unknown': bits.append(s['surface'])
                if s['distance'] != -1: bits.append(distance(s['distance']) + ' away')
                if s['edge'] in ('near', 'very_near'):
                    bits.append('the edge is very close' if s['edge'] == 'very_near' else 'the edge is close')
                    if s['edgeDistance'] != -1: bits.append('edge ' + distance(s['edgeDistance']) + ' away')
                elif s['edge'] == 'clear': bits.append('no edge seen nearby')
                if s['alignment'] != 'unknown': bits.append({'left': 'extends slightly left', 'right': 'extends slightly right', 'center': 'lines up with me'}[s['alignment']])
                if s['trend'] in ('closer', 'farther'): bits.append('the edge is getting ' + s['trend'])
                if s['slope'] in ('up', 'down'): bits.append('uphill' if s['slope'] == 'up' else 'downhill')
                return s['direction'].replace('-', ' ') + ': ' + (', '.join(bits) if bits else "I can't tell what's there")
            bits = []
            if s['surface'] != 'unknown': bits.append(_KIND_LABELS[s['surface']])
            if s['distance'] != -1: bits.append(distance(s['distance']))
            if s['edge'] in ('near', 'very_near'):
                bits.append('端が' + ('非常に近い' if s['edge'] == 'very_near' else '近い'))
                if s['edgeDistance'] != -1: bits.append('端' + distance(s['edgeDistance']))
            elif s['edge'] == 'clear': bits.append('見える範囲では端を確認していない')
            if s['alignment'] != 'unknown': bits.append({'left':'少し左へ伸びている', 'right':'少し右へ伸びている', 'center':'向きが合っている'}[s['alignment']])
            if s['trend'] in ('closer', 'farther'): bits.append('端が' + ('近づいている' if s['trend'] == 'closer' else '遠ざかっている'))
            if s['slope'] in ('up', 'down'): bits.append('上り坂' if s['slope'] == 'up' else '下り坂')
            return label + 'は' + ('、'.join(bits) if bits else '未確認')
        if wanted is not None:
            return sector_text(sectors[0])
        hazards = sorted([s for s in sectors if s['edge'] in ('near', 'very_near')], key=lambda s: s['edgeDistance'] if s['edgeDistance'] >= 0 else 4)
        objects = sorted([s for s in sectors if s['surface'] not in ('unknown', facts['ground'])], key=lambda s: s['distance'] if s['distance'] >= 0 else 4)
        chosen = []
        bridges = [s for s in sectors if s['surface']=='ruler']
        for s in [s for s in hazards if s['edge']=='very_near'] + bridges + hazards + objects:
            if s not in chosen and not any(c['surface'] == s['surface'] and c['edge'] == s['edge'] for c in chosen): chosen.append(s)
        sentences = [sector_text(s) for s in chosen[:2]]
        if len(sentences) < 2:
            body = 'まだ身体が動いている' if facts['moving'] else '身体は安定している' if facts['stable'] else '安定は未確認'
            sentences.append('足元は' + _KIND_LABELS[facts['ground']] + ('、' + body if include_body else ''))
            if language == 'en':
                ground = "I can't tell what's underfoot" if facts['ground'] == 'unknown' else 'Underfoot: ' + facts['ground']
                body = "I'm moving" if facts['moving'] else "I'm steady" if facts['stable'] else "I can't tell if I'm steady"
                sentences[-1] = ground + (', ' + body if include_body else '')
        if facts['revisited'] and len(sentences) < 2: sentences.append("I've been here before" if language == 'en' else '以前通った場所に戻った')
        # Keep whole facts rather than cutting a sentence halfway through a qualification.
        text = ''
        for sentence in sentences:
            ending = '. ' if language == 'en' else '。'
            sentence = sentence.rstrip('. ') + ending if language == 'en' else sentence + ending
            if len(text) + len(sentence) <= 240: text += sentence
        return text or ("I can't tell what's nearby." if language == 'en' else '見える範囲の周囲は未確認。')

    def summary(self, now=None):
        now = time.monotonic() if now is None else now
        age = None if self.sample is None else max(0, (now - self.sample_at) * 1000)
        fresh = age is not None and age < 750
        return {'source': 'unity_local_visual_sensor', 'sequence': self.sequence,
                'ageMs': round(age, 1) if age is not None else None, 'fresh': fresh,
                'facts': self.sample if fresh else {}}

    def announcement(self, now=None, language='ja'):
        """Return a changed, useful local fact at most once per four seconds."""
        if self.sample is None:
            return None
        now = time.monotonic() if now is None else now
        if now - self.sample_at >= .75 or now - self.last_spoken_at < 4:
            return None
        facts = self.sample
        hazards = tuple((s['direction'], s['edge'], s['trend'] == 'closer') for s in facts['directions'] if s['edge'] in ('near', 'very_near'))
        objects = tuple((s['direction'], s['surface'], s['alignment']) for s in facts['directions'] if s['surface'] not in ('unknown', facts['ground']))
        bridges = [s for s in facts['directions'] if s['surface']=='ruler'
                   and s['direction'] in ('front','front-right','front-left')]
        bridge = min(bridges, key=lambda s:s['distance'] if s['distance'] >= 0 else 4) if bridges else None
        bridge_signature = (bridge['direction'],bridge['alignment']) if bridge else None
        if bridge is None: self.last_bridge_signature = None
        urgent = any(s['edge']=='very_near' for s in facts['directions'])
        if bridge is not None and not urgent and bridge_signature != self.last_bridge_signature:
            self.last_bridge_signature = bridge_signature
            self.last_spoken_signature = (facts["ground"], hazards, objects)
            self.last_spoken_at = now
            return {'kind':'discovery','facts':{'text':bridge_guidance(bridge, language)}}
        signature = (facts['ground'], hazards, objects)
        if signature == self.last_spoken_signature and not facts['revisited']:
            return None
        self.last_spoken_signature, self.last_spoken_at = signature, now
        if hazards:
            closest = min((s for s in facts['directions'] if s['edge'] in ('near', 'very_near')),
                          key=lambda s:(s['edge'] != 'very_near', s['edgeDistance'] if s['edgeDistance'] >= 0 else 4))
            return {'kind': 'hazard', 'facts': {'text': self.describe(closest['direction'], language, now=now)}}
        if facts['revisited']:
            prefix = "I've been here before. Nearby: " if language == 'en' else '以前通った場所に戻った。今見える範囲: '
            return {'kind': 'memory', 'facts': {'text': prefix + self.describe('all', language, now=now, include_body=False)}}
        if objects or facts['ground'] != 'unknown':
            return {'kind': 'discovery', 'facts': {'text': self.describe('all', language, now=now, include_body=False)}}
        return None
