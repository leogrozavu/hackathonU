import json
import re
from collections import Counter
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from insights.models import Match, Player, PlayerMatchStats


FILENAME_RE = re.compile(
    r'^(?P<home>.+?) - (?P<away>.+?), (?P<hs>\d+)-(?P<as>\d+)(?:_(?P<wyid>\d+))?_players_stats\.json$'
)


class Command(BaseCommand):
    help = 'Ingest all *Universitatea Cluj*_players_stats.json files from a folder into DB.'

    def add_arguments(self, parser):
        parser.add_argument('folder', type=str)
        parser.add_argument('--reset', action='store_true', help='Delete existing Match/Player/Stats first')

    def handle(self, folder, reset=False, **opts):
        folder = Path(folder)
        if not folder.is_dir():
            self.stderr.write(f'Not a folder: {folder}')
            return

        cluj = settings.CLUJ_NAME

        if reset:
            self.stdout.write('Wiping existing data...')
            PlayerMatchStats.objects.all().delete()
            Match.objects.all().delete()
            Player.objects.all().delete()

        files = sorted(p for p in folder.glob('*_players_stats.json') if cluj in p.name)
        self.stdout.write(f'Found {len(files)} Cluj match files')

        player_match_count = Counter()

        for fp in files:
            m = FILENAME_RE.match(fp.name)
            if not m:
                self.stdout.write(f'  SKIP (regex miss): {fp.name}')
                continue

            home = m.group('home')
            away = m.group('away')
            hs = int(m.group('hs'))
            aw = int(m.group('as'))
            wyid_from_name = m.group('wyid')

            try:
                data = json.loads(fp.read_text(encoding='utf-8'))
            except Exception as e:
                self.stdout.write(f'  SKIP (json error): {fp.name} {e}')
                continue

            players = data.get('players') or []
            if wyid_from_name:
                match_id = int(wyid_from_name)
            elif players and players[0].get('matchId'):
                match_id = int(players[0]['matchId'])
            else:
                self.stdout.write(f'  SKIP (no match id): {fp.name}')
                continue

            cluj_is_home = (home == cluj)
            cluj_goals = hs if cluj_is_home else aw
            opp_goals = aw if cluj_is_home else hs

            label = f'{home} {hs}-{aw} {away}'

            Match.objects.update_or_create(
                wy_id=match_id,
                defaults=dict(
                    label=label,
                    home_team=home,
                    away_team=away,
                    home_score=hs,
                    away_score=aw,
                    cluj_is_home=cluj_is_home,
                    cluj_goals=cluj_goals,
                    opp_goals=opp_goals,
                ),
            )
            match = Match.objects.get(wy_id=match_id)

            new_stats = 0
            for p in players:
                total = p.get('total') or {}
                minutes = total.get('minutesOnField') or 0
                if minutes <= 0:
                    continue
                pid = p['playerId']
                positions = p.get('positions') or []
                pos_code = ''
                if positions:
                    pos_code = (positions[0].get('position') or {}).get('code', '') or ''

                player_obj, _ = Player.objects.get_or_create(wy_id=pid)
                PlayerMatchStats.objects.update_or_create(
                    match=match,
                    player=player_obj,
                    defaults=dict(minutes=minutes, position_code=pos_code, raw=p),
                )
                player_match_count[pid] += 1
                new_stats += 1
            self.stdout.write(f'  {label}  ({match_id}) -> {new_stats} players')

        self.stdout.write('Flagging is_cluj (appearances >= 4)...')
        total_matches = Match.objects.count()
        for pid, count in player_match_count.items():
            Player.objects.filter(wy_id=pid).update(
                appearances=count,
                is_cluj=(count >= 4),
            )
        cluj_count = Player.objects.filter(is_cluj=True).count()
        self.stdout.write(self.style.SUCCESS(
            f'Done. Matches: {total_matches}. Cluj players flagged: {cluj_count}.'
        ))
