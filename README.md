# redis-dashboard
redis cpu profiling 


# Description
Have you ever hit 100% cpu on your redis host ?  
are you tired of looking into the matrix [redis monitor](https://redis.io/commands/monitor/) ?  

hopefully this tool can help

It captures multiply "small" monitor commands , saves them in sqlite and summarised them 




> [!IMPORTANT]
> required python 3

## How to run 
1. ```git clone https://github.com/yonatan-ess/redis-dashboard```
2. ```cd redis-dashboard```
3. ```python -m venv venv```
4. ```source ./venv/bin/activate```
5. ```pip install -r  redis_dashboard/requirements.txt```
6. ```python redis_dashboard/manage.py migrate```
  
start capturing ! 



## How to capture 
![output2](https://github.com/yonatan-ess/redis-dashboard/assets/7499016/4735b127-2615-41c4-a825-3b7c4a1254f7)



## how to see captured monitors 
![Screen Shot 2024-01-09 at 16 38 31](https://github.com/yonatan-ess/redis-dashboard/assets/7499016/907a5811-a04b-4573-a10b-85d58ed63a2f)


## Build With

* HTMX
* Bootstrap
* Django

## Roadmap

- [ ] Add Top biggest payload commands
- [ ] Customizable color scheme for different latency (latency would vary on different env's)
- [ ] Add Dockerfile
- [ ] Base jinja template
