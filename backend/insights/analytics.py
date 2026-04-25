"""Pure analytics functions on Match + Cluj players.

All return JSON-serializable dicts/lists ready for JsonResponse.
"""
from collections import defaultdict

from django.db.models import Q

from .models import Match, Player, PlayerMatchStats


SCORE_SCALE = 0.3


def _get(total, key):
    return total.get(key) or 0


def _cluj_stats(match):
    return list(PlayerMatchStats.objects.filter(match=match, player__is_cluj=True).select_related('player'))


def _compute_components(total, minutes):
    """Return dict with the 5 components + raw total + per-90 score."""
    att = (
        30 * _get(total, 'goals')
        + 15 * _get(total, 'assists')
        + 20 * _get(total, 'xgShot')
        + 10 * _get(total, 'xgAssist')
        + 3 * _get(total, 'keyPasses')
        + 2 * _get(total, 'smartPasses')
        + 1.5 * _get(total, 'touchInBox')
    )
    prog = (
        0.8 * _get(total, 'progressivePasses')
        + 1.2 * _get(total, 'successfulPassesToFinalThird')
        + 1.5 * _get(total, 'progressiveRun')
        + 1.0 * _get(total, 'accelerations')
        + 0.8 * _get(total, 'successfulDribbles')
    )
    passing = (
        0.2 * _get(total, 'successfulPasses')
        + 0.5 * _get(total, 'successfulForwardPasses')
        - 0.3 * (_get(total, 'passes') - _get(total, 'successfulPasses'))
    )
    defense = (
        2 * _get(total, 'interceptions')
        + 1.5 * _get(total, 'slidingTackles')
        + 1 * _get(total, 'clearances')
        + 2 * _get(total, 'recoveries')
        + 3 * _get(total, 'dangerousOpponentHalfRecoveries')
        + 1.5 * _get(total, 'counterpressingRecoveries')
        + 1 * _get(total, 'defensiveDuelsWon')
        + 0.8 * _get(total, 'aerialDuelsWon')
    )
    risk = (
        -2 * _get(total, 'dangerousOwnHalfLosses')
        - 0.5 * _get(total, 'ownHalfLosses')
        - 0.3 * (_get(total, 'losses') - _get(total, 'ownHalfLosses'))
    )
    raw = (att + prog + passing + defense + risk) * (90 / max(minutes, 15))
    score = max(0, min(100, 50 + raw * SCORE_SCALE))
    return {
        'att': round(att, 2),
        'prog': round(prog, 2),
        'pass': round(passing, 2),
        'def': round(defense, 2),
        'risk': round(risk, 2),
        'score': round(score, 1),
    }


def compute_player_scores(match):
    out = []
    for s in _cluj_stats(match):
        total = (s.raw or {}).get('total') or {}
        c = _compute_components(total, s.minutes)
        passes = _get(total, 'passes')
        succ_passes = _get(total, 'successfulPasses')
        duels = _get(total, 'duels')
        duels_won = _get(total, 'duelsWon')
        pass_pct = round(succ_passes * 100 / passes) if passes else 0
        duels_pct = round(duels_won * 100 / duels) if duels else 0
        out.append({
            'player_id': s.player.wy_id,
            'player_name': s.player.display_name(),
            'position': s.position_code or s.player.position_code,
            'minutes': s.minutes,
            'score': c['score'],
            'breakdown': {'att': c['att'], 'prog': c['prog'], 'pass': c['pass'], 'def': c['def'], 'risk': c['risk']},
            'goals': _get(total, 'goals'),
            'assists': _get(total, 'assists'),
            'xg': round(_get(total, 'xgShot'), 2),
            'pass_pct': pass_pct,
            'duels_pct': duels_pct,
            'losses': _get(total, 'losses'),
            'key_passes': _get(total, 'keyPasses'),
            'shots': _get(total, 'shots'),
            'interceptions': _get(total, 'interceptions'),
        })
    out.sort(key=lambda x: x['score'], reverse=True)
    return out


def compute_ball_loss_zones(match):
    stats = _cluj_stats(match)
    totals = {'own_half': 0, 'opp_half': 0, 'dangerous': 0}
    players = []
    for s in stats:
        total = (s.raw or {}).get('total') or {}
        losses = _get(total, 'losses')
        own = _get(total, 'ownHalfLosses')
        dangerous = _get(total, 'dangerousOwnHalfLosses')
        opp = max(0, losses - own)
        totals['own_half'] += own
        totals['opp_half'] += opp
        totals['dangerous'] += dangerous
        players.append({
            'player_id': s.player.wy_id,
            'player_name': s.player.display_name(),
            'position': s.position_code,
            'minutes': s.minutes,
            'losses': losses,
            'own_half': own,
            'opp_half': opp,
            'dangerous': dangerous,
            'losses_per90': round(losses * 90 / max(s.minutes, 15), 2),
        })
    players.sort(key=lambda x: (x['dangerous'], x['losses_per90']), reverse=True)
    return {'team_totals': totals, 'players': players}


def compute_line_breaking_runs(match):
    out = []
    for s in _cluj_stats(match):
        total = (s.raw or {}).get('total') or {}
        prog_run = _get(total, 'progressiveRun')
        through = _get(total, 'successfulThroughPasses')
        final3 = _get(total, 'successfulPassesToFinalThird')
        smart = _get(total, 'successfulSmartPasses')
        score = prog_run + through + final3 + 0.5 * smart
        out.append({
            'player_id': s.player.wy_id,
            'player_name': s.player.display_name(),
            'position': s.position_code,
            'minutes': s.minutes,
            'score': round(score, 2),
            'breakdown': {
                'progressive_run': prog_run,
                'through_passes': through,
                'final_third_passes': final3,
                'smart_passes': smart,
            },
        })
    out.sort(key=lambda x: x['score'], reverse=True)
    return out


def compute_attacking_patterns(match):
    stats = _cluj_stats(match)
    type_mix = {'wide': 0, 'central': 0, 'direct': 0, 'set_piece': 0}
    creators = []
    finishers = []
    for s in stats:
        total = (s.raw or {}).get('total') or {}
        type_mix['wide'] += _get(total, 'successfulCrosses')
        type_mix['central'] += _get(total, 'successfulThroughPasses') + _get(total, 'successfulSmartPasses')
        type_mix['direct'] += _get(total, 'successfulLongPasses')
        type_mix['set_piece'] += _get(total, 'corners') + _get(total, 'directFreeKicks')

        creator_score = _get(total, 'shotAssists') + _get(total, 'xgAssist')
        if creator_score > 0:
            creators.append({
                'player_name': s.player.display_name(),
                'value': round(creator_score, 2),
                'shot_assists': _get(total, 'shotAssists'),
                'xg_assist': round(_get(total, 'xgAssist'), 2),
            })
        finisher_score = _get(total, 'xgShot') + 0.5 * _get(total, 'touchInBox')
        if finisher_score > 0:
            finishers.append({
                'player_name': s.player.display_name(),
                'value': round(finisher_score, 2),
                'xg': round(_get(total, 'xgShot'), 2),
                'touch_in_box': _get(total, 'touchInBox'),
                'goals': _get(total, 'goals'),
            })

    creators.sort(key=lambda x: x['value'], reverse=True)
    finishers.sort(key=lambda x: x['value'], reverse=True)
    return {
        'type_mix': type_mix,
        'top_creators': creators[:5],
        'finishers': finishers[:5],
    }


# ------ season aggregates ------

def season_summary():
    matches = list(Match.objects.all())
    wins = sum(1 for m in matches if m.result == 'W')
    draws = sum(1 for m in matches if m.result == 'D')
    losses = sum(1 for m in matches if m.result == 'L')
    gf = sum(m.cluj_goals for m in matches)
    ga = sum(m.opp_goals for m in matches)

    xg_for = xg_against = 0.0
    for m in matches:
        for s in PlayerMatchStats.objects.filter(match=m):
            total = (s.raw or {}).get('total') or {}
            x = _get(total, 'xgShot')
            if s.player.is_cluj:
                xg_for += x
            else:
                xg_against += x

    ppg = (wins * 3 + draws) / max(len(matches), 1)

    top_scorers = []
    top_assists = []
    cluj_players = Player.objects.filter(is_cluj=True)
    for p in cluj_players:
        goals = 0
        assists = 0
        xg = 0.0
        for s in PlayerMatchStats.objects.filter(player=p):
            t = (s.raw or {}).get('total') or {}
            goals += _get(t, 'goals')
            assists += _get(t, 'assists')
            xg += _get(t, 'xgShot')
        if goals > 0:
            top_scorers.append({'player_name': p.display_name(), 'goals': goals, 'xg': round(xg, 2)})
        if assists > 0:
            top_assists.append({'player_name': p.display_name(), 'assists': assists})
    top_scorers.sort(key=lambda x: x['goals'], reverse=True)
    top_assists.sort(key=lambda x: x['assists'], reverse=True)

    return {
        'matches_played': len(matches),
        'wins': wins,
        'draws': draws,
        'losses': losses,
        'record': f'{wins}-{draws}-{losses}',
        'goals_for': gf,
        'goals_against': ga,
        'xg_for': round(xg_for, 2),
        'xg_against': round(xg_against, 2),
        'ppg': round(ppg, 2),
        'top_scorers': top_scorers[:10],
        'top_assists': top_assists[:10],
    }


def season_player_scores(min_minutes=300):
    player_data = defaultdict(lambda: {
        'minutes': 0, 'matches': 0, 'att': 0, 'prog': 0, 'pass': 0, 'def': 0, 'risk': 0,
        'goals': 0, 'assists': 0, 'xg': 0.0, 'score_sum': 0, 'scores': [],
        'position': '', 'passes': 0, 'succ_passes': 0, 'duels': 0, 'duels_won': 0, 'losses': 0,
    })

    for s in PlayerMatchStats.objects.filter(player__is_cluj=True).select_related('player'):
        total = (s.raw or {}).get('total') or {}
        c = _compute_components(total, s.minutes)
        pid = s.player.wy_id
        d = player_data[pid]
        d['minutes'] += s.minutes
        d['matches'] += 1
        d['att'] += c['att']
        d['prog'] += c['prog']
        d['pass'] += c['pass']
        d['def'] += c['def']
        d['risk'] += c['risk']
        d['goals'] += _get(total, 'goals')
        d['assists'] += _get(total, 'assists')
        d['xg'] += _get(total, 'xgShot')
        d['passes'] += _get(total, 'passes')
        d['succ_passes'] += _get(total, 'successfulPasses')
        d['duels'] += _get(total, 'duels')
        d['duels_won'] += _get(total, 'duelsWon')
        d['losses'] += _get(total, 'losses')
        d['scores'].append(c['score'])
        if not d['position'] and s.position_code:
            d['position'] = s.position_code
        d['player_name'] = s.player.display_name()
        d['player_id'] = pid

    out = []
    for pid, d in player_data.items():
        if d['minutes'] < min_minutes:
            continue
        avg_score = sum(d['scores']) / len(d['scores']) if d['scores'] else 0
        out.append({
            'player_id': pid,
            'player_name': d['player_name'],
            'position': d['position'],
            'matches': d['matches'],
            'minutes': d['minutes'],
            'score': round(avg_score, 1),
            'breakdown': {
                'att': round(d['att'] / d['matches'], 2),
                'prog': round(d['prog'] / d['matches'], 2),
                'pass': round(d['pass'] / d['matches'], 2),
                'def': round(d['def'] / d['matches'], 2),
                'risk': round(d['risk'] / d['matches'], 2),
            },
            'goals': d['goals'],
            'assists': d['assists'],
            'xg': round(d['xg'], 2),
            'pass_pct': round(d['succ_passes'] * 100 / d['passes']) if d['passes'] else 0,
            'duels_pct': round(d['duels_won'] * 100 / d['duels']) if d['duels'] else 0,
            'losses': d['losses'],
        })
    out.sort(key=lambda x: x['score'], reverse=True)
    return out


def season_trends():
    rows = []
    for m in Match.objects.all().order_by('wy_id'):
        scores = []
        losses = 0
        minutes_total = 0
        xgf = 0.0
        xga = 0.0
        for s in PlayerMatchStats.objects.filter(match=m).select_related('player'):
            total = (s.raw or {}).get('total') or {}
            x = _get(total, 'xgShot')
            if s.player.is_cluj:
                c = _compute_components(total, s.minutes)
                scores.append(c['score'])
                losses += _get(total, 'losses')
                minutes_total += s.minutes
                xgf += x
            else:
                xga += x
        rows.append({
            'match_id': m.wy_id,
            'label': m.label,
            'opponent': m.opponent,
            'is_home': m.cluj_is_home,
            'result': m.result,
            'cluj_goals': m.cluj_goals,
            'opp_goals': m.opp_goals,
            'avg_player_score': round(sum(scores) / len(scores), 1) if scores else 0,
            'losses_per90': round(losses * 90 / max(minutes_total, 1), 2),
            'xg_for': round(xgf, 2),
            'xg_against': round(xga, 2),
        })
    return rows


def season_ball_losses():
    players = defaultdict(lambda: {
        'minutes': 0, 'matches': 0, 'losses': 0, 'own_half': 0, 'opp_half': 0, 'dangerous': 0,
    })
    totals = {'own_half': 0, 'opp_half': 0, 'dangerous': 0}
    for s in PlayerMatchStats.objects.filter(player__is_cluj=True).select_related('player'):
        total = (s.raw or {}).get('total') or {}
        losses = _get(total, 'losses')
        own = _get(total, 'ownHalfLosses')
        dangerous = _get(total, 'dangerousOwnHalfLosses')
        opp = max(0, losses - own)
        pid = s.player.wy_id
        d = players[pid]
        d['minutes'] += s.minutes
        d['matches'] += 1
        d['losses'] += losses
        d['own_half'] += own
        d['opp_half'] += opp
        d['dangerous'] += dangerous
        d['player_name'] = s.player.display_name()
        d['player_id'] = pid
        totals['own_half'] += own
        totals['opp_half'] += opp
        totals['dangerous'] += dangerous
    out = []
    for pid, d in players.items():
        if d['minutes'] < 300:
            continue
        out.append({
            'player_id': pid,
            'player_name': d['player_name'],
            'matches': d['matches'],
            'minutes': d['minutes'],
            'losses': d['losses'],
            'own_half': d['own_half'],
            'opp_half': d['opp_half'],
            'dangerous': d['dangerous'],
            'losses_per90': round(d['losses'] * 90 / max(d['minutes'], 1), 2),
        })
    out.sort(key=lambda x: (x['dangerous'], x['losses_per90']), reverse=True)
    return {'team_totals': totals, 'players': out}


def season_attacking_patterns():
    type_mix = {'wide': 0, 'central': 0, 'direct': 0, 'set_piece': 0}
    for s in PlayerMatchStats.objects.filter(player__is_cluj=True):
        total = (s.raw or {}).get('total') or {}
        type_mix['wide'] += _get(total, 'successfulCrosses')
        type_mix['central'] += _get(total, 'successfulThroughPasses') + _get(total, 'successfulSmartPasses')
        type_mix['direct'] += _get(total, 'successfulLongPasses')
        type_mix['set_piece'] += _get(total, 'corners') + _get(total, 'directFreeKicks')
    return {'type_mix': type_mix}


def player_form_series(window_last=8):
    """For each Cluj player, return ordered per-match score history.

    Enables AI to detect rising/declining form, head-to-head trends.
    """
    matches = list(Match.objects.all().order_by('wy_id'))
    match_id_to_label = {m.wy_id: {
        'label': m.label, 'opp': m.opponent, 'home': m.cluj_is_home,
        'score': f'{m.cluj_goals}-{m.opp_goals}', 'result': m.result,
    } for m in matches}

    series = {}
    for s in PlayerMatchStats.objects.filter(player__is_cluj=True).select_related('player', 'match'):
        total = (s.raw or {}).get('total') or {}
        c = _compute_components(total, s.minutes)
        pid = s.player.wy_id
        entry = series.setdefault(pid, {
            'player_id': pid,
            'player_name': s.player.display_name(),
            'matches': [],
        })
        entry['matches'].append({
            'match_id': s.match.wy_id,
            'opponent': match_id_to_label[s.match.wy_id]['opp'],
            'home': match_id_to_label[s.match.wy_id]['home'],
            'result': match_id_to_label[s.match.wy_id]['result'],
            'score_match': match_id_to_label[s.match.wy_id]['score'],
            'minutes': s.minutes,
            'score': c['score'],
            'goals': _get(total, 'goals'),
            'assists': _get(total, 'assists'),
            'xg': round(_get(total, 'xgShot'), 2),
            'dangerous_losses': _get(total, 'dangerousOwnHalfLosses'),
        })

    # Sort each player's matches by wy_id (chronological-ish)
    out = []
    for entry in series.values():
        entry['matches'].sort(key=lambda x: x['match_id'])
        recent = entry['matches'][-window_last:]
        recent_avg = round(sum(m['score'] for m in recent) / len(recent), 1) if recent else 0
        season_avg = round(sum(m['score'] for m in entry['matches']) / len(entry['matches']), 1) if entry['matches'] else 0
        entry['season_avg_score'] = season_avg
        entry['recent_avg_score'] = recent_avg
        entry['form_delta'] = round(recent_avg - season_avg, 1)
        entry['recent_matches'] = recent
        entry['total_matches'] = len(entry['matches'])
        del entry['matches']
        out.append(entry)
    out.sort(key=lambda x: -x['season_avg_score'])
    return out


def players_list():
    """Compact list of Cluj players for the dropdown."""
    out = []
    for p in Player.objects.filter(is_cluj=True):
        stats = PlayerMatchStats.objects.filter(player=p)
        matches = stats.count()
        if matches == 0:
            continue
        minutes = sum(s.minutes for s in stats)
        scores = []
        goals = 0
        assists = 0
        for s in stats:
            total = (s.raw or {}).get('total') or {}
            c = _compute_components(total, s.minutes)
            scores.append(c['score'])
            goals += _get(total, 'goals')
            assists += _get(total, 'assists')
        avg = sum(scores) / len(scores) if scores else 0
        out.append({
            'wy_id': p.wy_id,
            'name': p.display_name(),
            'position': p.position_code or '',
            'in_current_squad': p.in_current_squad,
            'matches': matches,
            'minutes': minutes,
            'score': round(avg, 1),
            'goals': goals,
            'assists': assists,
        })
    out.sort(key=lambda x: -x['score'])
    return out


def player_detail(wy_id: int):
    """Full season profile of one player."""
    try:
        player = Player.objects.get(wy_id=wy_id)
    except Player.DoesNotExist:
        return None

    matches_qs = list(PlayerMatchStats.objects.filter(player=player).select_related('match').order_by('match__wy_id'))
    if not matches_qs:
        return None

    per_match = []
    totals = defaultdict(float)
    component_sum = {'att': 0, 'prog': 0, 'pass': 0, 'def': 0, 'risk': 0}
    scores = []

    field_keys = (
        'goals', 'assists', 'xgShot', 'xgAssist', 'shots', 'shotsOnTarget',
        'keyPasses', 'smartPasses', 'successfulPassesToFinalThird',
        'progressivePasses', 'progressiveRun', 'accelerations', 'successfulDribbles',
        'passes', 'successfulPasses', 'successfulForwardPasses',
        'losses', 'ownHalfLosses', 'dangerousOwnHalfLosses',
        'interceptions', 'slidingTackles', 'clearances', 'recoveries',
        'dangerousOpponentHalfRecoveries', 'counterpressingRecoveries',
        'duels', 'duelsWon', 'defensiveDuelsWon', 'aerialDuelsWon',
        'successfulCrosses', 'successfulThroughPasses', 'successfulLongPasses',
        'successfulSmartPasses', 'corners', 'directFreeKicks',
        'shotAssists', 'touchInBox',
    )

    for s in matches_qs:
        total = (s.raw or {}).get('total') or {}
        c = _compute_components(total, s.minutes)
        scores.append(c['score'])
        component_sum['att'] += c['att']
        component_sum['prog'] += c['prog']
        component_sum['pass'] += c['pass']
        component_sum['def'] += c['def']
        component_sum['risk'] += c['risk']
        for k in field_keys:
            totals[k] += _get(total, k)
        m = s.match
        per_match.append({
            'match_id': m.wy_id,
            'opponent': m.opponent,
            'home': m.cluj_is_home,
            'result': m.result,
            'score_match': f'{m.cluj_goals}-{m.opp_goals}',
            'minutes': s.minutes,
            'score': c['score'],
            'goals': _get(total, 'goals'),
            'assists': _get(total, 'assists'),
            'xg': round(_get(total, 'xgShot'), 2),
            'losses': _get(total, 'losses'),
            'dangerous_losses': _get(total, 'dangerousOwnHalfLosses'),
        })

    n = len(matches_qs)
    minutes_total = sum(s.minutes for s in matches_qs)
    season_avg = round(sum(scores) / n, 1) if n else 0
    recent = scores[-5:] if len(scores) >= 1 else []
    recent_avg = round(sum(recent) / len(recent), 1) if recent else 0
    form_delta = round(recent_avg - season_avg, 1)

    breakdown_avg = {k: round(v / max(n, 1), 2) for k, v in component_sum.items()}

    own = totals['ownHalfLosses']
    opp = max(0, totals['losses'] - own)
    dangerous = totals['dangerousOwnHalfLosses']
    safe_own = max(0, own - dangerous)
    ball_loss = {
        'total_losses': int(totals['losses']),
        'own_half': int(own),
        'opp_half': int(opp),
        'dangerous': int(dangerous),
        'per90': round(totals['losses'] * 90 / max(minutes_total, 1), 2),
        'zones_proxy': {
            'own_def_third': int(dangerous),       # most dangerous = own defensive third
            'own_mid': int(safe_own),              # the rest of own half = midfield zone
            'opp_half': int(opp),
        },
        'worst_match': max(per_match, key=lambda m: m['dangerous_losses'], default=None),
    }

    line_breaks = {
        'prog_run': int(totals['progressiveRun']),
        'through_passes': int(totals['successfulThroughPasses']),
        'final_third_passes': int(totals['successfulPassesToFinalThird']),
        'smart_passes': int(totals['successfulSmartPasses']),
    }
    line_breaks['total'] = (line_breaks['prog_run'] + line_breaks['through_passes']
                            + line_breaks['final_third_passes']
                            + int(totals['successfulSmartPasses'] * 0.5))
    line_breaks['per90'] = round(line_breaks['total'] * 90 / max(minutes_total, 1), 2)

    attack = {
        'wide': int(totals['successfulCrosses']),
        'central': int(totals['successfulThroughPasses'] + totals['successfulSmartPasses']),
        'direct': int(totals['successfulLongPasses']),
        'set_piece': int(totals['corners'] + totals['directFreeKicks']),
        'shot_assists': int(totals['shotAssists']),
        'xg_assist': round(totals['xgAssist'], 2),
        'touch_in_box': int(totals['touchInBox']),
        'goals': int(totals['goals']),
        'xg': round(totals['xgShot'], 2),
        'finish_eff': round(totals['goals'] - totals['xgShot'], 2),
    }

    # Rank in squad
    season_players = season_player_scores(min_minutes=0)
    losses_data = season_ball_losses()['players']
    rank_in_squad = {}

    def rank_of(items, key, descending=True, my_id=wy_id):
        sorted_items = sorted(items, key=lambda x: x.get(key, 0) or 0, reverse=descending)
        for i, it in enumerate(sorted_items, 1):
            if it.get('player_id') == my_id:
                return {'rank': i, 'total': len(sorted_items)}
        return {'rank': None, 'total': len(sorted_items)}

    rank_in_squad['score'] = rank_of(season_players, 'score', True)
    rank_in_squad['goals'] = rank_of(season_players, 'goals', True)
    rank_in_squad['xg'] = rank_of(season_players, 'xg', True)
    rank_in_squad['dangerous_losses'] = rank_of(losses_data, 'dangerous', True)

    # Team-average context for comparison
    team_attack_total = season_attacking_patterns()['type_mix']
    return {
        'player': {
            'wy_id': player.wy_id,
            'name': player.display_name(),
            'position_code': player.position_code,
            'in_current_squad': player.in_current_squad,
            'total_matches': n,
            'total_minutes': minutes_total,
        },
        'totals': {k: int(v) if v == int(v) else round(v, 2) for k, v in totals.items()},
        'score': {
            'season_avg': season_avg,
            'recent_avg': recent_avg,
            'form_delta': form_delta,
            'breakdown_avg': breakdown_avg,
        },
        'per_match': per_match,
        'ball_loss': ball_loss,
        'line_breaks': line_breaks,
        'attack': attack,
        'team_attack_mix': team_attack_total,
        'rank_in_squad': rank_in_squad,
    }


def head_to_head(opponent_name: str):
    """All Cluj matches vs a given opponent with per-player scores."""
    matches = Match.objects.filter(
        Q(home_team=opponent_name) | Q(away_team=opponent_name)
    ).order_by('wy_id')
    out = []
    for m in matches:
        if opponent_name not in (m.home_team, m.away_team):
            continue
        players = []
        for s in PlayerMatchStats.objects.filter(match=m, player__is_cluj=True).select_related('player'):
            total = (s.raw or {}).get('total') or {}
            c = _compute_components(total, s.minutes)
            players.append({
                'name': s.player.display_name(),
                'pos': s.position_code,
                'min': s.minutes,
                'score': c['score'],
                'g': _get(total, 'goals'),
                'a': _get(total, 'assists'),
            })
        players.sort(key=lambda p: -p['score'])
        out.append({
            'match_id': m.wy_id,
            'label': m.label,
            'result': m.result,
            'score': f'{m.cluj_goals}-{m.opp_goals}',
            'home': m.cluj_is_home,
            'players': players[:14],
        })
    return out


def season_snapshot_for_ai():
    """Rich dict used as grounding for AI chat + trend detection."""
    current_ids = set(Player.objects.filter(in_current_squad=True).values_list('wy_id', flat=True))
    players_form = player_form_series(window_last=5)
    for pf in players_form:
        pf['currently_at_cluj'] = pf['player_id'] in current_ids

    current_squad = [
        {'name': p.display_name(), 'position': p.position_code, 'appearances': p.appearances}
        for p in Player.objects.filter(in_current_squad=True).order_by('-appearances')
    ]
    season_only = [
        {'name': p.display_name(), 'position': p.position_code, 'appearances': p.appearances,
         'note': 'played this season for Cluj but no longer at the club'}
        for p in Player.objects.filter(is_cluj=True, in_current_squad=False)
    ]
    return {
        'summary': season_summary(),
        'current_squad': current_squad,
        'players_who_left_mid_season': season_only,
        'players_form': players_form,
        'top_ball_losers': season_ball_losses()['players'][:10],
        'attack_mix': season_attacking_patterns()['type_mix'],
        'match_trends': season_trends(),
    }
