"""Fresh-process replay/reduction of a protected candidate; no injected mutants."""
import argparse
import hashlib
import json
from pathlib import Path
import time
from cc_contract.cli import canonical,provenance
from cc_contract.contracts import validate
from cc_contract.reducer import reduce
from cc_contract.runner import backend,utc
from uuid import uuid4


def fingerprint(observations):
    failures=[]
    for observation in observations:
        if observation['verdict']=='FAIL':
            expected,actual=observation['expected'],observation['observed']
            failures.append((observation['buffer'],expected['generation']!=actual['generation'],expected['values']!=actual['values']))
    return sorted(failures)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--scenario',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--backend',choices=['model','native-reference','cuda'],default='model')
    parser.add_argument('--reduce',choices=['contract','ddmin']);parser.add_argument('--budget-seconds',type=float,default=60)
    args=parser.parse_args();case=json.loads(args.scenario.read_text());validate(case)
    if args.budget_seconds<=0:parser.error('Positive replay budget required')
    args.output.mkdir(parents=True,exist_ok=False,mode=0o700);executor=backend(args.backend)
    commit,dirty=provenance();started=time.monotonic();run_id='replay-'+uuid4().hex
    manifest={'run_id':run_id,'timestamp_utc':utc(),'git_commit':commit,'working_tree_dirty':dirty,
              'scope':executor.environment['scope'],'gpu_executed':executor.environment['gpu_executed'],
              'scenario_sha256':hashlib.sha256(args.scenario.read_bytes()).hexdigest(),'budget_seconds':args.budget_seconds}
    calls=[]
    try:
        if hasattr(executor,'timeout'):executor.timeout=min(60,args.budget_seconds)
        original=executor.execute(case);target=fingerprint(original)
        def predicate(candidate):
            remaining=args.budget_seconds-(time.monotonic()-started)
            if remaining<=0:return False
            if hasattr(executor,'timeout'):executor.timeout=min(60,remaining)
            result=executor.execute(candidate)
            record={'scenario':candidate,'observations':result,'fingerprint':fingerprint(result),
                    'elapsed_seconds':time.monotonic()-started,'scope':executor.environment['scope']}
            calls.append(record)
            with (args.output/'replays.jsonl').open('ab') as file:file.write(canonical(record));file.flush()
            return bool(target) and fingerprint(result)==target
        if not target:
            result={'state':'CONDITIONAL_NOT_APPLICABLE','reason':'original_trace_has_no_candidate_anomaly'}
        elif args.reduce:
            remaining=max(.001,args.budget_seconds-(time.monotonic()-started))
            result=reduce(case,predicate,args.reduce,remaining)
            (args.output/'minimized-scenario.json').write_bytes(canonical(result['scenario']))
        else:
            checks=[predicate(case) for _ in range(3)]
            result={'state':'REPRODUCED_IN_ONE_FRESH_PROCESS' if all(checks) else 'INCONCLUSIVE','checks':checks}
        (args.output/'original-observations.json').write_bytes(canonical(original))
        manifest.update({'state':result['state'],'result':result,'replay_calls':len(calls)})
    except BaseException as error:
        manifest.update({'state':'INFRA_FAILURE','error':type(error).__name__+': '+str(error)});raise
    finally:
        executor.close()
        manifest['duration_seconds']=time.monotonic()-started
        manifest['hashes']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in args.output.iterdir() if p.is_file()}
        (args.output/'manifest.json').write_bytes(canonical(manifest))
        for file in args.output.iterdir():file.chmod(0o444)
    print(json.dumps(manifest,indent=2))


if __name__=='__main__':main()
