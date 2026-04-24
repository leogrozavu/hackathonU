"""AI-based player name attribution.

For each Cluj player without a real name, builds a season profile and asks the
LLM to match against the public Cluj 2024/25 roster.
"""
from collections import defaultdict

from django.core.management.base import BaseCommand

from insights import ai
from insights.models import Player, PlayerMatchStats
from insights.rosters import CLUJ_SQUAD_2024_25, MANUAL_OVERRIDES


class Command(BaseCommand):
    help = 'Use LLM to guess real player names based on statistical profile + roster.'

    def add_arguments(self, parser):
        parser.add_argument('--threshold', type=float, default=0.7,
                            help='Min confidence to apply the name')
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, threshold, dry_run, **opts):
        # 1. Apply manual overrides first
        applied_manual = 0
        for wy_id, name in MANUAL_OVERRIDES.items():
            updated = Player.objects.filter(wy_id=wy_id).update(name=name)
            if updated:
                applied_manual += updated
        if applied_manual:
            self.stdout.write(f'Applied {applied_manual} manual overrides.')

        if not ai.is_enabled():
            self.stdout.write(self.style.WARNING(
                'ANTHROPIC_API_KEY not set — AI tagging skipped. Only manual overrides applied.'
            ))
            return

        players = Player.objects.filter(is_cluj=True).exclude(wy_id__in=MANUAL_OVERRIDES.keys())
        self.stdout.write(f'Tagging {players.count()} Cluj players via LLM...')

        roster = CLUJ_SQUAD_2024_25
        updated_count = 0
        low_conf_count = 0

        for player in players:
            profile = _build_profile(player)
            result = ai.tag_player(profile, roster)
            name = (result.get('name_guess') or '').strip()
            conf = float(result.get('confidence') or 0)
            reasoning = result.get('reasoning') or ''
            self.stdout.write(f'  pid={player.wy_id} pos={profile["top_position"]} gls={profile["goals"]} ast={profile["assists"]} min={profile["minutes"]} -> {name!r} conf={conf:.2f}  ({reasoning[:80]})')
            if name and conf >= threshold and not dry_run:
                Player.objects.filter(wy_id=player.wy_id).update(name=name)
                updated_count += 1
            elif conf < threshold:
                low_conf_count += 1

        self.stdout.write(self.style.SUCCESS(
            f'Done. Updated {updated_count} names. Low-confidence skipped: {low_conf_count}.'
        ))


def _build_profile(player) -> dict:
    totals = defaultdict(float)
    positions = defaultdict(int)
    matches = 0
    minutes = 0
    for s in PlayerMatchStats.objects.filter(player=player):
        minutes += s.minutes
        matches += 1
        if s.position_code:
            positions[s.position_code] += s.minutes
        raw = (s.raw or {}).get('total') or {}
        for k in (
            'goals', 'assists', 'xgShot', 'xgAssist',
            'passes', 'successfulPasses', 'keyPasses',
            'defensiveDuelsWon', 'aerialDuelsWon', 'interceptions', 'clearances',
            'shots', 'touchInBox', 'dribbles', 'successfulDribbles',
        ):
            totals[k] += raw.get(k, 0) or 0
    top_pos = max(positions.items(), key=lambda x: x[1])[0] if positions else '?'
    pos_breakdown = {p: round(v * 100 / max(minutes, 1)) for p, v in positions.items()}
    return {
        'matches': matches,
        'minutes': minutes,
        'top_position': top_pos,
        'position_breakdown_percent': pos_breakdown,
        'goals': int(totals['goals']),
        'assists': int(totals['assists']),
        'xg': round(totals['xgShot'], 1),
        'xa': round(totals['xgAssist'], 1),
        'shots': int(totals['shots']),
        'touch_in_box': int(totals['touchInBox']),
        'key_passes': int(totals['keyPasses']),
        'pass_completion_pct': round(totals['successfulPasses'] * 100 / max(totals['passes'], 1), 1),
        'interceptions': int(totals['interceptions']),
        'clearances': int(totals['clearances']),
        'aerial_duels_won': int(totals['aerialDuelsWon']),
        'defensive_duels_won': int(totals['defensiveDuelsWon']),
        'successful_dribbles': int(totals['successfulDribbles']),
    }
