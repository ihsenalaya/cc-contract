"""Independent byte/state, arithmetic, AI output and paired-metric audit (stdlib)."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
import struct


def digest(words, fmt):
    return hashlib.sha256(struct.pack('<'+fmt*len(words),*words)).hexdigest()


def verdict_check(verdict, words, fmt, consumer=None):
    observed=verdict['observed_state'];expected=verdict['expected_state']
    if observed['buffer_id']!=words[0] or observed['generation']!=words[1] or observed['payload_tag']!=digest(words[3:],fmt):
        raise ValueError('Observed state not from consumed witness')
    if consumer is not None and observed['consumer']!=consumer:raise ValueError('Consumer mismatch')
    differences=[key for key in expected if observed[key]!=expected[key]]
    claimed=verdict['mismatches']
    if any(x not in claimed for x in differences) or any(x not in differences+['dependency_binding'] for x in claimed):
        raise ValueError('Mismatch list inconsistent')
    result='STATE_CONTINUITY_VIOLATION' if claimed else 'PASS'
    if verdict['classification']!=result:raise ValueError('False classification')


def audit(directory):
    records=json.loads((directory/'dynamic-development.json').read_text())
    for record in records:
        previous=record['seed'];generations={1:1,2:1,3:1}
        for row in record['steps']:
            raw=row['observation'];words=raw['consumed_words'];expected=row['expected']
            if row['prior_output']!=previous:raise ValueError('Dynamic branch lost preceding output')
            if expected['generation']!=generations[expected['buffer_id']]+1:raise ValueError('Nonmonotone generation')
            generations[expected['buffer_id']]=expected['generation']
            value=0
            for word in words[3:]:value=(value+word)%2**32 if raw['consumer']==1 else value^word
            if value!=raw['value']:raise ValueError('Consumer arithmetic differs')
            verdict_check(row['verdict'],words,'I',{1:'sum',2:'xor'}[raw['consumer']])
            previous=value
    ai=[]
    for fault in ('L1','L2','C1','C2'):
        h=directory/f'ai-{fault}-healthy.json';f=directory/f'ai-{fault}-injected.json'
        if not h.exists():continue
        healthy=json.loads(h.read_text());faulty=json.loads(f.read_text())
        for result in (healthy,faulty):
            for row in result['steps']:
                verdict_check(row['verdict'],row['snapshot_words'],'q')
                logits=row['logits']
                if not logits or any(not math.isfinite(x) for x in logits):raise ValueError('Invalid model logits')
                if row['next_token']!=max(range(len(logits)),key=logits.__getitem__):raise ValueError('Wrong argmax output')
        a,b=healthy['steps'][2]['logits'],faulty['steps'][2]['logits']
        ai.append({'fault':fault,'logit_Linf_at_injection':max(abs(x-y) for x,y in zip(a,b)),
                   'generated_tokens_changed':healthy['tokens']!=faulty['tokens']})
    perf=directory/'performance-cpu.json'
    if perf.exists():
        pairs=json.loads(perf.read_text())
        modes={r['mode']:r for r in pairs['records']}
        for mode in modes.values():
            samples=mode['samples'];durations=[r['wall_ns']/1e6 for r in samples]
            if statistics.median(durations)!=mode['latency_p50_ms']:raise ValueError('Incorrect latency median')
            if not math.isclose(mode['tokens_per_s'],sum(len(x['tokens']) for x in samples)/(sum(durations)/1000)):raise ValueError('Incorrect token throughput')
        off,on=modes['BASELINE_OFF'],modes['CC_CONTRACT_ON']
        if [r['tokens'] for r in off['samples']]!=[r['tokens'] for r in on['samples']]:raise ValueError('Unmatched performance paths')
        overhead=100*(on['latency_p50_ms']-off['latency_p50_ms'])/off['latency_p50_ms']
        if not math.isclose(overhead,pairs['overhead_percent']):raise ValueError('Incorrect overhead')
    return {'state':'PASS_INDEPENDENT_CPU_DEVELOPMENT_AUDIT','dynamic_sequences':len(records),
            'AI_output_impacts':ai,'detector_or_injector_imported':False,'GPU_results_claimed':False,
            'files_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.glob('*.json')}}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('directory',type=Path);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();result=audit(args.directory)
    with args.output.open('x') as f:json.dump(result,f,indent=2);f.write('\n')
    print(json.dumps({k:v for k,v in result.items() if k!='files_sha256'}))
