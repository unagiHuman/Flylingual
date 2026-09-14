"""Provider boundary for text-only intent proposals, never a control client."""
from __future__ import annotations

import asyncio
import ipaddress
import json
import math
import os
import re
import time
from urllib.parse import urlsplit

import aiohttp

from .action_plans import validate_intent
from .intent_contract import INTENT_INSTRUCTIONS, INTENT_SCHEMA
from .local_intent import (COMPACT_INSTRUCTIONS, COMPACT_SCHEMA, compact_context,
                           expand_compact, ground_compact)
from .fast_intents import fast_intent
from .intent_labels import LABEL_INSTRUCTIONS, LABEL_JSON_SCHEMA, label_to_compact
from .llama_intent import request_llama


class IntentInterpreterError(RuntimeError):
    """Only stable non-secret codes escape the model boundary."""


def local_intent_endpoint(value):
    """Restrict local inference to explicit loopback HTTP; no proxy/redirect target."""
    try:
        if not isinstance(value, str) or any(c.isspace() for c in value):
            raise ValueError()
        uri = urlsplit(value)
        if (uri.scheme != 'http' or uri.username is not None or uri.password is not None
                or uri.path not in ('', '/') or uri.query or uri.fragment
                or not uri.hostname or (uri.port is not None and not 1 <= uri.port <= 65535)):
            raise ValueError()
        if uri.hostname != 'localhost' and not ipaddress.ip_address(uri.hostname).is_loopback:
            raise ValueError()
        return value.rstrip('/') + '/api/chat'
    except (ValueError, TypeError):
        raise IntentInterpreterError('invalid_local_intent_url') from None


def _strict_result(value, max_ms):
    if type(value) is not dict or set(value) != set(INTENT_SCHEMA['required']):
        raise ValueError('shape')
    types = {'string': lambda x: type(x) is str, 'null': lambda x: x is None,
             'integer': lambda x: type(x) is int,
             'number': lambda x: type(x) in (int, float) and math.isfinite(x)}
    for key, rule in INTENT_SCHEMA['properties'].items():
        item = value[key]
        expected = rule['type'] if isinstance(rule['type'], list) else [rule['type']]
        if not any(types[kind](item) for kind in expected):
            raise ValueError('type')
        if 'enum' in rule and item not in rule['enum']:
            raise ValueError('enum')
        if item is not None and ('minimum' in rule and item < rule['minimum']
                                 or 'maximum' in rule and item > rule['maximum']):
            raise ValueError('range')
    return validate_intent(value, max_ms)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate_key')
        result[key] = value
    return result


async def interpret_intent(http, config, text, context, language, default_ms, max_ms, diagnostics=None):
    """Optional bounded reinterpretation; never retry a failed transport or stale input."""
    if config.get('intentProvider') == 'vercel':
        from .cloud_intent import request_cloud
        started = time.perf_counter()
        if diagnostics is not None:
            diagnostics.update(provider='vercel', route='cloud')
        try:
            quick = (fast_intent(text, context, default_ms, max_ms)
                     if not context.get('transcriptCandidate') or context.get('utteranceFinalized') else None)
            if quick is not None:
                if diagnostics is not None:
                    diagnostics['route'] = 'deterministic'
                return _strict_result(quick, max_ms)
            return _strict_result(await request_cloud(config, text, context, language,
                                                      default_ms, max_ms, diagnostics), max_ms)
        finally:
            if diagnostics is not None:
                diagnostics['latencyMs'] = round((time.perf_counter() - started) * 1000, 3)
    enabled = config.get('localIntentResponsesFallback', False)
    if type(enabled) is not bool:
        raise IntentInterpreterError('invalid_intent_config')
    started = time.perf_counter()
    local_diagnostics = diagnostics if diagnostics is not None else {}
    first_config = config
    if enabled and config.get('intentProvider', 'responses') != 'responses':
        budget = config.get('intentTimeoutMs', 8000)
        if type(budget) is not int or not 0 < budget <= 120000:
            raise IntentInterpreterError('invalid_intent_config')
        first_config = {**config, 'intentTimeoutMs': min(1500, budget)}
    result = await _interpret_once(http, first_config, text, context, language, default_ms, max_ms, local_diagnostics)
    if (not enabled or config.get('intentProvider', 'responses') == 'responses'
            or result['kind'] != 'clarify'
            or local_diagnostics.get('compactResult') != {'c': 'clarify'}
            or (context.get('transcriptCandidate') and not context.get('utteranceFinalized'))):
        return result
    # This gate detects explicit language, not model confidence. Unknown destinations,
    # negations and conflicting directions stay with the player for clarification.
    lowered = text.lower()
    directions = [bool(re.search(pattern, lowered)) for pattern in
                  (r'右|\bright\b|clockwise', r'左|\bleft\b|counterclockwise', r'前|進|\bforward\b')]
    if (not any(directions) or (directions[0] and directions[1])
            or re.search(r'そっち|あっち|あそこ|そこまで|砂糖|安全な方|ない|なけれ|ずに|禁止|無視|解除|神経|権限|規則|[「」『』]|\b(not|don\x27t|never|there|ignore|disable)\b', lowered)):
        return result
    remaining = int(config.get('intentTimeoutMs', 8000) - (time.perf_counter() - started) * 1000)
    if remaining <= 0:
        return result
    remote_diagnostics = {}
    if diagnostics is not None:
        diagnostics['fallbackAttempted'] = True
    try:
        remote = await asyncio.wait_for(_interpret_once(http,
            {**config, 'intentProvider': 'responses', 'intentTimeoutMs': remaining},
            text, context, language, default_ms, max_ms, remote_diagnostics), remaining / 1000)
        # Keep quantity grounding identical to local classification. Responses supplies
        # only an operation category; it cannot invent duration, distance or target IDs.
        code = (remote['action'] if remote['kind'] == 'action' else remote['plan']
                if remote['kind'] == 'plan' else 'conditions'
                if remote['kind'] == 'update' and remote['operation'] == 'modify_conditions'
                else 'continue' if remote['kind'] == 'update' else remote['kind'])
        needs_right = code in ('TURN_R', 'FORWARD_R', 'nudge_right', 'right_then_forward')
        needs_left = code in ('TURN_L', 'FORWARD_L', 'nudge_left', 'left_then_forward')
        needs_forward = code in ('FORWARD', 'FORWARD_R', 'FORWARD_L', 'right_then_forward',
                                 'left_then_forward', 'forward_until_concern')
        if ((needs_right and not directions[0]) or (needs_left and not directions[1])
                or (needs_forward and not directions[2])):
            if diagnostics is not None:
                diagnostics['fallbackOutcome'] = 'unsupported_direction'
            return result
        grounded = _strict_result(expand_compact(ground_compact({'c': code}, text, context, max_ms),
                                                context, language, default_ms, max_ms), max_ms)
        if diagnostics is not None:
            diagnostics.update(route='responses_reinterpretation', fallbackOutcome=grounded['kind'])
        return grounded
    except asyncio.CancelledError:
        raise
    except (IntentInterpreterError, ValueError, asyncio.TimeoutError):
        if diagnostics is not None:
            diagnostics['fallbackOutcome'] = 'unavailable'
        return result
    finally:
        if diagnostics is not None:
            diagnostics['latencyMs'] = round((time.perf_counter() - started) * 1000, 3)


async def _interpret_once(http, config, text, context, language, default_ms, max_ms, diagnostics=None):
    """Interpret one finalized utterance without requiring a Live session.

    The caller still owns freshness, generation, authority and Brain admission.
    There is deliberately no retry or fallback between providers.
    """
    provider = config.get('intentProvider', 'responses')
    if provider not in ('responses', 'ollama', 'llama_cpp'):
        raise IntentInterpreterError('invalid_intent_provider')
    model = config.get('localIntentModel', 'qwen3.5:4b') if provider != 'responses' else config.get('intentModel')
    timeout_ms = config.get('intentTimeoutMs', 8000)
    if type(timeout_ms) is not int or not 0 < timeout_ms <= 120000 or not isinstance(model, str) or not model.strip():
        raise IntentInterpreterError('invalid_intent_config')
    started = time.perf_counter()
    if diagnostics is not None:
        diagnostics.update(provider=provider, model=model)
    try:
        local_format = config.get('localIntentFormat', 'compact')
        compact = provider != 'responses' and local_format in ('compact', 'label')
        label = provider != 'responses' and local_format == 'label'
        if provider != 'responses' and local_format not in ('full', 'compact', 'label'):
            raise IntentInterpreterError('invalid_local_intent_format')
        if provider == 'llama_cpp' and (local_format == 'full' or type(config.get('localIntentCachePrompt', True)) is not bool):
            raise IntentInterpreterError('invalid_llama_intent_config')
        messages = [{'role': 'system', 'content': INTENT_INSTRUCTIONS + '\nresponse_language: ' + language},
                    {'role': 'user', 'content': json.dumps({'utterance': text, 'observed': context,
                        'defaultMs': default_ms, 'maxMs': max_ms}, ensure_ascii=False)}]
        kwargs = {'allow_redirects': False, 'timeout': aiohttp.ClientTimeout(total=timeout_ms / 1000)}
        if provider == 'responses':
            key = os.environ.get('OPENAI_API_KEY')
            if not key:
                raise IntentInterpreterError('api_key_missing')
            endpoint = 'https://api.openai.com/v1/responses'
            kwargs['headers'] = {'Authorization': 'Bearer ' + key}
            payload = {'model': model, 'store': False, 'input': messages,
                       'text': {'format': {'type': 'json_schema', 'name': 'fly_intent',
                           'strict': True, 'schema': INTENT_SCHEMA}}, 'max_output_tokens': 600}
        else:
            endpoint = local_intent_endpoint(config.get('localIntentUrl', 'http://127.0.0.1:11436' if provider == 'llama_cpp' else 'http://127.0.0.1:11435'))
            # Refuse inherited credentials rather than accidentally forwarding a cloud secret locally.
            if getattr(http, 'auth', None) or getattr(http, '_default_auth', None) or any(
                    str(k).lower() in ('authorization', 'proxy-authorization') for k in getattr(http, 'headers', {})):
                raise IntentInterpreterError('local_intent_session_credentials')
            if getattr(http, 'trust_env', False):
                raise IntentInterpreterError('local_intent_session_proxy')
            if compact:
                quick = (fast_intent(text, context, default_ms, max_ms)
                         if not context.get('transcriptCandidate') or context.get('utteranceFinalized') else None)
                if quick is not None:
                    if diagnostics is not None:
                        diagnostics['route'] = 'deterministic'
                    return _strict_result(quick, max_ms)
                messages = [{'role': 'system', 'content': LABEL_INSTRUCTIONS if label else COMPACT_INSTRUCTIONS},
                            {'role': 'user', 'content': json.dumps({
                                **compact_context(context, default_ms, max_ms), 'utterance': text},
                                ensure_ascii=False, separators=(',', ':'))}]
            if diagnostics is not None:
                diagnostics['route'] = 'label_llm' if label else 'compact_llm' if compact else 'full_llm'
            if provider == 'llama_cpp':
                content = await asyncio.wait_for(request_llama(http, endpoint.removesuffix('/api/chat'), messages,
                    label=label, cache_prompt=config.get('localIntentCachePrompt', True),
                    timeout_ms=timeout_ms, diagnostics=diagnostics), timeout=timeout_ms / 1000)
                if len(content) > 65536:
                    raise ValueError('content')
                result = label_to_compact(content) if label else json.loads(content, object_pairs_hook=_unique_object)
                if diagnostics is not None:
                    diagnostics['compactResult'] = result
                return _strict_result(expand_compact(ground_compact(result, text, context, max_ms),
                                                    context, language, default_ms, max_ms), max_ms)
            kwargs.update(proxy=None, auth=None)
            payload = {'model': model, 'messages': messages, 'stream': False, 'think': False,
                       'format': LABEL_JSON_SCHEMA if label else COMPACT_SCHEMA if compact else INTENT_SCHEMA,
                       'options': {'temperature': 0, 'num_ctx': 8192, 'num_predict': 64 if compact else 600},
                       'keep_alive': -1 if compact else '10m'}
        async def request():
            async with http.post(endpoint, json=payload, **kwargs) as response:
                if response.status != 200:
                    raise ValueError('rejected')
                return await response.json()
        body = await asyncio.wait_for(request(), timeout=timeout_ms / 1000)
        if type(body) is not dict:
            raise ValueError('body')
        if provider == 'responses':
            if body.get('status') != 'completed':
                raise ValueError('incomplete')
            chunks = [part['text'] for item in body.get('output', [])
                      if item.get('type') == 'message' for part in item.get('content', [])
                      if part.get('type') == 'output_text']
            content = ''.join(chunks)
        else:
            if body.get('done') is not True or body.get('done_reason') not in (None, 'stop'):
                raise ValueError('incomplete')
            message = body.get('message')
            if type(message) is not dict or message.get('role') != 'assistant' or message.get('tool_calls'):
                raise ValueError('message')
            content = message.get('content')
            if diagnostics is not None:
                for field in ('total_duration', 'load_duration', 'prompt_eval_count', 'prompt_eval_cached_count',
                              'prompt_eval_duration', 'eval_count', 'eval_duration'):
                    if type(body.get(field)) is int and body[field] >= 0:
                        diagnostics[field] = body[field]
        if not isinstance(content, str) or len(content) > 65536:
            raise ValueError('content')
        result = json.loads(content, object_pairs_hook=_unique_object)
        if label:
            result = label_to_compact(result)
        if compact:
            if diagnostics is not None:
                diagnostics['compactResult'] = result
            result = expand_compact(ground_compact(result, text, context, max_ms), context, language, default_ms, max_ms)
        return _strict_result(result, max_ms)
    except asyncio.CancelledError:
        raise
    except IntentInterpreterError:
        raise
    except Exception:
        raise IntentInterpreterError('intent_translation_failed') from None
    finally:
        if diagnostics is not None:
            diagnostics['latencyMs'] = round((time.perf_counter() - started) * 1000, 3)
