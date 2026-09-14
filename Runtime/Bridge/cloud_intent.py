"""Credential-free Vercel transport. Proposals still pass local admission."""
import asyncio
import ipaddress
import json
import math
from urllib.parse import urlsplit

import aiohttp

from .local_intent import CODES, compact_context, expand_compact, ground_compact


def cloud_endpoint(value):
    try:
        url = urlsplit(value)
        loopback = url.hostname == 'localhost'
        try:
            loopback = loopback or ipaddress.ip_address(url.hostname).is_loopback
        except ValueError:
            pass
        if (not value or any(c.isspace() for c in value) or not url.hostname
                or url.username is not None or url.password is not None or url.query or url.fragment
                or url.path != '/api/fly/translate'
                or not (url.scheme == 'https' or url.scheme == 'http' and loopback)
                or url.hostname == 'ai-gateway.vercel.sh'
                or url.port is not None and not 1 <= url.port <= 65535):
            raise ValueError()
        return value
    except (ValueError, TypeError, AttributeError):
        raise ValueError('invalid_cloud_intent_url') from None


async def request_cloud(config, text, context, language, default_ms, max_ms, diagnostics=None):
    endpoint = cloud_endpoint(config.get('cloudIntentUrl', ''))
    if not isinstance(text, str) or not 1 <= len(text) <= 1000 or language not in ('ja', 'en'):
        raise ValueError('invalid_cloud_input')
    timeout = min(config.get('intentTimeoutMs', 5000), 5000) / 1000
    fresh = context.get('stale') is False
    facts = context.get('facts') if type(context.get('facts')) is dict else {}
    def observed_number(name):
        value = facts.get(name)
        return (value if fresh and type(value) in (int, float) and -1000 <= value <= 1000
                and math.isfinite(value) else None)
    state = compact_context(context, default_ms, max_ms)
    state['observation'] = {'fresh': fresh, 'forward': observed_number('forward'),
                            'turn': observed_number('turn'), 'bodyMovementVerified': False}
    payload = {'schemaVersion': 1, 'playerInput': text, 'language': language,
               'flyState': state}
    fallback = expand_compact({'c': 'clarify', 'm': 't', 'v': 0}, context, language, default_ms, max_ms)
    fallback['reply'] = ('通信が使えないよ。前進・右・左・停止の短い指示なら使えるよ。'
                         if language == 'ja' else 'Cloud unavailable. Short forward, right, left and stop commands still work.')
    try:
        # Dedicated session: never inherit OpenAI auth, proxies or cookies.
        async with aiohttp.ClientSession(trust_env=False, timeout=aiohttp.ClientTimeout(total=timeout)) as http:
            async with http.post(endpoint, json=payload, allow_redirects=False) as response:
                if diagnostics is not None:
                    diagnostics['httpStatus'] = response.status
                if response.status != 200:
                    raise ValueError('cloud_unavailable')
                # read(n) may return a short network chunk before EOF. Accumulate
                # under the same hard timeout and reject before unbounded reading.
                raw = bytearray()
                async for chunk in response.content.iter_chunked(1024):
                    raw.extend(chunk)
                    if len(raw) > 4096:
                        raise ValueError('cloud_invalid_response')
                if len(raw) > 4096:
                    raise ValueError('cloud_invalid_response')
                def unique(pairs):
                    obj = {}
                    for k, v in pairs:
                        if k in obj:
                            raise ValueError('duplicate_key')
                        obj[k] = v
                    return obj
                body = json.loads(raw, object_pairs_hook=unique)
        if (type(body) is not dict or set(body) != {'schemaVersion', 'c', 'speech'}
                or type(body['schemaVersion']) is not int or body['schemaVersion'] != 1
                or type(body['c']) is not str or body['c'] not in CODES
                or type(body['speech']) is not str or len(body['speech']) > 160):
            raise ValueError('cloud_invalid_response')
        proposal = expand_compact(ground_compact({'c': body['c']}, text, context, max_ms),
                                  context, language, default_ms, max_ms)
        if proposal['kind'] in ('question', 'clarify'):
            proposal['reply'] = body['speech']
        return proposal
    except asyncio.CancelledError:
        raise
    except (aiohttp.ClientError, asyncio.TimeoutError, TimeoutError, ValueError, UnicodeError):
        if diagnostics is not None:
            diagnostics['cloudOutcome'] = 'CloudUnavailable'
        return fallback
