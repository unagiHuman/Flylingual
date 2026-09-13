"""llama.cpp native completion transport with explicit prefix-cache control."""
import aiohttp
import hashlib

from .intent_labels import LABEL_GBNF
from .local_intent import COMPACT_SCHEMA


async def request_llama(http, origin, messages, *, label, cache_prompt, timeout_ms, diagnostics=None):
    kwargs = {'allow_redirects': False, 'proxy': None, 'auth': None,
              'timeout': aiohttp.ClientTimeout(total=timeout_ms / 1000)}
    # Use this model's actual template, not a hard-coded ChatML or special-token guess.
    async with http.post(origin + '/apply-template', json={'messages': messages,
                         'chat_template_kwargs': {'enable_thinking': False}}, **kwargs) as response:
        if response.status != 200:
            raise ValueError('template_rejected')
        template = await response.json()
    if type(template) is not dict or type(template.get('prompt')) is not str:
        raise ValueError('invalid_template')
    # Hybrid recurrent models cannot rewind to an arbitrary token like a pure
    # transformer. Save an explicit checkpoint before the changing user suffix.
    # A cache flag alone otherwise re-evaluates the entire system prompt.
    prefix = template['prompt'].rpartition(messages[-1]['content'])[0]
    if cache_prompt:
        if not prefix or messages[-1]['content'] not in template['prompt']:
            raise ValueError('missing_shared_prefix')
        key = (origin, hashlib.sha256(prefix.encode('utf-8')).hexdigest())
        prepared = getattr(http, '_local_intent_prefixes', None)
        if prepared is None:
            prepared = http._local_intent_prefixes = set()
        if key not in prepared:
            async with http.post(origin + '/completion', json={'prompt': prefix, 'n_predict': 0,
                                 'cache_prompt': True, 'id_slot': 0, 'stream': False}, **kwargs) as response:
                if response.status != 200:
                    raise ValueError('prefix_prefill_rejected')
                warmed = await response.json()
            if type(warmed) is not dict or warmed.get('stop') is not True:
                raise ValueError('prefix_prefill_incomplete')
            prepared.add(key)
    payload = {'prompt': template['prompt'], 'stream': False, 'temperature': 0, 'seed': 0,
               'n_predict': 16 if label else 64, 'cache_prompt': cache_prompt, 'id_slot': 0}
    payload['grammar' if label else 'json_schema'] = LABEL_GBNF if label else COMPACT_SCHEMA
    async with http.post(origin + '/completion', json=payload, **kwargs) as response:
        if response.status != 200:
            raise ValueError('completion_rejected')
        body = await response.json()
    if (type(body) is not dict or body.get('stop') is not True or body.get('truncated')
            or body.get('stop_type') not in ('eos', 'word') or type(body.get('content')) is not str):
        raise ValueError('incomplete_completion')
    if diagnostics is not None:
        diagnostics['cachePrompt'] = cache_prompt
        diagnostics['llamaTimings'] = {key: value for key, value in body.get('timings', {}).items()
                                     if type(value) in (int, float)}
        diagnostics['tokensEvaluated'] = body.get('tokens_evaluated')
        diagnostics['tokensPredicted'] = body.get('tokens_predicted')
    if cache_prompt and body.get('timings', {}).get('cache_n', 0) == 0:
        prepared.discard(key)  # A server restart/eviction must permit re-priming.
    return body['content']
