from django.db import models


class Match(models.Model):
    wy_id = models.BigIntegerField(primary_key=True)
    label = models.CharField(max_length=200)
    home_team = models.CharField(max_length=100)
    away_team = models.CharField(max_length=100)
    home_score = models.IntegerField()
    away_score = models.IntegerField()
    cluj_is_home = models.BooleanField()
    cluj_goals = models.IntegerField()
    opp_goals = models.IntegerField()
    date = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ['wy_id']

    @property
    def result(self):
        if self.cluj_goals > self.opp_goals:
            return 'W'
        if self.cluj_goals < self.opp_goals:
            return 'L'
        return 'D'

    @property
    def opponent(self):
        return self.away_team if self.cluj_is_home else self.home_team


class Player(models.Model):
    wy_id = models.BigIntegerField(primary_key=True)
    name = models.CharField(max_length=100, default='')
    is_cluj = models.BooleanField(default=False)
    position_code = models.CharField(max_length=10, blank=True, default='')
    appearances = models.IntegerField(default=0)

    def display_name(self):
        return self.name or f'Player {self.wy_id}'


class PlayerMatchStats(models.Model):
    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name='stats')
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name='stats')
    minutes = models.IntegerField()
    position_code = models.CharField(max_length=10, blank=True, default='')
    raw = models.JSONField()

    class Meta:
        unique_together = [('match', 'player')]
