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


GEMINI_MODEL = 'gemini-2.5-flash'
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
            # Dezactivăm thinking — pentru output scurt nu ne trebuie raționament intern
            # care consumă din bugetul de tokens vizibili
            thinking_config=types.ThinkingConfig(thinking_budget=0),
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
                thinking_config=types.ThinkingConfig(thinking_budget=0),
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


# ---- Tool-using chat (F2) ----

def _build_tool_declarations():
    """Build Gemini function declarations for the 5 tools."""
    return [
        {
            'name': 'get_player_detail',
            'description': 'Returnează profilul complet al unui jucător Cluj (scoruri, pierderi, line-breaks, atac, ranking).',
            'parameters': {
                'type': 'OBJECT',
                'properties': {'player_name': {'type': 'STRING', 'description': 'Numele jucătorului (parțial OK)'}},
                'required': ['player_name'],
            },
        },
        {
            'name': 'get_match_detail',
            'description': 'Returnează insights pentru un singur meci al lui Cluj (scoruri, pierderi, line-breaks, atac).',
            'parameters': {
                'type': 'OBJECT',
                'properties': {
                    'opponent': {'type': 'STRING', 'description': 'Numele adversarului (parțial OK)'},
                    'score_hint': {'type': 'STRING', 'description': 'Opțional: scorul format "X-Y" pentru a dezambigua'},
                },
                'required': ['opponent'],
            },
        },
        {
            'name': 'get_ball_loss_zones_for',
            'description': 'Returnează distribuția pierderilor de minge pentru sezon, un meci sau un jucător.',
            'parameters': {
                'type': 'OBJECT',
                'properties': {
                    'scope': {'type': 'STRING', 'description': '"season", "match" sau "player"'},
                    'id_or_name': {'type': 'STRING', 'description': 'Pentru match/player: numele adversarului sau jucătorului'},
                },
                'required': ['scope'],
            },
        },
        {
            'name': 'get_line_breaking_for',
            'description': 'Returnează contribuțiile de line-breaking pentru sezon sau un meci.',
            'parameters': {
                'type': 'OBJECT',
                'properties': {
                    'scope': {'type': 'STRING', 'description': '"season" sau "match"'},
                    'id_or_name': {'type': 'STRING', 'description': 'Pentru match: numele adversarului'},
                },
                'required': ['scope'],
            },
        },
        {
            'name': 'get_attacking_patterns_vs',
            'description': 'Returnează pattern-urile de atac ale lui Cluj în meciurile cu un anumit adversar (toate apariții).',
            'parameters': {
                'type': 'OBJECT',
                'properties': {'opponent_name': {'type': 'STRING'}},
                'required': ['opponent_name'],
            },
        },
        {
            'name': 'get_players_by_role',
            'description': 'Compară TOȚI jucătorii Cluj de pe o anumită poziție cu statistici detaliate: scor mediu, formă, dueluri câștigate %, dueluri aeriene %, intercepții, degajări, pierderi periculoase, goluri, asisturi, pase reușite %. Folosește acest tool pentru întrebări despre "cei mai folosiți fundași centrali", "compară mijlocașii", "cine joacă pe poartă", "alegere între atacanți" etc.',
            'parameters': {
                'type': 'OBJECT',
                'properties': {
                    'role': {'type': 'STRING', 'description': 'Cod poziție: GK (portari), CB (fundași centrali), FB (fundași laterali), DM (mijlocași defensivi), CM (mijlocași centrali), AM (mijlocași ofensivi), WG (extreme), CF (atacanți)'},
                },
                'required': ['role'],
            },
        },
    ]


def _execute_tool(name: str, args: dict) -> dict:
    from . import analytics
    handlers = {
        'get_player_detail':           lambda a: analytics.tool_get_player_detail(a.get('player_name', '')),
        'get_match_detail':            lambda a: analytics.tool_get_match_detail(a.get('opponent', ''), a.get('score_hint')),
        'get_ball_loss_zones_for':     lambda a: analytics.tool_get_ball_loss_zones_for(a.get('scope', ''), a.get('id_or_name')),
        'get_line_breaking_for':       lambda a: analytics.tool_get_line_breaking_for(a.get('scope', ''), a.get('id_or_name')),
        'get_attacking_patterns_vs':   lambda a: analytics.tool_get_attacking_patterns_vs(a.get('opponent_name', '')),
        'get_players_by_role':         lambda a: analytics.tool_get_players_by_role(a.get('role', '')),
    }
    h = handlers.get(name)
    if not h:
        return {'error': f'Tool necunoscut: {name}'}
    try:
        return h(args)
    except Exception as e:
        return {'error': f'{type(e).__name__}: {e}'}


def chat_with_tools(messages: list, snapshot: dict) -> dict:
    """F2 — chat cu tool calling (max 3 hops). Doar Gemini.
    Returnează: {'reply': str, 'tool_calls': [{'name', 'args', 'result_keys'}]}.
    Fallback la chat() dacă apare orice eroare sau provider nu e Gemini.
    """
    client, provider = _init()
    if not client or provider != 'gemini':
        return {'reply': chat(messages, snapshot), 'tool_calls': []}
    try:
        from google.genai import types
    except ImportError:
        return {'reply': chat(messages, snapshot), 'tool_calls': []}

    system_text = prompts.SYSTEM_TOOL_AGENT + '\n\nSnapshot iniţial cu rezumatul sezonului:\n' + prompts.render_chat_snapshot(snapshot)[:40000]
    tools = [types.Tool(function_declarations=_build_tool_declarations())]

    # Build initial contents from messages
    contents = []
    for m in messages:
        role = 'user' if m['role'] == 'user' else 'model'
        contents.append({'role': role, 'parts': [{'text': m['content']}]})

    tool_calls_log = []
    try:
        for hop in range(3):
            _log(f'TOOL-CHAT hop={hop} provider=gemini',
                 f'SYSTEM (first 300):\n{system_text[:300]}\n\nLATEST USER:\n{messages[-1]["content"] if messages else ""}')
            resp = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system_text,
                    tools=tools,
                    max_output_tokens=2000,
                    temperature=0.4,
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                ),
            )
            # Inspect parts for function_calls
            cand = (resp.candidates or [None])[0]
            if not cand or not cand.content or not cand.content.parts:
                # No candidates / empty — return text or fallback
                text = (resp.text or '').strip()
                return {'reply': text or '(fără răspuns)', 'tool_calls': tool_calls_log}

            fn_calls = [p.function_call for p in cand.content.parts if getattr(p, 'function_call', None)]
            if not fn_calls:
                # Final answer — collect text from parts
                final_text = (resp.text or '').strip()
                return {'reply': final_text, 'tool_calls': tool_calls_log}

            # Execute each tool call and add to contents
            contents.append(cand.content)  # model's function_call message
            tool_responses = []
            for fc in fn_calls:
                args = dict(fc.args) if fc.args else {}
                _log(f'TOOL CALL: {fc.name}', f'args: {args}')
                result = _execute_tool(fc.name, args)
                _log(f'TOOL RESULT: {fc.name}', str(result)[:1500])
                tool_calls_log.append({'name': fc.name, 'args': args, 'result_keys': list(result.keys()) if isinstance(result, dict) else []})
                tool_responses.append({
                    'function_response': {
                        'name': fc.name,
                        'response': result if isinstance(result, dict) else {'value': result},
                    }
                })
            contents.append({'role': 'user', 'parts': tool_responses})
        # Reached max hops
        return {'reply': 'Am atins limita de investigare. Te rog reformulează întrebarea mai precis.', 'tool_calls': tool_calls_log}
    except Exception as e:
        _log('TOOL-CHAT ERROR', f'{type(e).__name__}: {e}')
        # Fallback to plain chat
        return {'reply': chat(messages, snapshot), 'tool_calls': tool_calls_log}


def detect_trends(trends: list, player_season: list) -> dict:
    if not is_enabled():
        return {'error': 'AI disabled (no GEMINI_API_KEY or ANTHROPIC_API_KEY)'}
    user_text = prompts.render_trend_prompt(trends, player_season)
    try:
        text = _generate(prompts.SYSTEM_TREND_DETECTOR, user_text, max_tokens=6000, force_json=True)
        return _parse_json(text)
    except Exception as e:
        return {'error': f'AI error: {type(e).__name__}: {e}'}


def generate_player_summary(detail: dict) -> str:
    if not is_enabled():
        return 'AI summary dezactivat (lipsește GEMINI_API_KEY sau ANTHROPIC_API_KEY).'
    user_text = prompts.render_player_profile_prompt(detail)
    try:
        return _generate(prompts.SYSTEM_PLAYER_PROFILE, user_text, max_tokens=1500, force_json=False)
    except Exception as e:
        return f'Eroare AI: {type(e).__name__}: {e}'


def generate_coach_brief(payload: dict) -> dict:
    """F1 — Coach brief structurat pe 4 axe."""
    if not is_enabled():
        return {'error': 'AI disabled (no GEMINI_API_KEY or ANTHROPIC_API_KEY)'}
    user_text = (
        "DATE SEZON Cluj (single source of truth):\n"
        + json.dumps(payload, default=str, ensure_ascii=False, indent=2)[:25000]
        + "\n\nGenerează brief-ul JSON cu cele 4 secțiuni acum."
    )
    try:
        text = _generate(prompts.SYSTEM_COACH_BRIEF, user_text, max_tokens=4500, force_json=True)
        return _parse_json(text)
    except Exception as e:
        return {'error': f'AI error: {type(e).__name__}: {e}'}


def generate_cross_insights(payload: dict) -> dict:
    """F4 — corelații cross-axe."""
    if not is_enabled():
        return {'error': 'AI disabled (no GEMINI_API_KEY or ANTHROPIC_API_KEY)'}
    user_text = (
        "DATE Cluj (single source of truth):\n"
        + json.dumps(payload, default=str, ensure_ascii=False, indent=2)[:18000]
        + "\n\nGenerează corelațiile JSON acum."
    )
    try:
        text = _generate(prompts.SYSTEM_CROSS_INSIGHT, user_text, max_tokens=2500, force_json=True)
        return _parse_json(text)
    except Exception as e:
        return {'error': f'AI error: {type(e).__name__}: {e}'}


def explain_insight(context: str, data: dict) -> str:
    """F3 — explicație scurtă pentru un singur grafic."""
    if not is_enabled():
        return 'AI dezactivat (lipsește GEMINI_API_KEY).'
    instr = prompts.INSIGHT_PROMPTS.get(context)
    if not instr:
        return f'Context necunoscut: {context}'
    user_text = (
        instr
        + "\n\nDATE:\n"
        + json.dumps(data, default=str, ensure_ascii=False, indent=2)[:6000]
    )
    try:
        return _generate(prompts.SYSTEM_INSIGHT, user_text, max_tokens=900, force_json=False).strip()
    except Exception as e:
        return f'Eroare AI: {type(e).__name__}: {e}'


def tag_player(profile: dict, roster: list) -> dict:
    if not is_enabled():
        return {'name_guess': '', 'confidence': 0, 'reasoning': 'AI disabled'}
    user_text = prompts.render_player_tag_prompt(profile, roster)
    try:
        text = _generate(prompts.SYSTEM_PLAYER_TAG, user_text, max_tokens=250, force_json=True)
        return _parse_json(text)
    except Exception as e:
        return {'name_guess': '', 'confidence': 0, 'reasoning': f'AI error: {e}'}
