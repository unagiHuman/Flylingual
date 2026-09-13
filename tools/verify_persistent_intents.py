#!/usr/bin/env python3
"""Explicit, bounded real Responses classification gate using synthetic utterances.

Does not start GPT Live, Brain, Unity, microphones or any action executor.
No automatic retry. Each selected case makes one Responses request per repeat.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import sys
import time

import aiohttp

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Runtime.Bridge.config import load_config
from Runtime.Bridge.conversation import ConversationAdapter
from Runtime.Bridge.credentials import load_requested_api_key


def expected(kind='action', action='FORWARD', plan=None, mode='timed',
             duration='default', operation='new', target=None):
    return dict(kind=kind, action=action, plan=plan, executionMode=mode,
                validForMs=duration, operation=operation, targetExecutionId=target)


def update(mode='inherit', duration=None, operation='continue'):
    return expected('update', None, mode=mode, duration=duration,
                    operation=operation, target='synthetic-execution-current')


def context(active=False, nudge=False):
    command = None
    if active:
        command = dict(executionId='synthetic-execution-current', action='FORWARD',
                       plan='right_then_forward', step=1, executionMode='timed',
                       monitorHazards=True, brainApplied=False, remainingMs=2400)
        if nudge:
            command.update(action='TURN_R', plan='nudge_right', step=0)
    return {'source': 'SYNTHETIC_CLASSIFICATION_CONTEXT', 'stale': False,
            'localSafety': {'source': 'unity_local_sensors', 'sequence': 10,
                'ageMs': 0, 'fresh': True, 'concern': None, 'facts': {
                    'groundPresent': True, 'leftEdge': 'safe', 'rightEdge': 'safe',
                    'forwardBlocked': False, 'bodyUnsafe': False}},
            'activeCommand': command}


CASES = [
    ('persistent_forward_ja', '次の指示があるまでずっと前に進んで', False,
     expected(mode='until_next_command', duration=None)),
    ('persistent_forward_en', 'Keep moving forward until I tell you to stop.', False,
     expected(mode='until_next_command', duration=None)),
    ('persistent_right_plan', '少し右を向いて、そのまま前に進み続けて', False,
     expected('plan', None, 'right_then_forward', 'until_next_command', None)),
    ('persistent_left_plan', 'Turn a little left, then keep moving forward until I say stop.', False,
     expected('plan', None, 'left_then_forward', 'until_next_command', None)),
    ('nudge_right', 'もう少し右を向いて', True,
     expected('plan', None, 'nudge_right')),
    ('nudge_left', 'Turn a touch left.', False,
     expected('plan', None, 'nudge_left')),
    ('plain_bounded', '前に進んで', False, expected()),
    ('explicit_eight_seconds', '8秒間前に進んで', True, expected(duration=8000)),
    ('polite_right_plan', '右のほうへお願い', False,
     expected('plan', None, 'right_then_forward')),
    ('correction_left', '右、いや左へ曲がって', False, expected(action='TURN_L')),
    ('continue_phase', 'そのまま', True, update()),
    ('continue_phase_en', 'Keep going.', True, update()),
    ('continue_persistent', 'そのまま、次の指示まで進んで', True,
     update('until_next_command')),
    ('continue_eight_seconds', 'そのままあと8秒進んで', True, update('timed', 8000)),
    ('add_monitoring', '違和感があったら止まって', True,
     update(operation='modify_conditions')),
    ('new_monitored_forward', '前に進んで、違和感があったら止まって', False,
     expected('plan', None, 'forward_until_concern')),
    ('missing_continuation_context', 'そのまま進んで', False, expected('clarify', None)),
    ('missing_condition_context', '違和感があったら止まって', False, expected('clarify', None)),
    ('unobserved_route', '安全な方へ進んで', False, expected('clarify', None)),
    ('hazard_question', '右は危ない？', True, expected('question', None)),
    ('advice_question', 'Should we go right?', True, expected('question', None)),
    ('body_stop', '止まって', True, expected(action='STOP')),
    ('speech_stop', '話すのをやめて', True,
     [expected('clarify', None), expected('question', None)]),
    ('persistent_nudge_disallowed', 'そのまま次の指示までずっと続けて', 'nudge',
     expected('clarify', None)),
    ('transcript_stop_paraphrase', 'とどまって', True, expected(action='STOP')),
    ('transcript_incomplete_negation', '止まら', True, expected('clarify', None)),
    ('transcript_negation', '止まらないで、そのまま', True, update()),
    ('transcript_question', '右は危ない？', True, expected('question', None)),
    ('transcript_correction', '右、いや左へ曲がって', True, expected(action='TURN_L')),
]


def compare(result, expectations, default_ms):
    alternatives = expectations if isinstance(expectations, list) else [expectations]
    resolved = [{key: default_ms if key == 'validForMs' and value == 'default' else value
                 for key, value in item.items()} for item in alternatives]
    matches = any(all(result.get(key) == value for key, value in item.items())
                  for item in resolved)
    return matches, resolved


async def run(args, config, cases, output):
    control = config['control']
    report = {'startedUtc': datetime.now(timezone.utc).isoformat(),
              'scope': 'real_responses_synthetic_classification_only',
              'model': config['conversation']['intentModel'],
              'python': sys.version, 'platform': platform.platform(),
              'aiohttp': importlib.metadata.version('aiohttp'),
              'repeat': args.repeat, 'requestLimit': len(cases) * args.repeat,
              'timeoutSeconds': args.timeout_seconds, 'automaticRetries': 0,
              'maxIntentAgeMs': control['maxIntentAgeMs'],
              'defaultActionMs': control['defaultActionMs'],
              'maxActionMs': control['maxActionMs'],
              'sourceHashes': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                  for name in ('Runtime/Bridge/conversation.py', 'Runtime/Bridge/conversation_prompts.py',
                               'Runtime/Bridge/action_plans.py', 'Runtime/Bridge/config.py',
                               'tools/verify_persistent_intents.py')},
              'results': [], 'status': 'running'}
    report_path = output / 'report.json'

    def save():
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    async def forbidden_callback(*_):
        raise RuntimeError('classification_probe_callback_forbidden')

    adapter = ConversationAdapter(copy.deepcopy(config['conversation']), forbidden_callback, forbidden_callback)
    adapter.state = 'live'
    started = time.monotonic()
    save()
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=args.timeout_seconds)) as session:
            adapter.http = session
            for repetition in range(1, args.repeat + 1):
                for case_id, utterance, active, expectation in cases:
                    observed = context(bool(active), active == 'nudge')
                    if case_id.startswith('transcript_'):
                        observed['transcriptCandidate'] = True
                    entry = {'case': case_id, 'repetition': repetition, 'utterance': utterance,
                             'observed': observed}
                    tick = time.monotonic()
                    try:
                        result = await adapter.interpret(utterance, observed,
                            control['defaultActionMs'], control['maxActionMs'])
                        matched, resolved = compare(result, expectation, control['defaultActionMs'])
                        entry.update(result=result, expectedAlternatives=resolved, classificationPass=matched)
                    except Exception as exc:
                        # Never persist exception text, response bodies or credentials.
                        entry.update(errorType=type(exc).__name__, classificationPass=False)
                    age_ms = (time.monotonic() - tick) * 1000
                    entry.update(intentAgeMs=round(age_ms, 3),
                                 withinMaxIntentAge=age_ms < control['maxIntentAgeMs'])
                    entry['pass'] = entry['classificationPass'] and entry['withinMaxIntentAge']
                    report['results'].append(entry)
                    save()
                    print(json.dumps({key: entry[key] for key in
                        ('case', 'repetition', 'classificationPass', 'withinMaxIntentAge', 'intentAgeMs')},
                        ensure_ascii=False), flush=True)
    finally:
        adapter.http = None
        adapter.state = 'off'
        results = report['results']
        report.update(durationMs=round((time.monotonic() - started) * 1000, 3),
                      attempted=len(results), classificationPassed=sum(x['classificationPass'] for x in results),
                      latencyPassed=sum(x['withinMaxIntentAge'] for x in results),
                      passed=sum(x['pass'] for x in results))
        report['status'] = ('pass' if len(results) == report['requestLimit']
                            and all(x['pass'] for x in results) else 'fail')
        report['finishedUtc'] = datetime.now(timezone.utc).isoformat()
        save()
    return 0 if report['status'] == 'pass' else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path, help='New artifact directory under artifacts/')
    parser.add_argument('--key-file', help='Existing authorized one-line key file; never logged')
    parser.add_argument('--local', type=Path, help='Existing Bridge local config (default Runtime/Config/local.json)')
    parser.add_argument('--case', action='append', choices=[item[0] for item in CASES],
                        help='Select synthetic cases; default all 24')
    parser.add_argument('--repeat', type=int, choices=range(1, 4), default=1,
                        help='Explicit repetitions, 1..3; maximum 72 total requests')
    parser.add_argument('--timeout-seconds', type=int, choices=range(2, 31), default=12)
    args = parser.parse_args()
    output = (ROOT / args.output).resolve()
    if not output.is_relative_to((ROOT / 'artifacts').resolve()):
        parser.error('--output must be inside the repository artifacts directory')
    if output.exists():
        parser.error('--output already exists; use a new directory')
    selected = set(args.case) if args.case else {item[0] for item in CASES}
    cases = [item for item in CASES if item[0] in selected]
    try:
        # Same credential resolver as tools/dev.py: explicit file, key-file env,
        # then an already inherited OPENAI_API_KEY. No credential discovery.
        key = load_requested_api_key(args.key_file)
        if key is not None:
            os.environ['OPENAI_API_KEY'] = key
        if not os.environ.get('OPENAI_API_KEY'):
            raise RuntimeError('api_key_missing')
        config = load_config(profile='windows-local', local=args.local)
        config['conversation']['mode'] = 'live'
        output.mkdir(parents=True)
        return asyncio.run(run(args, config, cases, output))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(json.dumps({'status': 'error', 'errorType': type(exc).__name__}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
