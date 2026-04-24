"""Load real player names + Cluj team attribution from a Wyscout players export JSON.

Input file format: `{ "meta": {...}, "players": [{ "wyId": int, "shortName": str, "firstName": str, "lastName": str, "currentTeamId": int, "role": {...} }, ...] }`
"""
import json
from collections import Counter
from pathlib import Path

from django.core.management.base import BaseCommand

from insights.models import Player


class Command(BaseCommand):
    help = 'Load player names and Cluj team attribution from a Wyscout players export.'

    def add_arguments(self, parser):
        parser.add_argument('path', type=str, help='Path to players.json')
        parser.add_argument('--team-id', type=int, default=None,
                            help='Cluj teamId. If omitted, inferred from currently-flagged players.')

    def handle(self, path, team_id=None, **opts):
        fp = Path(path)
        if not fp.is_file():
            self.stderr.write(f'File not found: {fp}')
            return

        data = json.loads(fp.read_text(encoding='utf-8'))
        players_in = data.get('players') or []
        self.stdout.write(f'Loaded {len(players_in)} players from {fp.name}')
        by_id = {p['wyId']: p for p in players_in}

        if team_id is None:
            flagged_ids = list(Player.objects.filter(is_cluj=True).values_list('wy_id', flat=True))
            teams = Counter()
            for pid in flagged_ids:
                p = by_id.get(pid)
                if p:
                    teams[p['currentTeamId']] += 1
            if not teams:
                self.stderr.write('Cannot infer Cluj teamId — pass --team-id explicitly.')
                return
            team_id = teams.most_common(1)[0][0]
            self.stdout.write(f'Inferred Cluj teamId = {team_id} ({teams[team_id]} hits)')

        # Update all existing Players
        updated_names = 0
        reflag_cluj = 0
        reflag_not_cluj = 0
        for player in Player.objects.all():
            p = by_id.get(player.wy_id)
            if not p:
                continue
            new_name = (p.get('shortName') or f"{p.get('firstName','')} {p.get('lastName','')}").strip()
            new_is_cluj = (p.get('currentTeamId') == team_id)
            changed = False
            if new_name and new_name != player.name:
                player.name = new_name
                updated_names += 1
                changed = True
            if player.is_cluj != new_is_cluj:
                player.is_cluj = new_is_cluj
                if new_is_cluj:
                    reflag_cluj += 1
                else:
                    reflag_not_cluj += 1
                changed = True
            if not player.position_code and p.get('role'):
                player.position_code = (p['role'].get('code2') or '').lower()
                changed = True
            if changed:
                player.save()

        cluj_count = Player.objects.filter(is_cluj=True).count()
        self.stdout.write(self.style.SUCCESS(
            f'Updated {updated_names} names. Re-flagged +{reflag_cluj} -{reflag_not_cluj}. Total Cluj: {cluj_count}.'
        ))
