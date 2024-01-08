from django.shortcuts import render
from django.http import HttpResponse, HttpResponseRedirect
from .cpuproflib import *
from django.views.generic import View
import json
from datetime import datetime
import time
from cpuprofile.models import Traces, CaptureStatus
from django.views.generic.list import ListView
from django.views.generic.detail import DetailView
import threading

finised_capture = False


def index(request):
    return HttpResponseRedirect("/traces/")


class captureCommandsToSQLite(View):
    def get(self, request, *args, **kwargs):
        return render(request, 'capturecommandstosqlite.html')


class capture(View):
    def post(self, request, *args, **kwargs):
        conn = connection(
            redis_host=request.POST.get('host'),
            password=request.POST.get('password'),
            username=request.POST.get('username'),
            db=request.POST.get('db'),
            port=request.POST.get('port'),
        )
        t = threading.Thread(target=savetosqlite,
                             args=(conn,),
                             kwargs={
                                 'amount': request.POST.get('amount'),
                                 'interval': request.POST.get('interval'),
                                 'captures': request.POST.get('captures'),
                             })
        t.setDaemon(True)
        t.start()

        return HttpResponse(status=204)


class TraceListView(ListView):
    model = Traces


class OnlyTraces(View):
    def get(self, request, *args, **kwargs):
        traces = Traces.objects.all()
        captureStatus = CaptureStatus.objects.get(id=1)
        return render(request, 'cpuprofile/only_traces.html', {'traces': traces,
                                                               'captureStatus': captureStatus, })


class TraceDetailView(DetailView):
    model = Traces

    def get(self, request, *args, **kwargs):
        trace = Traces.objects.get(pk=self.kwargs['pk'])
        trace_json = json.loads(trace.traceSum)
        time = trace.time
        return render(request, 'cpuprofile/trace_detail.html', {
            'trace_json': trace_json,
            'time': time,
        })


def savetosqlite(conn, amount=500, interval=0.3, captures=36):
    Traces.objects.all().delete()
    CaptureStatus(captureStatus=False, id=1).save()
    for i in range(0, int(captures)):

        data_to_store = merge_results(conn, amount)

        if data_to_store['percentilesCommandsDuration'][0.99] < 0.3:
            color = 'bg-success'
        elif data_to_store['percentilesCommandsDuration'][0.99] < 1:
            color = 'bg-warning'
        else:
            color = 'bg-danger'

        data_to_store_json = json.dumps(data_to_store)
        trace = Traces(time=datetime.utcnow().strftime('%F%T.%f')[
                       :-3], traceSum=data_to_store_json, color=color)
        trace.save()
        time.sleep(float(interval))
    CaptureStatus(captureStatus=True, id=1).save()

    return
