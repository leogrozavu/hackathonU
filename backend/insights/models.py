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
    is_cluj = models.BooleanField(default=False)  # anyone who played for Cluj this season
    in_current_squad = models.BooleanField(default=False)  # currently at Cluj per players.json snapshot
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


class TrainingSession(models.Model):
    """GPS / wearable device data per training session."""
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name='training_sessions')
    date = models.DateField(null=True, blank=True)
    week = models.IntegerField(null=True, blank=True)
    session_name = models.CharField(max_length=255)
    session_type = models.CharField(max_length=40, blank=True, default='')  # REZISTENTA / FORTA / TACTIC / REACTIVITATE / ...
    duration_min = models.FloatField(default=0)
    distance_m = models.FloatField(default=0)
    work_rate = models.FloatField(default=0)  # m / min
    accel_low_pos = models.IntegerField(default=0)   # 3-4 m/s^2
    accel_low_neg = models.IntegerField(default=0)   # -4 to -3 m/s^2
    accel_high_pos = models.IntegerField(default=0)  # 4-10 m/s^2
    accel_high_neg = models.IntegerField(default=0)  # -10 to -4 m/s^2
    high_int_acc_m = models.FloatField(default=0)
    high_int_dec_m = models.FloatField(default=0)
    speed_15_20_m = models.FloatField(default=0)   # HSR
    speed_20_25_m = models.FloatField(default=0)   # sprint
    speed_25_50_m = models.FloatField(default=0)   # max sprint
    power_avg_wkg = models.FloatField(default=0)
    sprints_per_min = models.FloatField(default=0)

    class Meta:
        unique_together = [('player', 'session_name')]
        indexes = [models.Index(fields=['player', 'date'])]
        ordering = ['date', 'session_name']
