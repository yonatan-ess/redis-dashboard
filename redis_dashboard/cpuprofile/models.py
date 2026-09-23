from django.db import models


class Capture(models.Model):
    RUNNING, DONE, STOPPED, FAILED, INTERRUPTED = 'running', 'done', 'stopped', 'failed', 'interrupted'
    STATUSES = [(s, s) for s in (RUNNING, DONE, STOPPED, FAILED, INTERRUPTED)]

    host = models.CharField(max_length=255)
    port = models.PositiveIntegerField()
    db = models.PositiveIntegerField()
    username = models.CharField(max_length=255, blank=True)
    amount = models.PositiveIntegerField()
    interval = models.FloatField()
    samples_requested = models.PositiveIntegerField()
    max_sample_seconds = models.FloatField()
    warn_usec = models.FloatField()
    crit_usec = models.FloatField()
    slowlog_threshold_us = models.IntegerField(null=True)
    status = models.CharField(max_length=20, choices=STATUSES, default=RUNNING)
    stop_requested = models.BooleanField(default=False)
    error = models.TextField(blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True)

    class Meta:
        ordering = ['-started_at']

    @property
    def target(self):
        return f'{self.host}:{self.port}/{self.db}'

    @property
    def is_running(self):
        return self.status == self.RUNNING

    def level_for(self, avg_usec):
        if avg_usec is None:
            return 'unknown'
        if avg_usec >= self.crit_usec:
            return 'crit'
        return 'warn' if avg_usec >= self.warn_usec else 'ok'


class Sample(models.Model):
    capture = models.ForeignKey(Capture, related_name='samples', on_delete=models.CASCADE)
    index = models.PositiveIntegerField()
    taken_at = models.DateTimeField(auto_now_add=True)
    stats = models.JSONField()
    avg_usec_per_call = models.FloatField(null=True)
    cpu_pct = models.FloatField(null=True)
    ops_per_sec = models.FloatField(null=True)
    level = models.CharField(max_length=10)

    class Meta:
        ordering = ['index']
