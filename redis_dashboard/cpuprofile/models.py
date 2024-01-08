from django.db import models

# Create your models here.


class Traces(models.Model):
    time = models.CharField(max_length=100)
    traceSum = models.JSONField()
    color = models.CharField(max_length=100, default='0000000')


class CaptureStatus(models.Model):
    captureStatus = models.BooleanField(default=False)
    captureTime = models.CharField(max_length=100, default='00:00:00')
    captureDate = models.CharField(max_length=100, default='00/00/00')
