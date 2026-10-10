"""Meaningful CPU development checks only; never executes reserved seeds."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--model',type=Path)
    args=p.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    subprocess.run([sys.executable,'-m','cc_contract.hdsc_rq2','--output',str(args.output/'rq2')],check=True)
    subprocess.run([sys.executable,str(ROOT/'scripts/audit-hdsc-rq2.py'),str(args.output/'rq2/runs.jsonl'),
                    '--output',str(args.output/'rq2-audit.json')],check=True)
    from cc_contract.hdsc_dynamic import run
    dynamic=[]
    for seed in range(82000,82008):
        for fault in (None,'L1','L2','C1','C2'):
            row=run(seed,fault);dynamic.append(row)
            assert sum(s['verdict']['classification']=='STATE_CONTINUITY_VIOLATION' for s in row['steps'])==int(fault is not None)
    patterns=('single-stream','multi-stream','event-dependencies','double-buffering','graph-replay','generation-reuse','dynamic-branch')
    for pattern in patterns:
        result=run(82001,pattern=pattern)
        assert all(x['verdict']['classification']=='PASS' for x in result['steps'])
        dynamic.append(result)
    (args.output/'dynamic-development.json').write_text(json.dumps(dynamic)+'\n')
    ai=[]
    if args.model:
        from cc_contract.hdsc_ai import Transformer,performance
        model=Transformer(args.model)
        for fault in ('L1','L2','C1','C2'):
            healthy=model.request(82000,fault,inject=False)
            faulty=model.request(82000,fault)
            for label,record in (('healthy',healthy),('injected',faulty)):
                assert sum(x['verdict']['classification']!='PASS' for x in record['steps'])==int(label=='injected')
                (args.output/f'ai-{fault}-{label}.json').write_text(json.dumps(record)+'\n')
            ai.append({'fault':fault,'tokens_changed':healthy['tokens']!=faulty['tokens'],
                       'logits_changed_at_injection':healthy['steps'][2]['logits']!=faulty['steps'][2]['logits']})
        perf=performance(args.model,'cpu',82000)
        (args.output/'performance-cpu.json').write_text(json.dumps(perf)+'\n')
    receipt={'scope':'CPU_DEVELOPMENT_ONLY','rq2_runs':48,'dynamic_sequences':len(dynamic),
             'dynamic_steps':sum(len(x['steps']) for x in dynamic),'dynamic_path_lengths':sorted({len(x['steps']) for x in dynamic}),
             'AI_fault_pairs':ai,'sanitizer_actual_CUDA_execution':'NOT_RUN_NO_LOCAL_CUDA_DEVICE',
             'reserved_evaluation_executed':False,'H100':'DEALLOCATED',
             'file_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in args.output.iterdir() if p.is_file()}}
    (args.output/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))


if __name__=='__main__':main()
