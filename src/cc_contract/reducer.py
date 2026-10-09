"""Validity-preserving reduction. Predicates must preserve anomaly identity."""
from copy import deepcopy
import time
from .contracts import validate, InvalidScenario


def dependency_closure(case, removed):
    """Remove consumers of deleted allocations/events/graph definitions.

    Closure is only a proposal; the full validator remains the authority.
    """
    removed = set(removed)
    ops = case['operations']
    while True:
        before = len(removed)
        buffers = {o['buffer'] for i,o in enumerate(ops) if i in removed and o['op']=='alloc'}
        events = {o['event'] for i,o in enumerate(ops) if i in removed and o['op']=='record_event'}
        graphs = {o['graph'] for i,o in enumerate(ops) if i in removed and o['op']=='define_graph'}
        for i,op in enumerate(ops):
            refs = {op.get(k) for k in ('buffer','source','target')}
            if refs & buffers or op.get('event') in events or op.get('graph') in graphs:
                removed.add(i)
            if op['op']=='define_graph' and any({n['source'],n['target']} & buffers for n in op['operations']):
                removed.add(i)
        if len(removed)==before:
            break
    result = deepcopy(case)
    result['operations'] = [o for i,o in enumerate(result['operations']) if i not in removed]
    return result


def reduce(case, interesting, strategy='contract', budget_seconds=60, repeats=3):
    if strategy not in {'contract','ddmin'} or budget_seconds<=0 or repeats<1:
        raise ValueError('Invalid reduction parameters')
    validate(case)
    deadline = time.monotonic()+budget_seconds
    attempts, invalid, calls = 0,0,0
    def accepts(candidate):
        nonlocal attempts,invalid,calls
        attempts += 1
        try:
            validate(candidate)
        except InvalidScenario:
            invalid += 1
            return False
        for _ in range(repeats):
            if time.monotonic() >= deadline:
                return False
            calls += 1
            if not interesting(candidate):
                return False
        return True
    if not accepts(case):
        return {'state':'INCONCLUSIVE','reason':'original_anomaly_not_reproducible','scenario':case,
                'predicate_calls':calls,'invalid_proposals':invalid}
    current = deepcopy(case)
    granularity = 2
    started = time.monotonic()
    while len(current['operations'])>=2 and time.monotonic()<deadline:
        length = len(current['operations'])
        chunk = max(1,(length+granularity-1)//granularity)
        changed = False
        for start in range(0,length,chunk):
            removed = set(range(start,min(length,start+chunk)))
            candidate = dependency_closure(current,removed) if strategy=='contract' else deepcopy(current)
            if strategy=='ddmin':
                candidate['operations'] = [o for i,o in enumerate(candidate['operations']) if i not in removed]
            if accepts(candidate):
                current,changed,granularity = candidate,True,max(2,granularity-1)
                break
            if time.monotonic()>=deadline:
                break
        if not changed:
            if granularity>=length:
                break
            granularity = min(length,granularity*2)
    return {'state':'BUDGET_EXHAUSTED' if time.monotonic()>=deadline else 'REDUCED_VALID',
            'scenario':current,'strategy':strategy,'before_operations':len(case['operations']),
            'after_operations':len(current['operations']),'attempts':attempts,'invalid_proposals':invalid,
            'predicate_calls':calls,'duration_seconds':time.monotonic()-started,
            'reproduction_requirement':repeats,'global_minimum_proven':False}
