# Generated by Django 4.2.8 on 2024-01-08 12:42

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cpuprofile', '0002_remove_traces_cpuutil_traces_finished_capture'),
    ]

    operations = [
        migrations.CreateModel(
            name='CaptureStatus',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('captureStatus', models.BooleanField(default=False)),
                ('captureTime', models.CharField(default='00:00:00', max_length=100)),
                ('captureDate', models.CharField(default='00/00/00', max_length=100)),
            ],
        ),
        migrations.RemoveField(
            model_name='traces',
            name='finished_capture',
        ),
    ]
