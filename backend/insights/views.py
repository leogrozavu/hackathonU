import json

from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from . import ai, analytics
from .models import Match, Player, PlayerMatchStats


def _ok(data):
    return JsonResponse(data, safe=not isinstance(data, list), json_dumps_params={'ensure_ascii': False})


def match_list(request):
    matches = Match.objects.all().order_by('wy_id')
    data = [{
        'wy_id': m.wy_id,
        'label': m.label,
        'home_team': m.home_team,
        'away_team': m.away_team,
        'home_score': m.home_score,
        'away_score': m.away_score,
        'cluj_is_home': m.cluj_is_home,
        'opponent': m.opponent,
        'cluj_goals': m.cluj_goals,
        'opp_goals': m.opp_goals,
        'result': m.result,
    } for m in matches]
    return _ok(data)


def match_detail(request, wy_id):
    m = get_object_or_404(Match, wy_id=wy_id)
    players = PlayerMatchStats.objects.filter(match=m, player__is_cluj=True).select_related('player')
    roster = [{
        'player_id': s.player.wy_id,
        'player_name': s.player.display_name(),
        'position': s.position_code,
        'minutes': s.minutes,
    } for s in players]
    return _ok({
        'wy_id': m.wy_id,
        'label': m.label,
        'home_team': m.home_team,
        'away_team': m.away_team,
        'home_score': m.home_score,
        'away_score': m.away_score,
        'cluj_is_home': m.cluj_is_home,
        'opponent': m.opponent,
        'cluj_goals': m.cluj_goals,
        'opp_goals': m.opp_goals,
        'result': m.result,
        'roster_cluj': roster,
    })


def match_player_scores(request, wy_id):
    m = get_object_or_404(Match, wy_id=wy_id)
    return _ok(analytics.compute_player_scores(m))


def match_ball_losses(request, wy_id):
    m = get_object_or_404(Match, wy_id=wy_id)
    return _ok(analytics.compute_ball_loss_zones(m))


def match_line_breaks(request, wy_id):
    m = get_object_or_404(Match, wy_id=wy_id)
    return _ok(analytics.compute_line_breaking_runs(m))


def match_attacking_patterns(request, wy_id):
    m = get_object_or_404(Match, wy_id=wy_id)
    return _ok(analytics.compute_attacking_patterns(m))


def match_ai_report(request, wy_id):
    if not ai.is_enabled():
        return JsonResponse({'error': 'AI disabled (set ANTHROPIC_API_KEY)'}, status=503)
    m = get_object_or_404(Match, wy_id=wy_id)
    payload = {
        'label': m.label,
        'score': f'{m.cluj_goals}-{m.opp_goals}',
        'cluj_is_home': m.cluj_is_home,
        'opponent': m.opponent,
        'result': m.result,
        'player_scores': analytics.compute_player_scores(m)[:10],
        'ball_losses': analytics.compute_ball_loss_zones(m),
        'line_breaks': analytics.compute_line_breaking_runs(m)[:8],
        'attacking_patterns': analytics.compute_attacking_patterns(m),
    }
    report = ai.generate_match_report(payload)
    return _ok(report)


def season_summary(request):
    return _ok(analytics.season_summary())


def season_player_scores(request):
    return _ok(analytics.season_player_scores())


def season_trends(request):
    return _ok(analytics.season_trends())


def season_ball_losses(request):
    return _ok(analytics.season_ball_losses())


def season_attacking_patterns(request):
    return _ok(analytics.season_attacking_patterns())


def season_ai_trends(request):
    if not ai.is_enabled():
        return JsonResponse({'error': 'AI disabled (set ANTHROPIC_API_KEY)'}, status=503)
    trends = analytics.season_trends()
    players = analytics.season_player_scores()
    return _ok(ai.detect_trends(trends, players[:25]))


@csrf_exempt
@require_http_methods(['POST'])
def ai_chat(request):
    if not ai.is_enabled():
        return JsonResponse({'error': 'AI disabled (set ANTHROPIC_API_KEY)'}, status=503)
    try:
        body = json.loads(request.body.decode('utf-8') or '{}')
    except Exception:
        return JsonResponse({'error': 'invalid json'}, status=400)
    messages = body.get('messages') or []
    if not messages:
        return JsonResponse({'error': 'messages required'}, status=400)
    snapshot = analytics.season_snapshot_for_ai()
    reply = ai.chat(messages, snapshot)
    return _ok({'reply': reply})
