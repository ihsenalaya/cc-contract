"""Bounded execution with durable original traces and explicit execution scope."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import signal
import sys
import time
from uuid import uuid4
from .cli import canonical, provenance
from .contracts import validate, InvalidScenario, UnsupportedScenario
from .generators import qualification_corpus, FAMILIES
from .model import execute as model_execute
from .native import NativeExecutor, InfrastructureFailure
from .search import Search, METHODS, schedule


def utc():
    return datetime.now(timezone.utc).isoformat()


class ModelExecutor:
    environment = {'scope':'CPU_SIMULATION_ONLY','gpu_executed':False,'hardware_attestation':'NOT_RUN'}
    capabilities = {'mapped':True,'graphs':True}
    def execute(self,case):
        return model_execute(case)
    def close(self):
        pass


def backend(name):
    return ModelExecutor() if name=='model' else NativeExecutor(reference=name=='native-reference')


def qualify(executor):
    counts, observations = Counter(),0
    for case in qualification_corpus():
        try:
            result = executor.execute(case)
            verdict = 'FAIL' if any(o['verdict']=='FAIL' for o in result) else 'PASS'
            observations += len(result)
        except UnsupportedScenario:
            verdict = 'UNSUPPORTED'
        counts[verdict] += 1
    return {'record_type':'qualification','scope':executor.environment['scope'],
            'gpu_executed':executor.environment['gpu_executed'],'cases':96,'counts':dict(counts),
            'observations':observations,'verdict':'PASS' if counts['PASS']==96 else 'INCOMPLETE',
            'hardware_attestation':'NOT_RUN_IN_WORKER'}


def campaign(executor, config, destination, max_cases=None):
    run_id = 'campaign-'+utc().replace(':','').replace('+','_')+'-'+uuid4().hex[:8]
    directory = Path(destination)/run_id
    directory.mkdir(parents=True,exist_ok=False,mode=0o700)
    commit,dirty = provenance()
    image = os.environ.get('CC_IMAGE_DIGEST','NOT_APPLICABLE_LOCAL_PROCESS')
    if executor.environment['gpu_executed'] and ('@sha256:' not in image or dirty is True):
        raise ValueError('GPU campaign requires immutable image digest and committed sources')
    families = [f for f in FAMILIES if f not in {'T07','T08'} or executor.capabilities.get('mapped' if f=='T07' else 'graphs')]
    policy = Search(config['method'],config['seed'],families)
    original = {'schema_version':2,'run_id':run_id,'timestamp_utc':utc(),'git_commit':commit,
                'working_tree_dirty':dirty,'image_digest':image,'configuration':config,
                'environment':{**executor.environment,'python':platform.python_version()},
                'family_support':{f:f in families for f in FAMILIES},'oracle_version':'integer_physical_tag_v2',
                'protocol_version':'0.2-draft','final_statistical_units':'independent_campaign_blocks',
                'defect_classification':'candidate_FAIL_requires_external_reproduction_and_review'}
    (directory/'start.json').write_bytes(canonical(original))
    counts = Counter()
    interrupted = {'value':False}
    def stop(*_):
        interrupted['value'] = True
    previous = {s:signal.signal(s,stop) for s in (signal.SIGINT,signal.SIGTERM)}
    started = time.monotonic()
    cases, error, state = 0,None,'COMPLETE_BUDGET'
    raw_path = directory/'records.jsonl'
    try:
        with raw_path.open('xb') as raw:
            while time.monotonic()-started < config['budget_seconds']:
                if interrupted['value']:
                    state = 'INTERRUPTED'
                    break
                if max_cases is not None and cases>=max_cases:
                    state = 'COMPLETE_CASE_LIMIT_LOCAL_ONLY'
                    break
                scenario = policy.next()
                observations,reason = [],None
                begin = time.monotonic()
                try:
                    validate(scenario)
                    observations = executor.execute(scenario)
                    verdict = 'FAIL' if any(o['verdict']=='FAIL' for o in observations) else 'PASS'
                    policy.observe(scenario)
                except InvalidScenario as exc:
                    verdict,reason = 'INVALID_TEST',str(exc)
                except UnsupportedScenario as exc:
                    verdict,reason = 'UNSUPPORTED',str(exc)
                except InfrastructureFailure as exc:
                    verdict,reason,state = 'INFRA_FAILURE',str(exc),'INFRA_FAILURE'
                    error = reason
                record = {'record_type':'case','run_id':run_id,'case_index':cases,'timestamp_utc':utc(),
                          'elapsed_seconds':time.monotonic()-started,'duration_seconds':time.monotonic()-begin,
                          'scenario':scenario,'observations':observations,'verdict':verdict,'reason':reason,
                          'scope':executor.environment['scope'],'gpu_executed':executor.environment['gpu_executed'],
                          'confirmed_distinct_defect':False}
                raw.write(canonical(record)); raw.flush(); os.fsync(raw.fileno())
                cases += 1; counts[verdict] += 1
                # Checkpoint is a durable recovery description, not a false claim
                # that a crashed CUDA context can continue safely in place.
                checkpoint = {'run_id':run_id,'completed_cases':cases,'elapsed_seconds':time.monotonic()-started,
                              'next_action_on_failure':'finalize_partial_then_fresh_qualified_process',
                              'random_state':policy.rng.getstate(),'structural':sorted(policy.structural),
                              'temporal':sorted(policy.temporal),'draws':policy.draws}
                temporary = directory/'checkpoint.tmp'
                temporary.write_bytes(canonical(checkpoint)); temporary.replace(directory/'checkpoint.json')
                if state=='INFRA_FAILURE':
                    break
    except BaseException as exc:
        state,error = 'INFRA_FAILURE',type(exc).__name__+': '+str(exc)
        raise
    finally:
        for sig,handler in previous.items():
            signal.signal(sig,handler)
        manifest = {**original,'state':state,'counts':dict(counts),'completed_cases':cases,
                    'candidate_draws':policy.draws,'actual_seconds':time.monotonic()-started,
                    'coverage':{'structural':len(policy.structural),'temporal':len(policy.temporal)},
                    'error':error,'raw_sha256':hashlib.sha256(raw_path.read_bytes()).hexdigest(),
                    'raw_file':'records.jsonl','confirmed_defects':[],
                    'time_to_confirmed_detection':None,'nondetection_is_censored':True}
        (directory/'manifest.json').write_bytes(canonical(manifest))
        for file in directory.iterdir():
            if file.is_file():
                file.chmod(0o444)
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command',choices=['qualify','campaign','schedule'])
    parser.add_argument('--backend',choices=['model','native-reference','cuda'],default='model')
    parser.add_argument('--method',choices=METHODS,default='B4')
    parser.add_argument('--seed',type=int,default=41001)
    parser.add_argument('--budget-seconds',type=float,default=600)
    parser.add_argument('--max-cases',type=int)
    parser.add_argument('--blocks',type=int,default=20)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--allow-unsupported',action='store_true',help='Qualification may proceed with explicitly unsupported optional families; verdict/counts stay unchanged')
    args = parser.parse_args()
    if args.command=='schedule':
        print(json.dumps(schedule(args.blocks,args.budget_seconds,args.seed),indent=2)); return 0
    if args.command=='campaign' and (args.output is None or args.budget_seconds<=0):
        parser.error('campaign requires --output and a positive budget')
    if args.backend=='cuda' and args.max_cases is not None:
        parser.error('GPU comparative budgets cannot be silently replaced by case limits')
    executor = backend(args.backend)
    try:
        result = qualify(executor) if args.command=='qualify' else campaign(executor,
                    {'method':args.method,'seed':args.seed,'budget_seconds':args.budget_seconds,
                     'partition':'development_pilot','max_cases':args.max_cases},args.output,args.max_cases)
        print(json.dumps(result,indent=2))
        if args.command=='qualify' and args.allow_unsupported and result['counts'].get('PASS',0)>0 and not result['counts'].get('FAIL',0):
            return 0
        return 0 if result.get('verdict')=='PASS' or result.get('state','').startswith('COMPLETE') else 1
    finally:
        executor.close()


if __name__=='__main__':
    sys.exit(main())
