"""LLM layer with Gemini + Anthropic support. Picks provider based on env vars."""
import json
import os
import re
import sys
import time

from django.conf import settings

from . import prompts


DEBUG_AI = True


def _log(label, text):
    if not DEBUG_AI:
        return
    sep = '=' * 70
    print(f'\n{sep}\n[AI DEBUG] {label}\n{sep}\n{text}\n{sep}', flush=True, file=sys.stdout)


_client = None
_provider = None


def _init():
    global _client, _provider
    if _client is not None:
        return _client, _provider

    gemini_key = os.getenv('GEMINI_API_KEY') or getattr(settings, 'GEMINI_API_KEY', '')
    anthropic_key = os.getenv('ANTHROPIC_API_KEY') or getattr(settings, 'ANTHROPIC_API_KEY', '')

    if gemini_key:
        try:
            from google import genai
        except ImportError:
            return None, None
        _client = genai.Client(api_key=gemini_key)
        _provider = 'gemini'
        return _client, _provider

    if anthropic_key:
        try:
            from anthropic import Anthropic
        except ImportError:
            return None, None
        _client = Anthropic(api_key=anthropic_key)
        _provider = 'anthropic'
        return _client, _provider

    return None, None


GEMINI_MODEL = 'gemini-2.5-flash-lite'
ANTHROPIC_MODEL = 'claude-haiku-4-5'


def is_enabled() -> bool:
    client, _ = _init()
    return client is not None


def _parse_json(text: str) -> dict:
    m = re.search(r'\{[\s\S]*\}', text)
    if not m:
        raise ValueError(f'No JSON in response: {text[:200]}')
    raw = m.group(0)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        _log('JSON PARSE FAILED — attempting repair', f'error: {e}\nraw length: {len(raw)}')
        repaired = _repair_truncated_json(raw)
        parsed = json.loads(repaired)
        _log('JSON REPAIR OK', f'keys: {list(parsed.keys())}')
        return parsed


def _repair_truncated_json(raw: str) -> str:
    """Best-effort repair of truncated JSON by closing open brackets."""
    stack = []
    in_string = False
    escape = False
    last_valid = 0
    for i, ch in enumerate(raw):
        if escape:
            escape = False
            continue
        if ch == '\\':
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in '{[':
            stack.append(ch)
        elif ch in '}]':
            if stack:
                stack.pop()
            if not stack:
                last_valid = i + 1
    # Trim trailing garbage and close open structures
    truncated = raw[:last_valid] if last_valid else raw
    if not last_valid:
        # Close open strings, then open brackets
        out = raw
        if in_string:
            out += '"'
        # Strip trailing comma/space
        out = re.sub(r'[,\s]+$', '', out)
        for ch in reversed(stack):
            out += '}' if ch == '{' else ']'
        return out
    return truncated


def _generate(system_text: str, user_text: str, max_tokens: int = 1500, force_json: bool = False) -> str:
    """Provider-agnostic text generation."""
    client, provider = _init()
    if not client:
        raise RuntimeError('AI not configured')

    _log(f'REQUEST [{provider} / single-turn / max_tokens={max_tokens} / force_json={force_json}]',
         f'SYSTEM (first 400 chars):\n{system_text[:400]}\n\nUSER (chars={len(user_text)}):\n{user_text[:600]}{"...(truncated)" if len(user_text) > 600 else ""}')
    t0 = time.time()

    if provider == 'gemini':
        from google.genai import types
        config = types.GenerateContentConfig(
            system_instruction=system_text,
            max_output_tokens=max_tokens,
            temperature=0.4,
        )
        if force_json:
            config.response_mime_type = 'application/json'
        resp = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=user_text,
            config=config,
        )
        text = resp.text or ''
    else:
        msg = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=max_tokens,
            system=[{'type': 'text', 'text': system_text, 'cache_control': {'type': 'ephemeral'}}],
            messages=[{'role': 'user', 'content': user_text}],
        )
        text = msg.content[0].text

    elapsed = time.time() - t0
    _log(f'RESPONSE [{elapsed:.1f}s / {len(text)} chars]', text)
    return text


def _chat_generate(system_text: str, messages: list, max_tokens: int = 700) -> str:
    """Multi-turn chat."""
    client, provider = _init()
    if not client:
        raise RuntimeError('AI not configured')

    last_user = next((m['content'] for m in reversed(messages) if m['role'] == 'user'), '')
    _log(f'CHAT REQUEST [{provider} / turns={len(messages)} / max_tokens={max_tokens}]',
         f'SYSTEM (first 400 chars):\n{system_text[:400]}\n\nLAST USER TURN:\n{last_user}')
    t0 = time.time()

    if provider == 'gemini':
        from google.genai import types
        contents = []
        for m in messages:
            role = 'user' if m['role'] == 'user' else 'model'
            contents.append({'role': role, 'parts': [{'text': m['content']}]})
        resp = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system_text,
                max_output_tokens=max_tokens,
                temperature=0.5,
            ),
        )
        text = resp.text or ''
    else:
        msg = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=max_tokens,
            system=[{'type': 'text', 'text': system_text, 'cache_control': {'type': 'ephemeral'}}],
            messages=messages,
        )
        text = msg.content[0].text

    elapsed = time.time() - t0
    _log(f'CHAT RESPONSE [{elapsed:.1f}s / {len(text)} chars]', text)
    return text


def generate_match_report(match_payload: dict) -> dict:
    if not is_enabled():
        return {'error': 'AI disabled (no GEMINI_API_KEY or ANTHROPIC_API_KEY)'}
    user_text = prompts.render_match_report_prompt(match_payload)
    try:
        text = _generate(prompts.SYSTEM_MATCH_REPORT, user_text, max_tokens=2500, force_json=True)
        return _parse_json(text)
    except Exception as e:
        return {'error': f'AI error: {type(e).__name__}: {e}'}


def chat(messages: list, snapshot: dict) -> str:
    if not is_enabled():
        return 'AI chat dezactivat (lipsește GEMINI_API_KEY sau ANTHROPIC_API_KEY).'
    system_text = prompts.SYSTEM_CHAT + '\n\n' + prompts.render_chat_snapshot(snapshot)
    try:
        return _chat_generate(system_text, messages, max_tokens=1200)
    except Exception as e:
        return f'Eroare AI: {type(e).__name__}: {e}'


def detect_trends(trends: list, player_season: list) -> dict:
    if not is_enabled():
        return {'error': 'AI disabled (no GEMINI_API_KEY or ANTHROPIC_API_KEY)'}
    user_text = prompts.render_trend_prompt(trends, player_season)
    try:
        text = _generate(prompts.SYSTEM_TREND_DETECTOR, user_text, max_tokens=6000, force_json=True)
        return _parse_json(text)
    except Exception as e:
        return {'error': f'AI error: {type(e).__name__}: {e}'}


def tag_player(profile: dict, roster: list) -> dict:
    if not is_enabled():
        return {'name_guess': '', 'confidence': 0, 'reasoning': 'AI disabled'}
    user_text = prompts.render_player_tag_prompt(profile, roster)
    try:
        text = _generate(prompts.SYSTEM_PLAYER_TAG, user_text, max_tokens=250, force_json=True)
        return _parse_json(text)
    except Exception as e:
        return {'name_guess': '', 'confidence': 0, 'reasoning': f'AI error: {e}'}
