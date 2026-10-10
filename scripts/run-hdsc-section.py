"""Reserved evaluation runner inside an approved guest; never provisions a VM.

This entry point is intentionally unavailable to CPU qualification. A future
controller must bind the explicit approval to the frozen plan and stop/deallocate
the existing VM on its independent global deadline. No automatic retries.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import signal
import sys
import time

from cc_contract.hdsc_benchmark import benchmark
from cc_contract.hdsc_schedule import schedule


def job_timeout(signum, frame):
    raise TimeoutError('Predeclared job time limit exceeded')


def run_job(row, model_path, evidence_directory):
    evidence_directory.mkdir(exist_ok=False)
    def save(name, value):
        with (evidence_directory/name).open("x") as file: json.dump(value,file);file.write("\n")
    def step_observer(value):
        with (evidence_directory/"steps.jsonl").open("a") as file: file.write(json.dumps(value)+"\n")
    from cc_contract.hdsc_rq2 import execute
    from cc_contract.hdsc_dynamic import run
    kind=row['kind']
    if kind in ('capability','rq2'):
        if kind=='capability':
            target=next(t for t in benchmark()['targets'] if t['split']=='development' and t['seed']==82000 and t['fault_class']=='L1' and t['state_variant']=='changed-output')
        else:target=next(t for t in benchmark()['targets'] if t['fault_id']==row['target_id'])
        return execute({'run_id':row['job_id'],'target':target,'active':row['active'],'tool':row['tool']},'cuda','/usr/local/bin/cc-continuity-worker')
    if kind=='dynamic' or kind=='healthy' and row['section']=='core':
        return run(row['seed'],row.get('fault'),backend='cuda',pattern=row.get('pattern','dynamic'),observer=step_observer)
    from cc_contract.hdsc_ai import Transformer
    if kind=='ai-pair':
        model=Transformer(model_path,'cuda')
        outputs=[]
        for active in row['active_order']:
            value=model.request(row['seed'],row['fault'],inject=active)
            save('injected.json' if active else 'healthy.json',value);outputs.append(value)
        return {'active_order':row['active_order'],'requests':outputs}
    if kind=='healthy':return Transformer(model_path,'cuda').request(row['seed'])
    if kind=='performance':
        model=Transformer(model_path,'cuda',row['enabled'])
        for _ in range(row['warmups']):model.request(row['seed'],capture_logits=False)
        model.torch.cuda.reset_peak_memory_stats()
        samples=[]
        for index in range(row['measured_requests']):
            value=model.request(row['seed'],capture_logits=False);save(f'measured-{index}.json',value);samples.append(value)
        return {'enabled':row['enabled'],'samples':samples}
    raise ValueError('Unknown frozen job')


def technical_failure(value):
    if isinstance(value,dict):
        if value.get('execution_status') in ('CUDA_ERROR','INFRA_FAILURE','INVALID_TEST','UNSUPPORTED'):return True
        if value.get('classification') in ('CUDA_ERROR','INFRA_FAILURE','INVALID_TEST'):return True
        return any(technical_failure(v) for v in value.values())
    if isinstance(value,list):return any(technical_failure(v) for v in value)
    return False


def validate_inputs(plan_bytes, approval, now):
    plan=json.loads(plan_bytes)
    expiry=datetime.fromisoformat(approval['expires_utc'])
    if (approval.get('explicit_user_approval') is not True or approval.get('plan_sha256')!=hashlib.sha256(plan_bytes).hexdigest()
            or plan.get('protocol')!='hdsc-evaluation-v1' or expiry.tzinfo is None or now>=expiry):
        raise ValueError('Missing current explicit approval matching this exact frozen plan')
    if hashlib.sha256((json.dumps(schedule(),sort_keys=True,indent=2)+'\n').encode()).hexdigest()!=plan['schedule_sha256']:
        raise ValueError('Schedule differs from approved plan')
    return plan,expiry


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--section',choices=('core','ai'),required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--model',type=Path)
    p.add_argument('--plan',type=Path,required=True);p.add_argument('--approval',type=Path,required=True)
    args=p.parse_args()
    plan_bytes=args.plan.read_bytes();approval=json.loads(args.approval.read_text())
    plan,expiry=validate_inputs(plan_bytes,approval,datetime.now(timezone.utc))
    args.output.mkdir(parents=True,exist_ok=False)
    rows=[r for r in schedule() if r['section']==args.section]
    signal.signal(signal.SIGALRM,job_timeout)
    unsupported=set();completed=0;start=time.monotonic();performance_pairs={}
    try:
        with (args.output/'jobs.jsonl').open('x') as out:
            for row in rows:
                if (expiry-datetime.now(timezone.utc)).total_seconds()<row['maximum_seconds']+120:
                    raise TimeoutError('Insufficient allowance before release deadline')
                signal.alarm(row['maximum_seconds']);job_start=time.monotonic()
                if row.get('tool') in unsupported:
                    result={'classification':'UNSUPPORTED','reason':'capability_rejected_environment','executed':False}
                else:result=run_job(row,args.model,args.output/f"job-{row['job_id']}")
                signal.alarm(0)
                if row['kind']=='performance':
                    pair=performance_pairs.setdefault(row['block'],{})
                    pair[row['enabled']]=[sample['tokens'] for sample in result['samples']]
                    if len(pair)==2 and pair[False]!=pair[True]:
                        result['classification']='INVALID_TEST'
                        result['reason']='ON/OFF tokens and therefore dynamic workload paths differ'
                out.write(json.dumps({'job':row,'result':result,'job_wall_seconds':time.monotonic()-job_start},sort_keys=True)+'\n');out.flush()
                if row['kind']=='capability' and result['B2_sanitizer']['classification']=='UNSUPPORTED' and result['B2_sanitizer'].get('reason')!='no_cuda_device':unsupported.add(row['tool'])
                elif technical_failure(result):raise RuntimeError('Technical failure: stop and deallocate before diagnosis')
                completed+=1;print(json.dumps({'job_id':row['job_id'],'kind':row['kind'],'completed':completed}),flush=True)
                if row['section']=='ai':
                    import gc,torch
                    gc.collect();torch.cuda.empty_cache()
    finally:
        signal.alarm(0)
        summary={'planned_jobs':len(rows),'completed_jobs':completed,'wall_seconds':time.monotonic()-start,
                 'unsupported_tools':sorted(unsupported),'plan_sha256':hashlib.sha256(plan_bytes).hexdigest()}
        (args.output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')


if __name__=='__main__':main()
