"""Opt-in, one-occurrence Cloud Run validation of real third-party review seats."""
import concurrent.futures
import datetime as dt
import hashlib
import json
import os
import re
import urllib.error
import urllib.request

MAX_OUTPUT = 384
MAX_RESPONSE = 64 * 1024
FIXTURE = (
    'Synthetic paper ledger: start with 1000 cash. Buy two units at 100 and pay a total fee of 2; '
    'sell one unit at 110 and pay a fee of 1; mark the remaining unit at 103. Allocate the purchase '
    'fee equally to both units. Ignore funding and operating expenses. Return only a JSON object '
    'with integer fields cash, remaining_basis, realized, unrealized, equity and '
    'a short string next_action describing one reconciliation check. No tools or external sources.'
)
EXPECTED = dict(cash=907, remaining_basis=101, realized=8, unrealized=2, equity=1010)
PROVIDERS = {
    'OpenAI': ('api.openai.com/v1/chat/completions', 'gpt-5-mini', 'APEX_OPENAI_API_KEY'),
    'Claude': ('api.anthropic.com/v1/messages', 'claude-haiku-5-5', 'APEX_ANTHROPIC_API_KEY'),
}


class ProviderError(Exception):
    """Bounded, operator-safe errors: no raw payloads, prompts, headers or keys."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def reserve_once(store, name, event_id):
    key = 'apex-external-v1-' + hashlib.sha256((name + ':' + event_id).encode()).hexdigest()

    def write(tx):
        if tx.get('meta', key) is not None:
            return False
        tx.put('meta', key, {'provider': name, 'event_id': event_id, 'attempt_reserved_at': now()})
        return True

    if not store.atomic(write):
        raise ProviderError(name + ' already attempted for this Calendar occurrence')


def post(url, headers, payload):
    req = urllib.request.Request(url, json.dumps(payload).encode(), headers, method='POST')
    try:
        with urllib.request.build_opener(NoRedirect()).open(req, timeout=30) as response:
            data = response.read(MAX_RESPONSE + 1)
            if len(data) > MAX_RESPONSE:
                raise ProviderError('Provider response exceeded byte cap')
            return json.loads(data), {k.lower(): v for k, v in response.headers.items()}
    except urllib.error.HTTPError as exc:
        raise ProviderError('Provider returned HTTP ' + str(exc.code)) from None
    except (ValueError, OSError):
        raise ProviderError('Provider response unavailable or invalid; no retry') from None


def invoke(name, key, event_id, store, transport=post):
    path, model, _ = PROVIDERS[name]
    message = {'role': 'user', 'content': FIXTURE}
    headers = {'Content-Type': 'application/json'}
    if name == 'OpenAI':
        headers['Authorization'] = 'Bearer ' + key
        payload = {'model': model, 'messages': [message], 'max_completion_tokens': MAX_OUTPUT,
                   'response_format': {'type': 'json_object'}, 'store': False, 'service_tier': 'default'}
    else:
        headers.update({'x-api-key': key, 'anthropic-version': '2023-06-01'})
        payload = {'model': model, 'messages': [message], 'max_tokens': MAX_OUTPUT,
                   'output_config': {'effort': 'low'}}
    reserve_once(store, name, event_id)
    started = now()
    data, returned_headers = transport('https://' + path, headers, payload)
    finished = now()
    try:
        if name == 'OpenAI':
            choice = data['choices'][0]
            if choice['finish_reason'] != 'stop' or choice['message'].get('refusal'):
                raise ValueError()
            answer = json.loads(choice['message']['content'])
            usage = dict(input_tokens=data['usage']['prompt_tokens'],
                         output_tokens=data['usage']['completion_tokens'])
        else:
            if data['stop_reason'] != 'end_turn':
                raise ValueError()
            answer = json.loads(''.join(x['text'] for x in data['content'] if x['type'] == 'text'))
            usage = dict(input_tokens=data['usage']['input_tokens'], output_tokens=data['usage']['output_tokens'])
        if not isinstance(answer, dict) or set(answer) != set(EXPECTED) | {'next_action'}:
            raise ValueError()
        if not all(type(answer[k]) is int and abs(answer[k]) <= 1_000_000 for k in EXPECTED):
            raise ValueError()
        if not isinstance(answer['next_action'], str) or not 0 < len(answer['next_action'].strip()) <= 320:
            raise ValueError()
        if not all(type(n) is int and n >= 0 for n in usage.values()) or usage['output_tokens'] > MAX_OUTPUT:
            raise ValueError()
        request_id = returned_headers.get('x-request-id') or returned_headers.get('request-id')
        identifiers = (request_id, data['id'], data['model'])
        if not all(isinstance(s, str) and re.fullmatch(r'[A-Za-z0-9_.:-]{1,150}', s) for s in identifiers):
            raise ValueError()
        if data['model'] != model and not data['model'].startswith(model + '-'):
            raise ValueError()
    except (ValueError, TypeError, KeyError, IndexError, AttributeError):
        raise ProviderError(name + ' returned no verified completion envelope') from None
    reported = {k: answer[k] for k in EXPECTED}
    mismatches = [k for k, v in reported.items() if v != EXPECTED[k]]
    verdict = 'matched deterministic arithmetic' if not mismatches else 'failed checks: ' + ', '.join(mismatches)
    return {
        'response': {'update': 'Synthetic paper result (' + verdict + '): ' + json.dumps(reported, sort_keys=True),
                     'next_action': answer['next_action'], 'evidence': []},
        'metadata': {'provider': name, 'model': data['model'], 'family': 'openai-gpt' if name == 'OpenAI' else 'claude',
                     'request_id': request_id, 'response_id': data['id'], 'usage': usage,
                     'started_at': started, 'finished_at': finished, 'fixture_check_passed': not mismatches,
                     'prompt_sha256': hashlib.sha256(FIXTURE.encode()).hexdigest(),
                     'api_cost_usd': None, 'scope': 'synthetic calendar canary only'},
    }


def execute_with_external_review(action_executor, task, context, adapters, goal, store,
                                 environ=None, transport=post):
    """Keep normal reviews unchanged. Never send caller context to either provider."""
    env = os.environ if environ is None else environ
    source = goal.get('spec', {}).get('source', {})
    event_id = env.get('APEX_EXTERNAL_REVIEW_EVENT_ID', '')
    if not (
        env.get('APEX_EXTERNAL_REVIEW_ENABLED') == '1'
        and re.fullmatch(r'[a-v0-9]{5,80}', event_id)
        and source.get('event_id') == event_id and source.get('mode') == 'review'
        and goal.get('spec', {}).get('project') == 'SchafferAI'
        and task.get('id') == 'review' and task.get('type') == 'review'
    ):
        return action_executor(task, context, adapters)
    keys = {n: env.get(p[2]) for n, p in PROVIDERS.items()}
    if not all(keys.values()):
        return action_executor(task, context, adapters)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = {n: pool.submit(invoke, n, key, event_id, store, transport)
                   for n, key in keys.items()}
        from actions import ActionError

        def seat(future):
            def get_result(_private_prompt, **_kwargs):
                try:
                    return future.result()
                except ProviderError as exc:
                    raise ActionError(str(exc)) from None
            return get_result

        original = adapters.get('contributors', {})
        scoped = dict(adapters, contributors={**original, **{n: seat(f) for n, f in futures.items()}})
        # These two calls start concurrently and use the same synthetic fixture.
        # Other reviewers see the existing Calendar task/context as before.
        return action_executor(task, context, scoped)
