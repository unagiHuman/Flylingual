"""Warm the local classifier before play; does not connect to Unity/Brain/Live."""
import argparse
import asyncio
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import aiohttp
from Runtime.Bridge.intent_interpreter import interpret_intent, IntentInterpreterError


async def prepare(model, provider, local_format):
    diagnostics = {}
    config = {'intentProvider': provider, 'localIntentFormat': local_format,
              'localIntentModel': model, 'intentTimeoutMs': 120000}
    async with aiohttp.ClientSession(trust_env=False) as http:
        await interpret_intent(http, config, 'こんにちは', {'activeCommand': None}, 'ja', 4000, 8000, diagnostics)
    print(json.dumps({'localClassifierReady': True, 'model': model,
                      'provider': provider, 'format': local_format,
                      'origin': 'http://127.0.0.1:11436' if provider == 'llama_cpp' else 'http://127.0.0.1:11435', 'residentUntilServerStop': True,
                      'warmupMs': diagnostics['latencyMs'], 'bodyConnected': False}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', default='qwen3.5:4b')
    parser.add_argument('--provider', choices=('ollama', 'llama_cpp'), default='ollama')
    parser.add_argument('--local-format', choices=('compact', 'label'), default='compact')
    arguments = parser.parse_args()
    try:
        asyncio.run(prepare(arguments.model, arguments.provider, arguments.local_format))
    except (IntentInterpreterError, OSError) as error:
        print('Local classifier not ready: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
