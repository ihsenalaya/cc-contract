"""Offline reserved-evaluation reporting. Never starts CUDA or loads model weights.

Preserve missing runs and invalid pairs. Validate actual schedule membership and
raw witnesses before producing bounded block-level effects, never GPU fixtures.
"""
import argparse
from collections import Counter,defaultdict
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import statistics
import tempfile

from cc_contract.hdsc_statistics import paired_effect,percentile

ROOT=Path(__file__).resolve().parents[1]


def auditor(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/f'{name}.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def effect(pairs):
    return paired_effect(pairs) if len(pairs)>=2 else {'independent_blocks':len(pairs),'estimate':None,'reason':'fewer_than_two_complete_blocks'}


def sanitizer_audit(result):
    tool=result['tool'];finding=result['B2_sanitizer'];raw=result['raw_worker']
    if tool=='direct':return
    text=raw.get('stdout','')+'\n'+raw.get('stderr','') if raw else ''
    rejected=any(s in text.lower() for s in ('not supported under confidential','not supported in confidential',
        'debugging is not supported','not supported in cc-on',
        'confidential compute mode detected. compute-sanitizer will be disabled.'))
    if finding['classification']=='UNSUPPORTED':
        if not rejected:
            raise ValueError('Unsupported sanitizer claim lacks original diagnostic')
        return
    if finding['classification'] in ('PASS','ALERT') and (rejected or 'compute-sanitizer will be disabled' in text.lower()):
        raise ValueError('Disabled instrumentation cannot establish a sanitizer detection or clean result')
    counts=re.findall(r'ERROR SUMMARY:\s*(\d+)\s+errors?',text)
    if finding['classification'] in ('PASS','ALERT'):
        if len(counts)!=1 or result['observation']['execution_status']!='CUDA_SUCCESS':raise ValueError('Incomplete sanitizer evidence')
        errors=int(counts[0])
        if finding['classification']!=('ALERT' if errors else 'PASS') or raw['returncode']!=(86 if errors else 0):
            raise ValueError('Sanitizer report/exit mismatch')


def request_audit(request,check):
    if request['backend']!='cuda':raise ValueError('CPU result cannot enter reserved GPU report')
    for step in request['steps']:
        if step['execution_status']!='CUDA_SUCCESS':raise ValueError('Incomplete AI consumer')
        if request['enabled']:check.verdict_check(step['verdict'],step['snapshot_words'],'q')
        if step.get('logits') is not None:
            logits=step['logits']
            if not logits or any(not math.isfinite(x) for x in logits):raise ValueError('Invalid model output')
            if max(range(len(logits)),key=logits.__getitem__)!=step['next_token']:raise ValueError('Model argmax disagrees')


def perf_metrics(result):
    samples=result['samples'];durations=[r['wall_ns']/1e9 for r in samples]
    if not durations or any(x<=0 or not math.isfinite(x) for x in durations):raise ValueError('Invalid timing')
    return dict(latency_p50_ms=percentile(durations,.5)*1000,latency_p95_ms=percentile(durations,.95)*1000,
        throughput_requests_per_s=len(samples)/sum(durations),tokens_per_s=sum(len(x['tokens']) for x in samples)/sum(durations),
        TTFT_p50_ms=percentile([x['TTFT_ns']/1e6 for x in samples],.5),
        GPU_stream_interval_p50_ms=percentile([x['GPU_stream_interval_ms'] for x in samples],.5),
        CPU_verifier_p50_ms=percentile([x['CPU_verifier_ns']/1e6 for x in samples],.5),
        GPU_max_allocated_bytes=max(x['GPU_max_allocated_bytes'] for x in samples),
        persistent_input_bytes=max(x['persistent_input_bytes'] for x in samples),
        extra_copies_per_request=statistics.mean(x['extra_copies'] for x in samples),
        witness_sync_points_per_request=statistics.mean(x['witness_D2H_sync_points'] for x in samples))


def analyze(directory,plan_path,schedule_path):
    plan=json.loads(plan_path.read_text());schedule_bytes=schedule_path.read_bytes()
    if hashlib.sha256(schedule_bytes).hexdigest()!=plan['schedule_sha256']:raise ValueError('Frozen schedule hash differs')
    expected=json.loads(schedule_bytes);jobs=[]
    for section in ('core','ai'):
        path=directory/section/'jobs.jsonl'
        actual=[json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
        scheduled=[j for j in expected if j['section']==section]
        if len(actual)>len(scheduled) or any(a['job']!=b for a,b in zip(actual,scheduled)):
            raise ValueError('Actual execution is not a prefix of the exact section schedule')
        jobs.extend(actual)
    rq2=[j['result'] for j in jobs if j['job']['kind']=='rq2' and j['result'].get('executed',True)]
    independent=auditor('audit-hdsc-rq2');check=auditor('audit-hdsc-development')
    with tempfile.TemporaryDirectory() as temporary:
        path=Path(temporary)/'rq2.jsonl';path.write_text(''.join(json.dumps(r)+'\n' for r in rq2))
        native_audit=independent.audit(path)
    for row in rq2:
        if row['backend']!='cuda':raise ValueError('CPU result in reserved report')
        sanitizer_audit(row)
    baseline_counts={}
    comparisons={}
    for tool in ('direct','memcheck','initcheck','synccheck'):
        rows=[r for r in rq2 if r['tool']==tool]
        baseline_counts[tool]=dict(runs=len(rows),activated=sum(r['activated'] for r in rows),
            CC_classifications=dict(Counter(r['B3_CC_Contract']['classification'] for r in rows)),
            sanitizer_classifications=dict(Counter(r['B2_sanitizer']['classification'] for r in rows)))
    direct={ (r['target']['fault_id'],r['active']):r for r in rq2 if r['tool']=='direct'}
    for baseline in ('B0','B1','memcheck','initcheck','synccheck'):
        for profile in ('changed-output','equal-payload','sum-collision'):
            blocks=defaultdict(list)
            candidates=[r for r in rq2 if r['tool']==('direct' if baseline in ('B0','B1') else baseline)]
            for row in candidates:
                target=row['target'];reference=direct.get((target['fault_id'],True))
                if not row['active'] or target['state_variant']!=profile or not row['activated'] or not reference or not reference['activated']:continue
                b=row['B0_cuda_status'] if baseline=='B0' else row['B1_output_only'] if baseline=='B1' else row['B2_sanitizer']['classification']
                if b not in ('PASS','ALERT'):continue
                blocks[target['block']].append((int(b=='ALERT'),int(reference['B3_CC_Contract']['classification']=='STATE_CONTINUITY_VIOLATION')))
            # Four fault causes per profile; incomplete blocks are shown but excluded from paired CI.
            pairs=[(statistics.mean(a for a,b in values),statistics.mean(b for a,b in values)) for values in blocks.values() if len(values)==4]
            comparisons[baseline+'/'+profile]=dict(effect=effect(pairs),eligible_targets_by_block={str(k):len(v) for k,v in blocks.items()},
                estimand='Detection difference conditional on activation in both paired executions; four causes per complete block')
    dynamic=[];healthy=[];ai=[];perf=defaultdict(dict)
    for job in jobs:
        row,result=job['job'],job['result'];kind=row['kind']
        if kind=='dynamic' or kind=='healthy' and row['section']=='core':
            alerts=0
            for step in result['steps']:
                raw=step['observation']
                if raw['execution_status']!='CUDA_SUCCESS':raise ValueError('Incomplete dynamic CUDA run')
                words=raw['consumed_words'];value=0
                for word in words[3:]:value=(value+word)%2**32 if raw['consumer']==1 else value^word
                if value!=raw['value']:raise ValueError('Dynamic arithmetic differs')
                check.verdict_check(step['verdict'],words,'I',{1:'sum',2:'xor'}[raw['consumer']])
                alerts+=step['verdict']['classification']=='STATE_CONTINUITY_VIOLATION'
            (healthy if kind=='healthy' else dynamic).append(dict(job_id=row['job_id'],block=row['block'],fault=row.get('fault'),alerts=alerts,steps=len(result['steps'])))
        elif kind=='ai-pair':
            by_active={active:request for active,request in zip(result['active_order'],result['requests'])}
            if len(by_active)!=2:raise ValueError('Incomplete AI pair')
            for request in by_active.values():request_audit(request,check)
            h,f=by_active[False],by_active[True]
            a,b=h['steps'][2]['logits'],f['steps'][2]['logits']
            ai.append(dict(job_id=row['job_id'],block=row['block'],fault=row['fault'],
                injected_alerts=sum(s['verdict']['classification']=='STATE_CONTINUITY_VIOLATION' for s in f['steps']),
                healthy_alerts=sum(s['verdict']['classification']=='STATE_CONTINUITY_VIOLATION' for s in h['steps']),
                logit_Linf=max(abs(x-y) for x,y in zip(a,b)),tokens_changed=h['tokens']!=f['tokens']))
        elif kind=='healthy':
            request_audit(result,check);healthy.append(dict(job_id=row['job_id'],block=row['block'],alerts=sum(s['verdict']['classification']=='STATE_CONTINUITY_VIOLATION' for s in result['steps'])))
        elif kind=='performance':
            for sample in result['samples']:request_audit(sample,check)
            perf[row['block']][row['enabled']]=result
    paired={};invalid=[];per_block=[]
    for block,modes in perf.items():
        if set(modes)!={False,True}:continue
        off,on=modes[False],modes[True]
        if [s['tokens'] for s in off['samples']]!=[s['tokens'] for s in on['samples']]:invalid.append(block);continue
        a,b=perf_metrics(off),perf_metrics(on)
        per_block.append({'block':block,'OFF':a,'ON':b})
        for metric in a:paired.setdefault(metric,[]).append((a[metric],b[metric]))
    dynamic_blocks=defaultdict(list);healthy_blocks=defaultdict(list)
    for record in dynamic:dynamic_blocks[record['block']].append(record)
    for record in healthy:healthy_blocks[record['block']].append(record)
    dynamic_pairs=[]
    for records in dynamic_blocks.values():
        baseline=[r for r in records if r['fault'] is None];faults=[r for r in records if r['fault'] is not None]
        if len(baseline)==1 and len(faults)==4:
            dynamic_pairs.append((int(baseline[0]['alerts']>0),statistics.mean(r['alerts']>0 for r in faults)))
    healthy_rates=[(0,statistics.mean(r['alerts']>0 for r in records)) for records in healthy_blocks.values() if len(records)==8]
    return dict(state='AUDITED_COMPLETE_SCHEDULE' if len(jobs)==len(expected) else 'AUDITED_PARTIAL_SCHEDULE',
        planned_jobs=len(expected),recorded_jobs=len(jobs),missing_jobs=len(expected)-len(jobs),
        plan_sha256=hashlib.sha256(plan_path.read_bytes()).hexdigest(),RQ2_independent_audit=native_audit,
        RQ2_counts=baseline_counts,RQ2_paired_effects=comparisons,RQ3_runs=dynamic,AI_fault_pairs=ai,
        RQ3_healthy_vs_injected_alert_difference=effect(dynamic_pairs),
        healthy_reserved=dict(runs=len(healthy),runs_with_alerts=sum(r['alerts']>0 for r in healthy),records=healthy,
                              block_false_positive_fraction=effect(healthy_rates)),
        RQ4=dict(paired_block_metrics=per_block,invalid_blocks=invalid,effects={metric:effect(values) for metric,values in paired.items()}),
        limitations=['No independent model correctness or malicious-adapter guarantee','Unsupported tools excluded, never missed detections','CPU verifier time covers verdict relations, not all preparation','GPU event interval is not isolated SM-active time'])


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('directory',type=Path);p.add_argument('--plan',type=Path,required=True)
    p.add_argument('--schedule',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();result=analyze(args.directory,args.plan,args.schedule)
    with args.output.open('x') as file:json.dump(result,file,indent=2);file.write('\n')
    print(json.dumps({'state':result['state'],'recorded_jobs':result['recorded_jobs'],'missing_jobs':result['missing_jobs']}))
