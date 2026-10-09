"""Conditional paired intervention measurement; correctness precedes timing."""
import random
import time


def paired_benchmark(cases, paths, correctness, characterization, blocks=10, seed=68001, synchronize=lambda:None):
    required={'initial','conservative','intervention'}
    if set(paths)!=required or not characterization or characterization.get('state')!='CHARACTERIZED_REAL_ANOMALY':
        return {'state':'CONDITIONAL_NOT_APPLICABLE','reason':'characterized_real_case_and_three_paths_required','records':[]}
    if len(cases)!=24 or blocks<1:
        raise ValueError('E8 requires 24 common requests and positive paired block count')
    # Qualification calls are not timed performance samples.
    qualification=[]
    for name in sorted(paths):
        for index,case in enumerate(cases):
            output=paths[name](case);synchronize(); verdict=correctness(case,output)
            qualification.append({'path':name,'case':index,'verdict':verdict})
    protected=[r for r in qualification if r['path'] in {'conservative','intervention'}]
    if any(r['verdict']!='PASS' for r in protected):
        return {'state':'BLOCKED_CORRECTNESS','qualification':qualification,'records':[]}
    rng=random.Random(seed);records=[]
    for block in range(blocks):
        order=sorted(paths);rng.shuffle(order)
        for position,name in enumerate(order):
            latencies=[];verdicts=[]
            for case in cases:
                synchronize();begin=time.perf_counter();result=paths[name](case);synchronize()
                latencies.append(time.perf_counter()-begin)
                verdicts.append(correctness(case,result))
            record={'block':block,'position':position,'path':name,'latency_seconds':latencies,
                    'throughput_requests_per_second':len(cases)/sum(latencies),'verdicts':verdicts,
                    'correctness_passed':all(v=='PASS' for v in verdicts)}
            records.append(record)
            if name in {'conservative','intervention'} and not record['correctness_passed']:
                return {'state':'BLOCKED_CORRECTNESS_DURING_MEASUREMENT','qualification':qualification,'records':records}
    return {'state':'COMPLETE_PAIRED_MEASUREMENT','seed':seed,'independent_units':'paired_blocks',
            'qualification':qualification,'records':records,'characterization':characterization,
            'timing_scope':'provided_path_and_synchronization; excludes_oracle_and_trace_serialization'}
