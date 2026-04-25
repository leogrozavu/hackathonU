"""Pure analytics functions on Match + Cluj players.

All return JSON-serializable dicts/lists ready for JsonResponse.
"""
from collections import defaultdict

from django.db.models import Q

from .models import Match, Player, PlayerMatchStats, TrainingSession


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
    """Compact list of Cluj players for the dropdown.
    Includes is_cluj players and training-only (in_current_squad with no Wyscout matches).
    """
    out = []
    qs = Player.objects.filter(models_Q=None) if False else Player.objects.all()
    qs = Player.objects.filter(Q(is_cluj=True) | Q(in_current_squad=True))
    for p in qs:
        stats = PlayerMatchStats.objects.filter(player=p)
        matches = stats.count()
        # If no match data AND no training data → skip (orphan)
        if matches == 0:
            has_training = TrainingSession.objects.filter(player=p).exists()
            if not has_training:
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


def squad_training_totals():
    """Return dict {wy_id: {distance, hsr, sprint_25}} for all players with training data — used for ranking."""
    out = {}
    for s in TrainingSession.objects.select_related('player'):
        d = out.setdefault(s.player.wy_id, {'distance': 0.0, 'hsr': 0.0, 'sprint_25': 0.0, 'sessions': 0})
        d['distance'] += s.distance_m
        d['hsr'] += s.speed_15_20_m
        d['sprint_25'] += s.speed_25_50_m
        d['sessions'] += 1
    return out


def player_training_load(wy_id: int):
    """Aggregate training stats for a player across all available sessions."""
    sessions = list(TrainingSession.objects.filter(player__wy_id=wy_id).order_by('date', 'session_name'))
    if not sessions:
        return None

    n = len(sessions)
    total_distance = sum(s.distance_m for s in sessions)
    total_duration = sum(s.duration_min for s in sessions)
    total_hsr = sum(s.speed_15_20_m for s in sessions)
    total_sprint = sum(s.speed_20_25_m for s in sessions)
    total_max_sprint = sum(s.speed_25_50_m for s in sessions)
    total_high_acc = sum(s.high_int_acc_m for s in sessions)
    total_high_dec = sum(s.high_int_dec_m for s in sessions)
    total_accel_high_pos = sum(s.accel_high_pos for s in sessions)
    total_accel_high_neg = sum(s.accel_high_neg for s in sessions)

    weeks = {s.week for s in sessions if s.week is not None}
    sessions_per_week = round(n / max(len(weeks), 1), 1)

    avg_distance = round(total_distance / n, 0) if n else 0
    avg_work_rate = round(sum(s.work_rate for s in sessions) / n, 1) if n else 0
    avg_power = round(sum(s.power_avg_wkg for s in sessions) / max(n, 1), 1)

    # Ranks in squad
    totals = squad_training_totals()
    def rank_by(key):
        sorted_ids = [pid for pid, _ in sorted(totals.items(), key=lambda x: -x[1][key])]
        return {'rank': sorted_ids.index(wy_id) + 1 if wy_id in sorted_ids else None, 'total': len(sorted_ids)}

    # Last session (date or just last in order)
    last = sessions[-1]
    first = sessions[0]

    # Session type distribution
    type_counts = {}
    for s in sessions:
        t = s.session_type or 'altul'
        type_counts[t] = type_counts.get(t, 0) + 1

    return {
        'total_sessions': n,
        'total_distance_km': round(total_distance / 1000, 1),
        'total_duration_min': round(total_duration, 0),
        'avg_distance_per_session': avg_distance,
        'avg_work_rate': avg_work_rate,
        'avg_power_wkg': avg_power,
        'total_hsr_m': round(total_hsr, 0),
        'total_sprint_m': round(total_sprint, 0),
        'total_max_sprint_m': round(total_max_sprint, 0),
        'total_high_int_acc_m': round(total_high_acc, 0),
        'total_high_int_dec_m': round(total_high_dec, 0),
        'total_accel_high_pos': total_accel_high_pos,
        'total_accel_high_neg': total_accel_high_neg,
        'sessions_per_week_avg': sessions_per_week,
        'weeks_covered': len(weeks),
        'period_first': str(first.date) if first.date else None,
        'period_last': str(last.date) if last.date else None,
        'session_types': type_counts,
        'distance_rank': rank_by('distance'),
        'hsr_rank': rank_by('hsr'),
        'sprint_rank': rank_by('sprint_25'),
    }


def player_training_timeline(wy_id: int):
    """Per-session list cronologic for charting."""
    out = []
    for s in TrainingSession.objects.filter(player__wy_id=wy_id).order_by('date', 'session_name'):
        out.append({
            'date': str(s.date) if s.date else None,
            'week': s.week,
            'session_name': s.session_name,
            'session_type': s.session_type,
            'duration_min': round(s.duration_min, 1),
            'distance_m': round(s.distance_m, 0),
            'work_rate': round(s.work_rate, 1),
            'hsr_m': round(s.speed_15_20_m, 0),
            'sprint_m': round(s.speed_20_25_m, 0),
            'max_sprint_m': round(s.speed_25_50_m, 0),
            'high_int_acc_m': round(s.high_int_acc_m, 0),
            'high_int_dec_m': round(s.high_int_dec_m, 0),
            'power_avg_wkg': round(s.power_avg_wkg, 2),
        })
    return out


def _resolve_player_by_name(query: str):
    """Find Cluj player by partial name match (case-insensitive, accent-insensitive)."""
    import unicodedata
    q = unicodedata.normalize('NFD', query.lower())
    q = ''.join(c for c in q if unicodedata.category(c) != 'Mn')
    for p in Player.objects.filter(is_cluj=True):
        n = unicodedata.normalize('NFD', p.name.lower())
        n = ''.join(c for c in n if unicodedata.category(c) != 'Mn')
        if q in n:
            return p
    return None


def _resolve_match_by_opponent(opponent: str, score_hint: str = None):
    """Find match by opponent name (and optionally score like '2-1')."""
    candidates = list(Match.objects.filter(
        Q(home_team__icontains=opponent) | Q(away_team__icontains=opponent)
    ).order_by('wy_id'))
    if not candidates:
        return None
    if score_hint:
        for m in candidates:
            if f'{m.cluj_goals}-{m.opp_goals}' == score_hint:
                return m
    # If multiple, return latest
    return candidates[-1] if candidates else None


def tool_get_player_detail(player_name: str) -> dict:
    p = _resolve_player_by_name(player_name)
    if not p:
        return {'error': f'Jucătorul "{player_name}" nu a fost găsit'}
    d = player_detail(p.wy_id)
    if not d:
        return {'error': 'Fără date pentru acest jucător'}
    # Compact response — exclude per_match for token efficiency
    return {
        'player': d['player'],
        'score': d['score'],
        'totals_summary': {
            'goals': d['totals'].get('goals'), 'assists': d['totals'].get('assists'),
            'xg': d['totals'].get('xgShot'), 'xg_assist': d['totals'].get('xgAssist'),
            'key_passes': d['totals'].get('keyPasses'),
        },
        'ball_loss': d['ball_loss'],
        'line_breaks': d['line_breaks'],
        'attack': d['attack'],
        'rank_in_squad': d['rank_in_squad'],
    }


def tool_get_match_detail(opponent: str, score_hint: str = None) -> dict:
    m = _resolve_match_by_opponent(opponent, score_hint)
    if not m:
        return {'error': f'Meciul cu "{opponent}" nu a fost găsit'}
    return {
        'label': m.label,
        'score': f'{m.cluj_goals}-{m.opp_goals}',
        'result': m.result,
        'cluj_is_home': m.cluj_is_home,
        'opponent': m.opponent,
        'top_player_scores': compute_player_scores(m)[:8],
        'ball_losses': compute_ball_loss_zones(m),
        'line_breaks': compute_line_breaking_runs(m)[:8],
        'attack_mix': compute_attacking_patterns(m).get('type_mix', {}),
    }


def tool_get_ball_loss_zones_for(scope: str, id_or_name: str = None) -> dict:
    if scope == 'season':
        return season_ball_losses()
    if scope == 'player':
        p = _resolve_player_by_name(id_or_name or '')
        if not p:
            return {'error': 'Jucător necunoscut'}
        d = player_detail(p.wy_id)
        return {'player': p.name, 'ball_loss': d['ball_loss'] if d else None}
    if scope == 'match':
        m = _resolve_match_by_opponent(id_or_name or '')
        if not m:
            return {'error': 'Meci necunoscut'}
        return {'match': m.label, 'ball_loss': compute_ball_loss_zones(m)}
    return {'error': f'Scope necunoscut: {scope}'}


def tool_get_line_breaking_for(scope: str, id_or_name: str = None) -> dict:
    if scope == 'season':
        # Aggregate all Cluj matches
        out = {}
        for s in PlayerMatchStats.objects.filter(player__is_cluj=True).select_related('player'):
            t = (s.raw or {}).get('total') or {}
            d = out.setdefault(s.player.wy_id, {'name': s.player.display_name(), 'minutes': 0, 'prog_run': 0, 'through': 0, 'final_third': 0, 'smart': 0})
            d['minutes'] += s.minutes
            d['prog_run'] += _get(t, 'progressiveRun')
            d['through'] += _get(t, 'successfulThroughPasses')
            d['final_third'] += _get(t, 'successfulPassesToFinalThird')
            d['smart'] += _get(t, 'successfulSmartPasses')
        for d in out.values():
            d['total'] = d['prog_run'] + d['through'] + d['final_third'] + 0.5 * d['smart']
            d['per90'] = round(d['total'] * 90 / max(d['minutes'], 1), 2)
        return {'top10': sorted(out.values(), key=lambda x: -x['per90'])[:10]}
    if scope == 'match':
        m = _resolve_match_by_opponent(id_or_name or '')
        if not m:
            return {'error': 'Meci necunoscut'}
        return {'match': m.label, 'line_breaks': compute_line_breaking_runs(m)[:10]}
    return {'error': f'Scope necunoscut: {scope}'}


def tool_get_players_by_role(role: str) -> dict:
    """Compară toți jucătorii Cluj de pe o anumită poziție/rol.
    role poate fi: GK, CB, FB (left/right back), DM, CM, AM, WG (winger), CF.
    Returnează stats complete: scor, formă, dueluri, aer, intercepții, pierderi.
    """
    role_map = {
        'GK': {'gk'},
        'CB': {'cb', 'lcb', 'rcb'},
        'FB': {'lb', 'rb', 'lwb', 'rwb'},
        'DM': {'dmf', 'ldmf', 'rdmf'},
        'CM': {'cmf', 'lcmf', 'rcmf'},
        'AM': {'amf', 'am', 'lamf', 'ramf'},
        'WG': {'lw', 'rw'},
        'CF': {'cf', 'st'},
    }
    role_upper = (role or '').upper()
    codes = role_map.get(role_upper)
    if not codes:
        return {'error': f'Rol necunoscut: "{role}". Folosește: GK, CB, FB, DM, CM, AM, WG, CF.'}

    # Build form map for trend lookup
    form_map = {p['player_id']: p for p in player_form_series(window_last=5)}

    data = {}
    for s in PlayerMatchStats.objects.filter(player__is_cluj=True).select_related('player'):
        pc = (s.position_code or '').lower()
        if pc not in codes:
            continue
        total = (s.raw or {}).get('total') or {}
        c = _compute_components(total, s.minutes)
        pid = s.player.wy_id
        d = data.setdefault(pid, {
            'player_id': pid,
            'name': s.player.display_name(),
            'in_current_squad': s.player.is_cluj and s.player.in_current_squad,
            'position_code': pc,
            'minutes': 0, 'matches': 0, 'scores': [],
            'goals': 0, 'assists': 0, 'xg': 0.0,
            'def_duels': 0, 'def_duels_won': 0,
            'aerial': 0, 'aerial_won': 0,
            'interceptions': 0, 'clearances': 0, 'tackles': 0,
            'losses': 0, 'dangerous': 0,
            'progressive_run': 0, 'final_third_passes': 0,
            'passes': 0, 'successful_passes': 0,
            'key_passes': 0, 'shot_assists': 0,
        })
        d['minutes'] += s.minutes
        d['matches'] += 1
        d['scores'].append(c['score'])
        d['goals'] += _get(total, 'goals')
        d['assists'] += _get(total, 'assists')
        d['xg'] += _get(total, 'xgShot')
        d['def_duels'] += _get(total, 'defensiveDuels')
        d['def_duels_won'] += _get(total, 'defensiveDuelsWon')
        d['aerial'] += _get(total, 'aerialDuels')
        d['aerial_won'] += _get(total, 'aerialDuelsWon')
        d['interceptions'] += _get(total, 'interceptions')
        d['clearances'] += _get(total, 'clearances')
        d['tackles'] += _get(total, 'slidingTackles')
        d['losses'] += _get(total, 'losses')
        d['dangerous'] += _get(total, 'dangerousOwnHalfLosses')
        d['progressive_run'] += _get(total, 'progressiveRun')
        d['final_third_passes'] += _get(total, 'successfulPassesToFinalThird')
        d['passes'] += _get(total, 'passes')
        d['successful_passes'] += _get(total, 'successfulPasses')
        d['key_passes'] += _get(total, 'keyPasses')
        d['shot_assists'] += _get(total, 'shotAssists')

    out = []
    for pid, d in data.items():
        n = max(d['matches'], 1)
        avg_score = round(sum(d['scores']) / n, 1) if d['scores'] else 0
        fm = form_map.get(pid, {})
        out.append({
            'name': d['name'],
            'position': d['position_code'].upper(),
            'in_squad': d['in_current_squad'],
            'matches': d['matches'],
            'minutes': d['minutes'],
            'season_avg_score': avg_score,
            'recent_avg_score': fm.get('recent_avg_score', avg_score),
            'form_delta': fm.get('form_delta', 0),
            'goals': d['goals'],
            'assists': d['assists'],
            'xg': round(d['xg'], 2),
            'def_duels_won_pct': round(d['def_duels_won'] * 100 / max(d['def_duels'], 1)),
            'aerial_won_pct': round(d['aerial_won'] * 100 / max(d['aerial'], 1)),
            'interceptions': d['interceptions'],
            'clearances': d['clearances'],
            'tackles': d['tackles'],
            'losses': d['losses'],
            'dangerous_losses': d['dangerous'],
            'losses_per90': round(d['losses'] * 90 / max(d['minutes'], 1), 1),
            'progressive_run': d['progressive_run'],
            'final_third_passes': d['final_third_passes'],
            'pass_pct': round(d['successful_passes'] * 100 / max(d['passes'], 1)),
            'key_passes': d['key_passes'],
            'shot_assists': d['shot_assists'],
        })
    out.sort(key=lambda x: -x['minutes'])
    return {'role': role_upper, 'codes': sorted(codes), 'players': out, 'count': len(out)}


def tool_get_attacking_patterns_vs(opponent_name: str) -> dict:
    matches = list(Match.objects.filter(Q(home_team__icontains=opponent_name) | Q(away_team__icontains=opponent_name)).order_by('wy_id'))
    if not matches:
        return {'error': f'Niciun meci cu "{opponent_name}"'}
    rows = []
    for m in matches:
        ap = compute_attacking_patterns(m)
        rows.append({
            'match': m.label,
            'result': m.result,
            'score': f'{m.cluj_goals}-{m.opp_goals}',
            'mix': ap.get('type_mix', {}),
        })
    # Aggregated mix
    agg = {'wide': 0, 'central': 0, 'direct': 0, 'set_piece': 0}
    for r in rows:
        for k in agg:
            agg[k] += r['mix'].get(k, 0)
    return {'opponent': opponent_name, 'matches_count': len(rows), 'aggregate_mix': agg, 'matches': rows}


def head_to_head_attack_split():
    """Pentru F1 attacking_patterns: media attack mix în meciurile câștigate vs înfrânte."""
    won_mix = {'wide': 0, 'central': 0, 'direct': 0, 'set_piece': 0}
    lost_mix = {'wide': 0, 'central': 0, 'direct': 0, 'set_piece': 0}
    won_count = lost_count = 0
    for m in Match.objects.all():
        if m.result not in ('W', 'L'):
            continue
        target = won_mix if m.result == 'W' else lost_mix
        for s in PlayerMatchStats.objects.filter(match=m, player__is_cluj=True):
            t = (s.raw or {}).get('total') or {}
            target['wide']      += _get(t, 'successfulCrosses')
            target['central']   += _get(t, 'successfulThroughPasses') + _get(t, 'successfulSmartPasses')
            target['direct']    += _get(t, 'successfulLongPasses')
            target['set_piece'] += _get(t, 'corners') + _get(t, 'directFreeKicks')
        if m.result == 'W':
            won_count += 1
        else:
            lost_count += 1
    # Average per match
    def avg(d, n):
        return {k: round(v / max(n, 1), 1) for k, v in d.items()}
    return {
        'won': avg(won_mix, won_count),
        'lost': avg(lost_mix, lost_count),
        'won_count': won_count,
        'lost_count': lost_count,
    }


def coach_brief_payload():
    """Date compacte pentru AI coach brief F1."""
    summary = season_summary()
    pf = player_form_series(window_last=5)
    leaders = sorted(pf, key=lambda x: -x['form_delta'])[:5]
    concerns = sorted(pf, key=lambda x: x['form_delta'])[:5]
    losses = season_ball_losses()
    line_break_data = []
    for s in PlayerMatchStats.objects.filter(player__is_cluj=True).select_related('player'):
        total = (s.raw or {}).get('total') or {}
        line_break_data.append({
            'player_id': s.player.wy_id,
            'player_name': s.player.display_name(),
            'position_code': s.position_code or s.player.position_code,
            'minutes': s.minutes,
            'prog_run': _get(total, 'progressiveRun'),
            'through': _get(total, 'successfulThroughPasses'),
            'final_third': _get(total, 'successfulPassesToFinalThird'),
            'smart': _get(total, 'successfulSmartPasses'),
        })
    # Aggregate per player
    per_player_lb = {}
    for r in line_break_data:
        d = per_player_lb.setdefault(r['player_id'], {
            'name': r['player_name'], 'minutes': 0, 'position': r['position_code'],
            'prog_run': 0, 'through': 0, 'final_third': 0, 'smart': 0,
        })
        d['minutes'] += r['minutes']
        if r['position_code'] and not d.get('position'):
            d['position'] = r['position_code']
        for k in ('prog_run', 'through', 'final_third', 'smart'):
            d[k] += r[k]
    for d in per_player_lb.values():
        d['total'] = d['prog_run'] + d['through'] + d['final_third'] + 0.5 * d['smart']
        d['per90'] = round(d['total'] * 90 / max(d['minutes'], 1), 2)
    # Exclude goalkeepers from line-break blockers list (their job isn't to break lines)
    EXCLUDED_FROM_BLOCKERS = {'gk', 'cb', 'lcb', 'rcb'}  # GK and pure CBs
    lb_sorted = sorted(per_player_lb.values(), key=lambda x: -x['per90'])
    h2h = head_to_head_attack_split()
    return {
        'team_summary': {
            'record': summary['record'],
            'goals': f"{summary['goals_for']}-{summary['goals_against']}",
            'xg': f"{summary['xg_for']}-{summary['xg_against']}",
            'ppg': summary['ppg'],
        },
        'player_scores_summary': [
            {'name': p['player_name'], 'season_avg': p['season_avg_score'], 'recent_avg': p['recent_avg_score'],
             'form_delta': p['form_delta'], 'matches': p['total_matches']}
            for p in pf if p['total_matches'] >= 5
        ][:20],
        'leaders_form': [
            {'name': p['player_name'], 'form_delta': p['form_delta'], 'season_avg': p['season_avg_score'], 'recent_avg': p['recent_avg_score']}
            for p in leaders if p['form_delta'] > 0
        ],
        'concerns_form': [
            {'name': p['player_name'], 'form_delta': p['form_delta'], 'season_avg': p['season_avg_score'], 'recent_avg': p['recent_avg_score']}
            for p in concerns if p['form_delta'] < 0
        ],
        'ball_loss_team': losses['team_totals'],
        'ball_loss_top10': losses['players'][:10],
        'line_breaks_top10': lb_sorted[:10],
        'line_breaks_low_attacking_mids': sorted(
            [d for d in per_player_lb.values()
             if d['minutes'] >= 600
             and (d.get('position') or '').lower() not in EXCLUDED_FROM_BLOCKERS],
            key=lambda x: x['per90'],
        )[:8],
        'attack_mix_season': season_attacking_patterns()['type_mix'],
        'attack_mix_won_vs_lost': h2h,
    }


def cross_insights_payload():
    """Date pentru detectarea corelațiilor F4."""
    pf = player_form_series(window_last=5)
    # Build per-player axes
    losses = {l['player_id']: l for l in season_ball_losses()['players']}
    # Aggregate line-breaks per player
    per_player_lb = {}
    per_player_xg = {}
    per_player_goals = {}
    for s in PlayerMatchStats.objects.filter(player__is_cluj=True).select_related('player'):
        total = (s.raw or {}).get('total') or {}
        pid = s.player.wy_id
        d = per_player_lb.setdefault(pid, {'minutes': 0, 'prog_run': 0, 'through': 0, 'final_third': 0, 'smart': 0})
        d['minutes'] += s.minutes
        d['prog_run'] += _get(total, 'progressiveRun')
        d['through'] += _get(total, 'successfulThroughPasses')
        d['final_third'] += _get(total, 'successfulPassesToFinalThird')
        d['smart'] += _get(total, 'successfulSmartPasses')
        per_player_xg[pid] = per_player_xg.get(pid, 0) + _get(total, 'xgShot')
        per_player_goals[pid] = per_player_goals.get(pid, 0) + _get(total, 'goals')

    rows = []
    for p in pf:
        pid = p['player_id']
        lb = per_player_lb.get(pid, {})
        loss = losses.get(pid, {})
        lb_total = lb.get('prog_run', 0) + lb.get('through', 0) + lb.get('final_third', 0) + 0.5 * lb.get('smart', 0)
        lb_per90 = round(lb_total * 90 / max(lb.get('minutes', 1), 1), 2)
        rows.append({
            'name': p['player_name'],
            'matches': p['total_matches'],
            'season_avg_score': p['season_avg_score'],
            'recent_avg_score': p['recent_avg_score'],
            'form_delta': p['form_delta'],
            'line_breaks_per90': lb_per90,
            'losses_per90': loss.get('losses_per90', 0),
            'dangerous_losses': loss.get('dangerous', 0),
            'goals': per_player_goals.get(pid, 0),
            'xg': round(per_player_xg.get(pid, 0), 2),
            'finish_eff': round(per_player_goals.get(pid, 0) - per_player_xg.get(pid, 0), 2),
        })
    summary = season_summary()
    attack = season_attacking_patterns()['type_mix']
    return {
        'team_record': summary['record'],
        'team_xg_over_performance': round(summary['goals_for'] - summary['xg_for'], 2),
        'team_xg_against_over': round(summary['goals_against'] - summary['xg_against'], 2),
        'team_attack_mix': attack,
        'players_axes': rows,
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
    # Build training load summary per player
    training_totals = squad_training_totals()
    training_by_pid = {}
    for pid, t in training_totals.items():
        training_by_pid[pid] = {
            'sessions_2mo': t['sessions'],
            'distance_km': round(t['distance']/1000, 1),
            'hsr_m': round(t['hsr']),
            'sprint_25_m': round(t['sprint_25']),
        }
    for pf in players_form:
        pf['currently_at_cluj'] = pf['player_id'] in current_ids
        if pf['player_id'] in training_by_pid:
            pf['training_load_2mo'] = training_by_pid[pf['player_id']]

    current_squad = [
        {'name': p.display_name(), 'position': p.position_code, 'appearances': p.appearances}
        for p in Player.objects.filter(in_current_squad=True).order_by('-appearances')
    ]
    season_only = [
        {'name': p.display_name(), 'position': p.position_code, 'appearances': p.appearances,
         'note': 'played this season for Cluj but no longer at the club'}
        for p in Player.objects.filter(is_cluj=True, in_current_squad=False)
    ]
    # Regulars — jucători folosiți cel mai des (titulari obișnuiți)
    regulars_data = []
    for p in Player.objects.filter(is_cluj=True):
        stats = PlayerMatchStats.objects.filter(player=p)
        if not stats.exists():
            continue
        total_min = sum(s.minutes for s in stats)
        matches = stats.count()
        # Position cea mai jucată
        pos_min = {}
        for s in stats:
            pc = (s.position_code or p.position_code or '').lower()
            if pc:
                pos_min[pc] = pos_min.get(pc, 0) + s.minutes
        main_pos = max(pos_min.items(), key=lambda x: x[1])[0] if pos_min else (p.position_code or '')
        if total_min > 0:
            regulars_data.append({
                'name': p.display_name(),
                'position': main_pos,
                'matches': matches,
                'minutes': total_min,
                'avg_min_per_match': round(total_min / matches),
                'in_current_squad': p.in_current_squad,
            })
    regulars_data.sort(key=lambda x: -x['minutes'])

    return {
        'summary': season_summary(),
        'current_squad': current_squad,
        'players_who_left_mid_season': season_only,
        'regulars': regulars_data[:18],  # primii 18 cei mai folosiți (lot de bază)
        'players_form': players_form,
        'top_ball_losers': season_ball_losses()['players'][:10],
        'attack_mix': season_attacking_patterns()['type_mix'],
        'match_trends': season_trends(),
    }
