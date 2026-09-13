"""Interactive finalized-text classifier; no body or voice service connection."""
import asyncio
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import aiohttp
from Runtime.Bridge.intent_interpreter import interpret_intent, IntentInterpreterError


async def main(provider, local_format):
    print('ローカル操作判定テスト（身体は動きません）。文を入力してください。終了: /exit')
    print('各入力は実行中の操作がない状態で判定します。入力をファイルには保存しません。')
    config = {'intentProvider': provider, 'localIntentFormat': local_format,
              'localIntentModel': 'qwen3.5:4b', 'intentTimeoutMs': 1500}
    async with aiohttp.ClientSession(trust_env=False) as http:
        while True:
            try:
                text = input('> ').strip()
            except EOFError:
                return
            if text == '/exit':
                return
            if not text:
                continue
            if len(text) > 2000:
                print('2000文字以内で入力してください。')
                continue
            diagnostics = {}
            try:
                result = await interpret_intent(http, config, text, {'activeCommand': None},
                                                'ja', 4000, 8000, diagnostics)
                print(f"{diagnostics['latencyMs']:.1f} ms / {diagnostics['route']}")
                print(json.dumps(result, ensure_ascii=False))
            except IntentInterpreterError as error:
                print('判定を採用しません: ' + str(error))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--provider', choices=('ollama', 'llama_cpp'), default='ollama')
    parser.add_argument('--local-format', choices=('compact', 'label'), default='compact')
    args = parser.parse_args()
    for stream in (sys.stdin, sys.stdout):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    try:
        asyncio.run(main(args.provider, args.local_format))
    except KeyboardInterrupt:
        pass
