"""LLM layer. All functions return plain dicts/strings. Fail-soft when no API key."""
import json
import os
import re

from django.conf import settings

from . import prompts


_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client
    key = getattr(settings, 'ANTHROPIC_API_KEY', '') or os.getenv('ANTHROPIC_API_KEY', '')
    if not key:
        return None
    try:
        from anthropic import Anthropic
    except ImportError:
        return None
    _client = Anthropic(api_key=key)
    return _client


MODEL = 'claude-haiku-4-5'


def is_enabled() -> bool:
    return _get_client() is not None


def _parse_json(text: str) -> dict:
    """Extract JSON object from model output, tolerating code fences / pre/post chatter."""
    m = re.search(r'\{[\s\S]*\}', text)
    if not m:
        raise ValueError(f'No JSON found in response: {text[:200]}')
    return json.loads(m.group(0))


def generate_match_report(match_payload: dict) -> dict:
    client = _get_client()
    if not client:
        return {'error': 'AI disabled (no ANTHROPIC_API_KEY set)'}
    prompt = prompts.render_match_report_prompt(match_payload)
    msg = client.messages.create(
        model=MODEL,
        max_tokens=1500,
        system=[
            {
                'type': 'text',
                'text': prompts.SYSTEM_MATCH_REPORT,
                'cache_control': {'type': 'ephemeral'},
            }
        ],
        messages=[{'role': 'user', 'content': prompt}],
    )
    text = msg.content[0].text
    try:
        return _parse_json(text)
    except Exception:
        return {'raw': text, 'error': 'Invalid JSON from model'}


def chat(messages: list, snapshot: dict) -> str:
    client = _get_client()
    if not client:
        return 'AI chat is disabled (no ANTHROPIC_API_KEY). Please configure the key and retry.'
    system_blocks = [
        {'type': 'text', 'text': prompts.SYSTEM_CHAT},
        {
            'type': 'text',
            'text': prompts.render_chat_snapshot(snapshot),
            'cache_control': {'type': 'ephemeral'},
        },
    ]
    msg = client.messages.create(
        model=MODEL,
        max_tokens=700,
        system=system_blocks,
        messages=messages,
    )
    return msg.content[0].text


def detect_trends(trends: list, player_season: list) -> dict:
    client = _get_client()
    if not client:
        return {'error': 'AI disabled (no ANTHROPIC_API_KEY set)'}
    prompt = prompts.render_trend_prompt(trends, player_season)
    msg = client.messages.create(
        model=MODEL,
        max_tokens=1400,
        system=[
            {
                'type': 'text',
                'text': prompts.SYSTEM_TREND_DETECTOR,
                'cache_control': {'type': 'ephemeral'},
            }
        ],
        messages=[{'role': 'user', 'content': prompt}],
    )
    text = msg.content[0].text
    try:
        return _parse_json(text)
    except Exception:
        return {'raw': text, 'error': 'Invalid JSON from model'}


def tag_player(profile: dict, roster: list) -> dict:
    client = _get_client()
    if not client:
        return {'name_guess': '', 'confidence': 0, 'reasoning': 'AI disabled'}
    prompt = prompts.render_player_tag_prompt(profile, roster)
    msg = client.messages.create(
        model=MODEL,
        max_tokens=250,
        system=prompts.SYSTEM_PLAYER_TAG,
        messages=[{'role': 'user', 'content': prompt}],
    )
    text = msg.content[0].text
    try:
        return _parse_json(text)
    except Exception:
        return {'name_guess': '', 'confidence': 0, 'reasoning': f'parse fail: {text[:120]}'}
