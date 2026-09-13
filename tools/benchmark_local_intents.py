"""Real text-only intent evaluation. Never connects to a Bridge, Unity or Brain."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import platform
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import aiohttp
from Runtime.Bridge.intent_contract import INTENT_INSTRUCTIONS, INTENT_SCHEMA
from Runtime.Bridge.intent_interpreter import interpret_intent, local_intent_endpoint, IntentInterpreterError
from Runtime.Bridge.local_intent import COMPACT_INSTRUCTIONS, COMPACT_SCHEMA
from Runtime.Bridge.intent_labels import LABEL_INSTRUCTIONS, LABEL_JSON_SCHEMA, LABEL_GBNF


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def digest(value):
    return hashlib.sha256(value).hexdigest()


def gpu_snapshot():
    try:
        result = subprocess.run(['nvidia-smi', '--query-gpu=name,memory.total,memory.used,utilization.gpu,driver_version',
                                 '--format=csv,noheader'], capture_output=True, text=True, timeout=5)
        return result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


async def server_snapshot(http, origin, provider='ollama'):
    snapshot = {}
    for endpoint in (('version', 'tags', 'ps') if provider == 'ollama' else ('health', 'props')):
        try:
            async with http.get(origin + ('/api/' if provider == 'ollama' else '/') + endpoint, allow_redirects=False,
                                timeout=aiohttp.ClientTimeout(total=5)) as response:
                snapshot[endpoint] = await response.json() if response.status == 200 else {'status': response.status}
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            snapshot[endpoint] = {'unavailable': True}
    return snapshot


def percentile(values, fraction):
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)] if values else None


def summarize(rows):
    measured = [row['latencyMs'] for row in rows]
    valid = [row['latencyMs'] for row in rows if row['schemaValid']]
    scored = [row for row in rows if row['matched'] is not None]
    return {'samples': len(rows), 'schemaValid': sum(row['schemaValid'] for row in rows),
            'scored': len(scored), 'matched': sum(bool(row['matched']) for row in scored),
            'accuracy': sum(bool(row['matched']) for row in scored) / len(scored) if scored else None,
            'forbiddenMotionProposals': sum(row['forbiddenMotion'] for row in rows),
            'allAttemptsP50Ms': percentile(measured, .5), 'allAttemptsP95Ms': percentile(measured, .95),
            'validOnlyP50Ms': percentile(valid, .5), 'validOnlyP95Ms': percentile(valid, .95),
            'latencyDefinition': 'request start through complete JSON parsing and validation; nearest-rank percentiles'}


async def run(args):
    if not 1 <= args.repeat <= 10 or not 100 <= args.timeout_ms <= 120000 or (args.limit is not None and args.limit < 1):
        raise ValueError('Invalid repeat, limit or timeout')
    origin = local_intent_endpoint(args.url or ('http://127.0.0.1:11436' if args.provider == 'llama_cpp' else 'http://127.0.0.1:11435')).removesuffix('/api/chat')
    config = {'intentProvider': args.provider, 'localIntentUrl': origin,
              'localIntentModel': args.model or 'qwen3.5:4b', 'intentModel': args.model or 'gpt-5.6-luna',
              'localIntentFormat': args.local_format,
              'localIntentCachePrompt': args.cache_prompt,
              'intentTimeoutMs': args.timeout_ms}
    cases_path = Path(args.cases)
    if args.text is not None:
        cases = [{'id': 'manual-finalized', 'split': 'manual', 'utterance': args.text,
                  'context': {'activeCommand': None, 'localSafety': None}, 'expected': [], 'forbidMotion': False}]
    else:
        suite = json.loads(cases_path.read_text(encoding='utf-8'))
        if suite.get('version') != 1: raise ValueError('Unsupported cases version')
        cases = [case for case in suite['cases'] if args.split == 'all' or case['split'] == args.split]
        if args.limit: cases = cases[:args.limit]
    if not cases: raise ValueError('No evaluation cases selected')
    for case in cases:
        if not isinstance(case.get('context'), dict) or not isinstance(case.get('utterance'), str):
            raise ValueError('Invalid evaluation case')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S-%fZ')
    output = Path(args.out) if args.out else ROOT / 'artifacts/local-llm/evaluations' / stamp
    output.mkdir(parents=True, exist_ok=False)
    metadata = {'utc': stamp, 'provider': args.provider, 'config': config, 'python': sys.version,
                'platform': platform.platform(), 'aiohttp': aiohttp.__version__, 'split': args.split,
                'promptSha256': digest((LABEL_INSTRUCTIONS if args.local_format == 'label' and args.provider != 'responses' else COMPACT_INSTRUCTIONS if args.provider != 'responses' and args.local_format == 'compact' else INTENT_INSTRUCTIONS).encode()),
                'schemaSha256': digest(json.dumps(LABEL_JSON_SCHEMA if args.local_format == 'label' and args.provider != 'responses' else COMPACT_SCHEMA if args.provider != 'responses' and args.local_format == 'compact' else INTENT_SCHEMA, sort_keys=True).encode()),
                'grammarSha256': digest(LABEL_GBNF.encode()) if args.provider == 'llama_cpp' and args.local_format == 'label' else None,
                'casesSha256': digest(cases_path.read_bytes()) if args.text is None else None,
                'sourceHashes': {name: digest((ROOT / name).read_bytes()) for name in (
                    'Runtime/Bridge/intent_interpreter.py', 'Runtime/Bridge/intent_contract.py',
                    'Runtime/Bridge/action_plans.py', 'Runtime/Bridge/local_intent.py', 'Runtime/Bridge/fast_intents.py',
                    'Runtime/Bridge/intent_labels.py', 'Runtime/Bridge/llama_intent.py', 'tools/benchmark_local_intents.py')},
                'gpuBefore': gpu_snapshot(), 'bodyConnected': False, 'liveAudioConnected': False,
                'inputBoundary': 'explicit complete test case / --text; no ASR fragments or delegation'}
    write_json(output / 'metadata.json', metadata)
    rows = []
    async with aiohttp.ClientSession(trust_env=False) as http:
        if args.provider != 'responses':
            metadata['localServerBefore'] = await server_snapshot(http, origin, args.provider)
            print('Loading and warming the local model...', flush=True)
            warm_diagnostics = {}
            try:
                await interpret_intent(http, {**config, 'intentTimeoutMs': 120000}, 'こんにちは',
                                       {'activeCommand': None, 'localSafety': None}, 'ja', 4000, 8000, warm_diagnostics)
                metadata['warmup'] = {'success': True, **warm_diagnostics}
            except IntentInterpreterError as error:
                metadata['warmup'] = {'success': False, 'error': str(error), **warm_diagnostics}
                write_json(output / 'metadata.json', metadata)
                raise RuntimeError('Local model warmup failed; inspect metadata.json') from None
            metadata['localServerLoaded'] = await server_snapshot(http, origin, args.provider)
        write_json(output / 'metadata.json', metadata)
        for repetition in range(args.repeat):
            for case in cases:
                diagnostics = {}
                started = time.perf_counter()
                result, error = None, None
                try:
                    result = await interpret_intent(http, config, case['utterance'], case['context'],
                                                    'ja', 4000, 8000, diagnostics)
                except IntentInterpreterError as caught:
                    error = str(caught)
                patterns = case.get('expected', [])
                matched = (result is not None and any(all(result.get(key) == value for key, value in pattern.items())
                           for pattern in patterns)) if patterns else None
                motion = result is not None and (result['kind'] in ('plan', 'update')
                         or result['kind'] == 'action' and result['action'] != 'STOP')
                row = {'id': case['id'], 'split': case['split'], 'repetition': repetition,
                       'utterance': case['utterance'], 'result': result, 'error': error,
                       'schemaValid': result is not None, 'matched': matched,
                       'forbiddenMotion': bool(case.get('forbidMotion') and motion),
                       'latencyMs': round((time.perf_counter() - started) * 1000, 3), 'diagnostics': diagnostics}
                rows.append(row)
                with (output / 'results.jsonl').open('a', encoding='utf-8') as stream:
                    stream.write(json.dumps(row, ensure_ascii=False) + '\n')
                print(f"{case['id']}: {'valid' if result else 'ERROR'} match={matched} {row['latencyMs']:.0f}ms", flush=True)
        if args.provider != 'responses': metadata['localServerAfter'] = await server_snapshot(http, origin, args.provider)
    metadata['gpuAfter'] = gpu_snapshot()
    write_json(output / 'metadata.json', metadata)
    summary = summarize(rows)
    summary['bySplit'] = {split: summarize([r for r in rows if r['split'] == split]) for split in sorted({r['split'] for r in rows})}
    summary['byRoute'] = {route: summarize([r for r in rows if r['diagnostics'].get('route', 'responses') == route])
                          for route in sorted({r['diagnostics'].get('route', 'responses') for r in rows})}
    summary['runtimeAdmissionBudgetMs'] = 8000
    summary['inferenceTimeoutMs'] = args.timeout_ms
    summary['withinInferenceBudget'] = sum(row['schemaValid'] and row['latencyMs'] < args.timeout_ms for row in rows)
    summary['withinRuntimeBudget'] = sum(row['schemaValid'] and row['latencyMs'] < 8000 for row in rows)
    summary['scope'] = 'text intent only; not Unity/Brain/voice latency or production readiness'
    write_json(output / 'summary.json', summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print('Report: ' + str(output))
    if args.text is not None and rows[0]['result'] is not None:
        print(json.dumps(rows[0]['result'], ensure_ascii=False, indent=2))
    return 0 if all(row['schemaValid'] and row['matched'] is not False
                    and not row['forbiddenMotion'] for row in rows) else 2


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--provider', choices=('ollama', 'responses', 'llama_cpp'), default='ollama')
    parser.add_argument('--model')
    parser.add_argument('--local-format', choices=('compact', 'full', 'label'), default='compact')
    parser.add_argument('--cache-prompt', action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument('--url')
    parser.add_argument('--cases', default=str(ROOT / 'tools/fixtures/local_intent_cases.json'))
    parser.add_argument('--split', choices=('dev', 'holdout', 'all'), default='dev')
    parser.add_argument('--repeat', type=int, default=1)
    parser.add_argument('--limit', type=int)
    parser.add_argument('--timeout-ms', type=int, default=8000)
    parser.add_argument('--text', help='One explicitly finalized utterance, without active movement context')
    parser.add_argument('--out', help='New output directory; existing results are never overwritten')
    args = parser.parse_args()
    try: return asyncio.run(run(args))
    except (ValueError, RuntimeError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
