"""Generate an exact, serial evaluation inventory without executing any case."""
import random
from .hdsc_benchmark import schedule as rq2_schedule

PATTERNS = ('single-stream','multi-stream','event-dependencies','double-buffering',
            'graph-replay','generation-reuse','dynamic-branch','Transformer-healthy')


def schedule():
    rows=[]
    for tool in ('memcheck','initcheck','synccheck'):
        rows.append({'rq':'RQ2','section':'core','kind':'capability','tool':tool,
                     'seed':82000,'fault':'L1','active':False,'maximum_seconds':30})
    for row in rq2_schedule('reserved_evaluation'):
        rows.append({'rq':'RQ2','section':'core','kind':'rq2','target_id':row['target']['fault_id'],
                     'tool':row['tool'],'active':row['active'],'maximum_seconds':30})
    rng=random.Random(501026)
    for block,seed in enumerate(range(93000,93010)):
        faults=[None,'L1','L2','C1','C2'];rng.shuffle(faults)
        for fault in faults:
            rows.append({'rq':'RQ3','section':'core','kind':'dynamic','block':block,
                         'seed':seed,'fault':fault,'maximum_steps':12,'maximum_seconds':60})
        faults=['L1','L2','C1','C2'];rng.shuffle(faults)
        for fault in faults:
            order=[False,True];rng.shuffle(order)
            rows.append({'rq':'RQ2/RQ3','section':'ai','kind':'ai-pair','block':block,
                         'seed':seed,'fault':fault,'active_order':order,'requests':2,'maximum_steps_per_request':8,
                         'maximum_seconds':120})
        patterns=list(PATTERNS);rng.shuffle(patterns)
        for pattern in patterns:
            rows.append({'rq':'RQ2/RQ3','section':'ai' if pattern=='Transformer-healthy' else 'core',
                         'kind':'healthy','block':block,'seed':104000+block,'pattern':pattern,
                         'maximum_seconds':120 if pattern=='Transformer-healthy' else 60})
        order=[False,True];random.Random(seed).shuffle(order)
        for enabled in order:
            rows.append({'rq':'RQ4','section':'ai','kind':'performance','block':block,'seed':seed,
                         'enabled':enabled,'warmups':3,'measured_requests':10,'maximum_seconds':180})
    return [dict(job_id=index,**row) for index,row in enumerate(rows)]


def counts():
    rows=schedule()
    result={key:sum(r['kind']==key for r in rows) for key in ('capability','rq2','dynamic','ai-pair','healthy','performance')}
    instances=sum(r['kind'] in ('ai-pair','performance') or r['kind']=='healthy' and r['section']=='ai' for r in rows)
    result.update(serial_jobs=len(rows),workload_requests=sum(
                      r['warmups']+r['measured_requests'] if r['kind']=='performance' else
                      r['requests'] if r['kind']=='ai-pair' else 1 for r in rows),
                  performance_warmup_requests=sum(r['warmups'] for r in rows if r['kind']=='performance'),
                  performance_measured_requests=sum(r['measured_requests'] for r in rows if r['kind']=='performance'),
                  AI_model_instances=instances,AI_setup_eager_forwards=9*instances,AI_setup_capture_forwards=3*instances,
                  racecheck_runs=0,Random_B3_B4_runs=0)
    return result
