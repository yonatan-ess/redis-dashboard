import time
from collections import Counter

import redis

TOP_N = 15
# MONITOR can't time commands; these are gaps between arrivals, not durations
GAP_PERCENTILES = [0.5, 0.9, 0.99]
# our own probing commands, kept out of the per-command CPU table
OWN_COMMANDS = {'monitor', 'slowlog|get', 'info'}


def connection(host='localhost', port=6379, db=0, username=None, password=None, timeout=5):
    return redis.Redis(host=host, port=port, db=db,
                       username=username or None, password=password or None,
                       socket_connect_timeout=timeout, socket_timeout=timeout,
                       decode_responses=True)


def _decode(v):
    return v.decode(errors='replace') if isinstance(v, bytes) else v


def get_monitor_data(conn, amount, max_seconds):
    commands = []
    deadline = time.monotonic() + max_seconds
    try:
        with conn.monitor() as m:
            for command in m.listen():
                commands.append(command)
                if len(commands) >= amount or time.monotonic() > deadline:
                    break
    except redis.TimeoutError:
        pass  # idle server; keep what we got
    return commands


def parse_command(raw):
    parts = raw['command'].split(' ', 2)
    return {
        'time': float(raw['time']),
        'command': parts[0].upper(),
        'keyname': parts[1] if len(parts) > 1 else None,
        'size': len(parts[2]) if len(parts) > 2 else 0,
        'val': parts[2][:200] if len(parts) > 2 else None,
        'client': raw.get('client_address') or raw.get('client_type'),
    }


def percentile(sorted_values, p):
    if not sorted_values:
        return None
    return sorted_values[min(int(len(sorted_values) * p), len(sorted_values) - 1)]


def key_prefix(key):
    return key.split(':', 1)[0] + ':*' if ':' in key else '(no prefix)'


def summarize_monitor(raw_commands):
    commands = [parse_command(c) for c in raw_commands]
    gaps = sorted((b['time'] - a['time']) * 1000 for a, b in zip(commands, commands[1:]))
    window = commands[-1]['time'] - commands[0]['time'] if len(commands) > 1 else 0
    keyed = [c for c in commands if c['keyname']]
    largest = sorted((c for c in commands if c['size']), key=lambda c: c['size'], reverse=True)
    return {
        'captured': len(commands),
        'window_ms': window * 1000,
        'monitor_ops_per_sec': (len(commands) - 1) / window if window else None,
        'command_mix': Counter(c['command'] for c in commands).most_common(),
        'top_keys': Counter(c['keyname'] for c in keyed).most_common(TOP_N),
        'top_prefixes': Counter(key_prefix(c['keyname']) for c in keyed).most_common(TOP_N),
        'top_clients': Counter(c['client'] for c in commands).most_common(TOP_N),
        'largest_payloads': [
            {k: c[k] for k in ('command', 'keyname', 'size', 'val')} for c in largest[:10]],
        'gap_ms': {str(p): percentile(gaps, p) for p in GAP_PERCENTILES},
    }


def snapshot(conn):
    """Cumulative server counters; diff two snapshots to get a sample's real cost."""
    snap = {'at': time.monotonic(), 'commandstats': None, 'cpu': None, 'slowlog_id': None}
    try:
        snap['commandstats'] = conn.info('commandstats')
    except redis.ResponseError:
        pass  # INFO restricted by ACL / managed Redis
    try:
        cpu = conn.info('cpu')
        # commands run on the main thread, so that's what saturates first
        snap['cpu'] = (cpu.get('used_cpu_sys_main_thread', cpu['used_cpu_sys'])
                       + cpu.get('used_cpu_user_main_thread', cpu['used_cpu_user']))
    except (redis.ResponseError, KeyError):
        pass
    try:
        latest = conn.slowlog_get(1)
        snap['slowlog_id'] = latest[0]['id'] if latest else -1
    except redis.ResponseError:
        pass
    return snap


def diff_commandstats(before, after):
    rows = []
    for name, stat in after.items():
        cmd = name.removeprefix('cmdstat_')
        if cmd in OWN_COMMANDS:
            continue
        prev = before.get(name, {'calls': 0, 'usec': 0})
        calls, usec = stat['calls'] - prev['calls'], stat['usec'] - prev['usec']
        if calls > 0:
            rows.append({'command': cmd.upper(), 'calls': calls, 'usec': usec,
                         'usec_per_call': usec / calls})
    return sorted(rows, key=lambda r: r['usec'], reverse=True)


def new_slowlog_entries(conn, since_id):
    if since_id is None:
        return None
    try:
        entries = conn.slowlog_get(128)
    except redis.ResponseError:
        return None
    rows = [{
        'id': e['id'],
        'start_time': e['start_time'],
        'duration_us': e['duration'],
        'command': _decode(e['command'])[:200],
        'client': _decode(e.get('client_address', '')),
    } for e in entries if e['id'] > since_id]
    return sorted(rows, key=lambda r: r['duration_us'], reverse=True)[:TOP_N]


def slowlog_threshold_us(conn):
    try:
        return int(conn.config_get('slowlog-log-slower-than')['slowlog-log-slower-than'])
    except (redis.ResponseError, KeyError, ValueError):
        return None  # CONFIG is often disabled on managed Redis


def take_sample(conn, amount, max_seconds):
    before = snapshot(conn)
    raw = get_monitor_data(conn, amount, max_seconds)
    after = snapshot(conn)
    elapsed = after['at'] - before['at']

    stats = summarize_monitor(raw)
    stats['elapsed_ms'] = elapsed * 1000
    stats['slowlog'] = new_slowlog_entries(conn, before['slowlog_id'])
    # rusage granularity overshoots on short windows; one thread can't exceed 100%
    stats['cpu_pct'] = min((after['cpu'] - before['cpu']) / elapsed * 100, 100) \
        if before['cpu'] is not None and after['cpu'] is not None and elapsed else None

    if before['commandstats'] is not None and after['commandstats'] is not None:
        rows = diff_commandstats(before['commandstats'], after['commandstats'])
        calls = sum(r['calls'] for r in rows)
        usec = sum(r['usec'] for r in rows)
        stats['cpu_by_command'] = rows
        stats['ops_per_sec'] = calls / elapsed if elapsed else None
        stats['avg_usec_per_call'] = usec / calls if calls else None
    else:
        stats['cpu_by_command'] = None
        stats['ops_per_sec'] = stats['monitor_ops_per_sec']
        stats['avg_usec_per_call'] = None
    return stats
