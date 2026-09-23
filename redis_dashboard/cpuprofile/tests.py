from unittest import mock

import redis
from django.test import TestCase

from .cpuproflib import diff_commandstats, parse_command, percentile, summarize_monitor
from .models import Capture, Sample


def mon(t, command, client='10.0.0.1'):
    return {'time': t, 'db': 0, 'client_address': client, 'client_port': '1', 'client_type': 'tcp',
            'command': command}


class ParseTests(TestCase):
    def test_value_with_spaces_kept_whole(self):
        c = parse_command(mon(1.0, 'set user:1 hello big world'))
        self.assertEqual((c['command'], c['keyname'], c['val'], c['size']), ('SET', 'user:1', 'hello big world', 15))

    def test_keyless_command(self):
        c = parse_command(mon(1.0, 'PING'))
        self.assertIsNone(c['keyname'])
        self.assertEqual(c['size'], 0)

    def test_percentile_bounds(self):
        self.assertIsNone(percentile([], 0.99))
        self.assertEqual(percentile([5], 0.99), 5)
        self.assertEqual(percentile([1, 2, 3, 4], 0.99), 4)


class SummaryTests(TestCase):
    def test_counts_every_command_case_insensitively(self):
        raw = [mon(1.000, 'get a:1'), mon(1.001, 'GET a:2'), mon(1.003, 'SET b 1', '10.0.0.2'), mon(1.004, 'PING')]
        s = summarize_monitor(raw)
        self.assertEqual(s['captured'], 4)
        self.assertEqual(dict(s['command_mix']), {'GET': 2, 'SET': 1, 'PING': 1})
        self.assertEqual(dict(s['top_prefixes']), {'a:*': 2, '(no prefix)': 1})
        self.assertEqual(s['top_clients'][0], ('10.0.0.1', 3))
        self.assertAlmostEqual(s['window_ms'], 4, places=3)
        self.assertAlmostEqual(s['gap_ms']['0.99'], 2, places=3)

    def test_empty_and_single_sample_do_not_crash(self):
        self.assertEqual(summarize_monitor([])['captured'], 0)
        one = summarize_monitor([mon(1.0, 'PING')])
        self.assertIsNone(one['gap_ms']['0.5'])
        self.assertIsNone(one['monitor_ops_per_sec'])

    def test_commandstats_diff_sorted_by_cost_and_skips_own_probes(self):
        before = {'cmdstat_get': {'calls': 10, 'usec': 10}, 'cmdstat_info': {'calls': 1, 'usec': 50}}
        after = {'cmdstat_get': {'calls': 20, 'usec': 30}, 'cmdstat_keys': {'calls': 1, 'usec': 900},
                 'cmdstat_info': {'calls': 3, 'usec': 150}}
        rows = diff_commandstats(before, after)
        self.assertEqual([r['command'] for r in rows], ['KEYS', 'GET'])
        self.assertEqual(rows[1]['usec_per_call'], 2)


class ViewTests(TestCase):
    def make_capture(self, **kw):
        defaults = dict(host='localhost', port=6379, db=0, amount=10, interval=0, samples_requested=2,
                        max_sample_seconds=1, warn_usec=20, crit_usec=100, status=Capture.DONE)
        return Capture.objects.create(**{**defaults, **kw})

    def test_home_renders_with_empty_db(self):
        r = self.client.get('/')
        self.assertContains(r, 'No captures yet')

    def test_invalid_form_returns_errors(self):
        r = self.client.post('/captures/new', {'host': 'x', 'port': '99999'}, HTTP_HX_REQUEST='true')
        self.assertEqual(r.status_code, 422)
        self.assertContains(r, 'is-invalid', status_code=422)

    def test_connection_error_is_shown(self):
        data = {'host': 'localhost', 'port': 6399, 'db': 0, 'amount': 10, 'samples_requested': 1,
                'interval': 0, 'max_sample_seconds': 1, 'warn_usec': 20, 'crit_usec': 100}
        with mock.patch('redis.Redis.ping', side_effect=redis.ConnectionError('refused')):
            r = self.client.post('/captures/new', data, HTTP_HX_REQUEST='true')
        self.assertContains(r, 'Could not connect', status_code=422)
        self.assertFalse(Capture.objects.exists())

    def test_orphaned_running_capture_marked_interrupted(self):
        c = self.make_capture(status=Capture.RUNNING)
        self.client.get(f'/captures/{c.id}/')
        c.refresh_from_db()
        self.assertEqual(c.status, Capture.INTERRUPTED)

    def test_sample_detail_renders(self):
        c = self.make_capture()
        stats = summarize_monitor([mon(1.0, 'GET a:1'), mon(1.001, 'SET a:2 v')])
        stats.update(elapsed_ms=5, slowlog=[], cpu_pct=42.0, cpu_by_command=[
            {'command': 'GET', 'calls': 1, 'usec': 3, 'usec_per_call': 3.0}], ops_per_sec=400, avg_usec_per_call=3.0)
        Sample.objects.create(capture=c, index=1, stats=stats, avg_usec_per_call=3, cpu_pct=42.0,
                              ops_per_sec=400, level='ok')
        r = self.client.get(f'/captures/{c.id}/samples/1/', HTTP_HX_REQUEST='true')
        self.assertContains(r, 'Where the CPU went')
        self.assertContains(r, '42%')
        # full-page hits redirect to the capture page with the sample preselected
        r = self.client.get(f'/captures/{c.id}/samples/1/')
        self.assertRedirects(r, f'/captures/{c.id}/?sample=1')
