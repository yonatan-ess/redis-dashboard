# redis-dashboard
redis cpu profiling 


# Description
Have you ever hit 100% cpu on your redis host ?  
are you tired of looking into the matrix [redis monitor](https://redis.io/commands/monitor/) ?  

hopefully this tool can help

It takes a series of short samples and, for each one, records:

- **Real CPU cost per command type**: the change in `INFO commandstats` (calls, total µs, µs/call)
- **Main-thread CPU %**: the change in `INFO cpu`
- **Slow commands**: new `SLOWLOG` entries
- **Traffic mix**: from `MONITOR` (command mix, hot keys, key prefixes, clients, largest payloads)

Samples are colored by average µs per call, with thresholds you set per capture. Captures are kept in SQLite until you delete them.

> [!NOTE]
> `MONITOR` can't time commands. The "arrival gaps" it shows are the time between commands arriving, not how long they ran.
> `MONITOR` also adds load, so keep samples short on busy production hosts.




> [!IMPORTANT]
> required python 3

## How to run 
1. ```git clone https://github.com/yonatan-ess/redis-dashboard```
2. ```cd redis-dashboard```
3. ```python -m venv venv```
4. ```source ./venv/bin/activate```
5. ```pip install -r  redis_dashboard/requirements.txt```
6. ```python redis_dashboard/manage.py migrate```
7. ```python redis_dashboard/manage.py runserver```
8. open http://localhost:8000 and start a capture

Everything is served locally (Bootstrap, htmx and Chart.js are in `static/vendor`), so it works offline.

Run tests: ```python redis_dashboard/manage.py test cpuprofile```



## How to capture 
![New capture](docs/screenshots/capture-running.png)



## how to see captured monitors 
![Sample detail](docs/screenshots/capture-done.png)


## Build With

* HTMX
* Bootstrap 5.3
* Chart.js
* Django

## Roadmap

- [x] Add Top biggest payload commands
- [x] Customizable color scheme for different latency (latency would vary on different env's)
- [ ] Add Dockerfile
- [x] Base template
