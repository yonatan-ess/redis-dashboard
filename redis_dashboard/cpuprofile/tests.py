import os
import threading
import time
from unittest import mock

import redis
from django.test import SimpleTestCase, TestCase

from . import runner
from .cpuproflib import (connection, diff_commandstats, new_slowlog_entries, parse_command,
                         percentile, snapshot, summarize_monitor, take_sample)
from .forms import CaptureForm
from .models import Capture, Sample
from .templatetags import dash

# integration tests write keys and touch config, so they only run when pointed at a Redis explicitly
REDIS_HOST = os.environ.get('REDIS_HOST')
REDIS_PORT = int(os.environ.get('REDIS_PORT', 6379))

FORM_DATA = {'host': 'localhost', 'port': 6379, 'db': 0, 'amount': 10, 'samples_requested': 2,
             'interval': 0, 'max_sample_seconds': 1, 'warn_usec': 20, 'crit_usec': 100}


def mon(t, command, client='10.0.0.1'):
    return {'time': t, 'db': 0, 'client_address': client, 'client_port': '1', 'client_type': 'tcp',
            'command': command}


def make_capture(**kw):
    defaults = dict(host='localhost', port=6379, db=0, amount=10, interval=0, samples_requested=2,
                    max_sample_seconds=1, warn_usec=20, crit_usec=100, status=Capture.DONE)
    return Capture.objects.create(**{**defaults, **kw})


def fake_stats(avg=3.0):
    stats = summarize_monitor([mon(1.0, 'GET a:1'), mon(1.001, 'SET a:2 v')])
    stats.update(elapsed_ms=5, slowlog=[], cpu_pct=42.0, ops_per_sec=400, avg_usec_per_call=avg,
                 cpu_by_command=[{'command': 'GET', 'calls': 1, 'usec': 3, 'usec_per_call': 3.0}])
    return stats


def redis_available():
    if not REDIS_HOST:
        return False
    try:
        return connection(REDIS_HOST, REDIS_PORT, timeout=1).ping()
    except (redis.RedisError, OSError):
        return False


class ParseTests(SimpleTestCase):
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


class SummaryTests(SimpleTestCase):
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

    def test_largest_payloads_sorted_desc(self):
        s = summarize_monitor([mon(1.0, 'SET a x'), mon(1.1, 'SET b ' + 'y' * 50), mon(1.2, 'SET c zz')])
        self.assertEqual([p['keyname'] for p in s['largest_payloads']], ['b', 'c', 'a'])

    def test_commandstats_diff_sorted_by_cost_and_skips_own_probes(self):
        before = {'cmdstat_get': {'calls': 10, 'usec': 10}, 'cmdstat_info': {'calls': 1, 'usec': 50}}
        after = {'cmdstat_get': {'calls': 20, 'usec': 30}, 'cmdstat_keys': {'calls': 1, 'usec': 900},
                 'cmdstat_info': {'calls': 3, 'usec': 150}}
        rows = diff_commandstats(before, after)
        self.assertEqual([r['command'] for r in rows], ['KEYS', 'GET'])
        self.assertEqual(rows[1]['usec_per_call'], 2)


class SlowlogTests(SimpleTestCase):
    def entry(self, id, duration, command):
        return {'id': id, 'start_time': 0, 'duration': duration, 'command': command,
                'client_address': b'127.0.0.1:1'}

    def test_decodes_bytes_and_str_and_keeps_only_new_entries(self):
        # redis-py 5 returns bytes, 8 returns str
        conn = mock.Mock()
        conn.slowlog_get.return_value = [
            self.entry(3, 500, b'KEYS *'), self.entry(2, 900, 'HGETALL big'), self.entry(1, 9999, 'OLD')]
        rows = new_slowlog_entries(conn, since_id=1)
        self.assertEqual([(r['command'], r['duration_us']) for r in rows], [('HGETALL big', 900), ('KEYS *', 500)])
        self.assertEqual(rows[0]['client'], '127.0.0.1:1')

    def test_unavailable_slowlog_returns_none(self):
        conn = mock.Mock()
        conn.slowlog_get.side_effect = redis.ResponseError('NOPERM')
        self.assertIsNone(new_slowlog_entries(conn, since_id=0))
        self.assertIsNone(new_slowlog_entries(conn, since_id=None))


class RestrictedServerTests(SimpleTestCase):
    def test_snapshot_tolerates_denied_commands(self):
        conn = mock.Mock()
        conn.info.side_effect = redis.ResponseError('NOPERM')
        conn.slowlog_get.side_effect = redis.ResponseError('NOPERM')
        snap = snapshot(conn)
        self.assertEqual((snap['commandstats'], snap['cpu'], snap['slowlog_id']), (None, None, None))

    def test_take_sample_falls_back_to_monitor_estimate(self):
        conn = mock.Mock()
        conn.info.side_effect = redis.ResponseError('NOPERM')
        conn.slowlog_get.side_effect = redis.ResponseError('NOPERM')
        with mock.patch('cpuprofile.cpuproflib.get_monitor_data',
                        return_value=[mon(1.0, 'GET a'), mon(1.5, 'GET b'), mon(2.0, 'GET c')]):
            s = take_sample(conn, amount=3, max_seconds=1)
        self.assertIsNone(s['cpu_by_command'])
        self.assertIsNone(s['avg_usec_per_call'])
        self.assertIsNone(s['cpu_pct'])
        self.assertAlmostEqual(s['ops_per_sec'], 2)


class FilterTests(SimpleTestCase):
    def test_compact(self):
        self.assertEqual([dash.compact(v) for v in (None, 7, 1234, 283_000, 2_500_000)],
                         ['—', '7', '1.2k', '283k', '2.5M'])

    def test_usec_scales_units(self):
        self.assertEqual([dash.usec(v) for v in (None, 0.4, 250, 3530, 2_000_000)],
                         ['—', '0.4 µs', '250 µs', '3.53 ms', '2.00 s'])

    def test_pct_and_ratio(self):
        self.assertEqual((dash.pct(None), dash.pct(4.25), dash.pct(94.4)), ('—', '4.2%', '94%'))
        self.assertEqual((dash.ratio(5, 10), dash.ratio(0.01, 10), dash.ratio(1, 0), dash.ratio(None, 5)), (50, 2, 0, 0))

    def test_get_uses_string_keys(self):
        self.assertEqual(dash.get({'0.5': 1.0}, 0.5), 1.0)
        self.assertIsNone(dash.get(None, 'x'))


class FormTests(SimpleTestCase):
    def test_defaults_are_valid(self):
        self.assertTrue(CaptureForm(FORM_DATA).is_valid())

    def test_warn_must_not_exceed_crit(self):
        form = CaptureForm({**FORM_DATA, 'warn_usec': 200, 'crit_usec': 100})
        self.assertFalse(form.is_valid())
        self.assertIn('crit_usec', form.errors)


class RunnerTests(TestCase):
    def setUp(self):
        # the worker closes its DB connection when done, which would break the test transaction
        for name in ('close_old_connections', 'db_connection'):
            patcher = mock.patch.object(runner, name)
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_capture(self, capture, **patch_kw):
        runner._live.add(capture.id)
        with mock.patch.object(runner, 'take_sample', **patch_kw):
            runner._run(capture.id, mock.Mock())
        capture.refresh_from_db()
        return capture

    def test_records_samples_with_levels(self):
        c = make_capture(status=Capture.RUNNING, samples_requested=3)
        c = self.run_capture(c, side_effect=[fake_stats(5), fake_stats(50), fake_stats(500)])
        self.assertEqual(c.status, Capture.DONE)
        self.assertEqual(list(c.samples.values_list('level', flat=True)), ['ok', 'warn', 'crit'])
        self.assertIsNotNone(c.finished_at)
        self.assertFalse(runner.is_live(c.id))

    def test_stop_request_ends_capture(self):
        c = make_capture(status=Capture.RUNNING, samples_requested=5, stop_requested=True)
        c = self.run_capture(c, return_value=fake_stats())
        self.assertEqual(c.status, Capture.STOPPED)
        self.assertEqual(c.samples.count(), 0)

    def test_redis_failure_is_recorded(self):
        c = make_capture(status=Capture.RUNNING)
        c = self.run_capture(c, side_effect=redis.ConnectionError('Connection reset by peer'))
        self.assertEqual(c.status, Capture.FAILED)
        self.assertIn('Connection reset by peer', c.error)


class ViewTests(TestCase):
    def test_home_renders_with_empty_db(self):
        self.assertContains(self.client.get('/'), 'No captures yet')

    def test_old_urls_redirect_home(self):
        for url in ('/traces/', '/capturecommandstosql'):
            self.assertRedirects(self.client.get(url), '/', fetch_redirect_response=False)

    def test_invalid_form_returns_errors(self):
        r = self.client.post('/captures/new', {'host': 'x', 'port': '99999'}, HTTP_HX_REQUEST='true')
        self.assertContains(r, 'is-invalid', status_code=422)

    def test_connection_error_is_shown(self):
        with mock.patch('redis.Redis.ping', side_effect=redis.ConnectionError('refused')):
            r = self.client.post('/captures/new', FORM_DATA, HTTP_HX_REQUEST='true')
        self.assertContains(r, 'Could not connect', status_code=422)
        self.assertFalse(Capture.objects.exists())

    def test_start_capture_redirects_and_does_not_store_password(self):
        conn = mock.Mock()
        conn.config_get.return_value = {'slowlog-log-slower-than': '10000'}
        with mock.patch('cpuprofile.views.connection', return_value=conn), \
                mock.patch.object(runner, 'start') as start:
            r = self.client.post('/captures/new', {**FORM_DATA, 'password': 's3cret'}, HTTP_HX_REQUEST='true')
        capture = Capture.objects.get()
        self.assertEqual(r.headers['HX-Redirect'], f'/captures/{capture.id}/')
        self.assertEqual(capture.slowlog_threshold_us, 10000)
        start.assert_called_once_with(capture, conn)
        self.assertNotIn('s3cret', str(Capture.objects.values().get()))

    def test_only_one_running_capture(self):
        running = make_capture(status=Capture.RUNNING)
        runner._live.add(running.id)
        self.addCleanup(runner._live.discard, running.id)
        r = self.client.post('/captures/new', FORM_DATA, HTTP_HX_REQUEST='true')
        self.assertContains(r, 'still running', status_code=422)

    def test_orphaned_running_capture_marked_interrupted(self):
        c = make_capture(status=Capture.RUNNING)
        self.client.get(f'/captures/{c.id}/')
        c.refresh_from_db()
        self.assertEqual(c.status, Capture.INTERRUPTED)

    def test_live_partial_polls_only_while_running(self):
        running = make_capture(status=Capture.RUNNING)
        runner._live.add(running.id)
        self.addCleanup(runner._live.discard, running.id)
        self.assertContains(self.client.get(f'/captures/{running.id}/live'), 'every 2s')
        done = make_capture()
        self.assertNotContains(self.client.get(f'/captures/{done.id}/live'), 'every 2s')

    def test_stop_sets_flag(self):
        c = make_capture(status=Capture.RUNNING)
        runner._live.add(c.id)
        self.addCleanup(runner._live.discard, c.id)
        r = self.client.post(f'/captures/{c.id}/stop', HTTP_HX_REQUEST='true')
        self.assertContains(r, 'Stopping')
        c.refresh_from_db()
        self.assertTrue(c.stop_requested)

    def test_delete(self):
        running = make_capture(status=Capture.RUNNING)
        runner._live.add(running.id)
        self.addCleanup(runner._live.discard, running.id)
        self.assertEqual(self.client.post(f'/captures/{running.id}/delete').status_code, 409)

        done = make_capture()
        Sample.objects.create(capture=done, index=1, stats=fake_stats(), level='ok')
        r = self.client.post(f'/captures/{done.id}/delete', HTTP_HX_REQUEST='true')
        self.assertEqual(r.headers['HX-Redirect'], '/')
        self.assertFalse(Capture.objects.filter(id=done.id).exists())
        self.assertFalse(Sample.objects.filter(capture_id=done.id).exists())

    def test_sample_detail_renders(self):
        c = make_capture()
        Sample.objects.create(capture=c, index=1, stats=fake_stats(), avg_usec_per_call=3, cpu_pct=42.0,
                              ops_per_sec=400, level='ok')
        r = self.client.get(f'/captures/{c.id}/samples/1/', HTTP_HX_REQUEST='true')
        self.assertContains(r, 'Where the CPU went')
        self.assertContains(r, '42%')
        # full-page hits redirect to the capture page with the sample preselected
        r = self.client.get(f'/captures/{c.id}/samples/1/')
        self.assertRedirects(r, f'/captures/{c.id}/?sample=1')

    def test_missing_sample_404s(self):
        c = make_capture()
        self.assertEqual(self.client.get(f'/captures/{c.id}/samples/9/', HTTP_HX_REQUEST='true').status_code, 404)


class RedisIntegrationTests(SimpleTestCase):
    """Runs against a real Redis; set REDIS_HOST (and REDIS_PORT) to enable. Use a throwaway instance."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not redis_available():
            raise cls.skipTest(cls, 'set REDIS_HOST to a throwaway Redis to run')
        cls.conn = connection(REDIS_HOST, REDIS_PORT, timeout=2)
        cls.slowlog_before = cls.conn.config_get('slowlog-log-slower-than')['slowlog-log-slower-than']
        cls.conn.config_set('slowlog-log-slower-than', 0)  # log everything so SLOWLOG is exercised

    @classmethod
    def tearDownClass(cls):
        cls.conn.config_set('slowlog-log-slower-than', cls.slowlog_before)
        cls.conn.delete(*[f'rdtest:{i}' for i in range(20)])
        super().tearDownClass()

    def generate_traffic(self, stop):
        c = connection(REDIS_HOST, REDIS_PORT)
        time.sleep(0.1)  # let MONITOR attach first
        i = 0
        while not stop.is_set():
            c.set(f'rdtest:{i % 20}', 'hello world')
            c.get(f'rdtest:{i % 20}')
            i += 1

    def sample(self, amount=200):
        stop = threading.Event()
        t = threading.Thread(target=self.generate_traffic, args=(stop,), daemon=True)
        t.start()
        try:
            return take_sample(self.conn, amount=amount, max_seconds=5)
        finally:
            stop.set()
            t.join()

    def test_take_sample_against_real_redis(self):
        s = self.sample()
        self.assertEqual(s['captured'], 200)
        self.assertTrue({'SET', 'GET'} <= {cmd for cmd, _ in s['command_mix']})
        self.assertEqual(dict(s['top_prefixes'])['rdtest:*'], sum(n for cmd, n in s['command_mix'] if cmd in ('SET', 'GET')))
        costed = {r['command']: r for r in s['cpu_by_command']}
        self.assertGreater(costed['SET']['calls'], 0)
        self.assertGreater(s['avg_usec_per_call'], 0)
        self.assertGreater(s['ops_per_sec'], 0)
        self.assertIsNotNone(s['cpu_pct'])
        self.assertLessEqual(s['cpu_pct'], 100)
        self.assertTrue(s['slowlog'], 'threshold is 0, so every command should be logged')
        self.assertTrue(all(isinstance(e['command'], str) for e in s['slowlog']))

    def test_idle_server_times_out_instead_of_hanging(self):
        conn = connection(REDIS_HOST, REDIS_PORT, timeout=0.5)
        started = time.monotonic()
        s = take_sample(conn, amount=1_000_000, max_seconds=0.5)
        self.assertLess(time.monotonic() - started, 5)
        self.assertLess(s['captured'], 1_000_000)
