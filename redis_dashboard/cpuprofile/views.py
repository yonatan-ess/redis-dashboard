import redis
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from . import runner
from .cpuproflib import connection, slowlog_threshold_us
from .forms import CaptureForm
from .models import Capture, Sample


def _captures():
    return Capture.objects.annotate(
        n_samples=Count('samples'),
        n_warn=Count('samples', filter=Q(samples__level='warn')),
        n_crit=Count('samples', filter=Q(samples__level='crit')),
    )


def home(request):
    runner.reap_orphans()
    return render(request, 'cpuprofile/home.html', {
        'form': CaptureForm(), 'captures': _captures()[:50],
    })


def _form_response(request, form):
    return render(request, 'cpuprofile/_capture_form.html', {'form': form}, status=422)


@require_POST
def new_capture(request):
    runner.reap_orphans()
    form = CaptureForm(request.POST)
    if not form.is_valid():
        return _form_response(request, form)
    d = form.cleaned_data

    running = Capture.objects.filter(status=Capture.RUNNING).first()
    if running:
        form.add_error(None, f'Capture #{running.id} on {running.target} is still running — stop it first.')
        return _form_response(request, form)

    conn = connection(d['host'], d['port'], d['db'], d['username'], d['password'],
                      timeout=d['max_sample_seconds'])
    try:
        conn.ping()
    except (redis.RedisError, OSError) as e:
        form.add_error(None, f'Could not connect to {d["host"]}:{d["port"]} — {e}')
        return _form_response(request, form)

    capture = Capture.objects.create(
        slowlog_threshold_us=slowlog_threshold_us(conn),
        **{k: v for k, v in d.items() if k != 'password'})
    runner.start(capture, conn)

    url = reverse('capture', args=[capture.id])
    if request.htmx:
        return HttpResponse(status=204, headers={'HX-Redirect': url})
    return redirect(url)


def _timeline(capture):
    return [{'i': s.index, 'cpu': s.cpu_pct, 'ops': s.ops_per_sec, 'avg': s.avg_usec_per_call,
             'level': s.level} for s in capture.samples.all()]


def _live_context(capture):
    samples = list(capture.samples.all())
    done = len(samples)
    return {
        'capture': capture,
        'samples': samples,
        'timeline': _timeline(capture),
        'progress': round(done / capture.samples_requested * 100) if capture.samples_requested else 0,
        'counts': {lvl: sum(s.level == lvl for s in samples) for lvl in ('ok', 'warn', 'crit', 'unknown')},
    }


def capture_detail(request, pk):
    runner.reap_orphans()
    capture = get_object_or_404(Capture, pk=pk)
    ctx = _live_context(capture)
    ctx['selected'] = request.GET.get('sample', '')
    return render(request, 'cpuprofile/capture.html', ctx)


def capture_live(request, pk):
    runner.reap_orphans()
    capture = get_object_or_404(Capture, pk=pk)
    ctx = _live_context(capture)
    ctx['selected'] = request.GET.get('sample', '')
    return render(request, 'cpuprofile/_live.html', ctx)


def sample_detail(request, pk, index):
    sample = get_object_or_404(Sample.objects.select_related('capture'), capture_id=pk, index=index)
    if not request.htmx:
        return redirect(f"{reverse('capture', args=[pk])}?sample={index}")
    capture = sample.capture
    stats = sample.stats
    max_usec = max((r['usec'] for r in stats.get('cpu_by_command') or []), default=0)
    return render(request, 'cpuprofile/_sample.html', {
        'capture': capture,
        'sample': sample,
        's': stats,
        'max_usec': max_usec,
    })


@require_POST
def stop_capture(request, pk):
    Capture.objects.filter(pk=pk, status=Capture.RUNNING).update(stop_requested=True)
    return capture_live(request, pk)


@require_POST
def delete_capture(request, pk):
    capture = get_object_or_404(Capture, pk=pk)
    if capture.is_running:
        return HttpResponse('Stop the capture before deleting it.', status=409)
    capture.delete()
    if request.htmx:
        return HttpResponse(status=204, headers={'HX-Redirect': reverse('home')})
    return redirect('home')
