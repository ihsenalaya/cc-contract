"""Budgeted baseline and ablation policies over a shared bounded candidate pool."""
from copy import deepcopy
import random
from .contracts import validate, InvalidScenario
from .generators import generate, features, BOUNDARIES

METHODS = ('B1', 'B2', 'B3', 'B4', 'A_NO_STATE', 'A_NO_DIVERSITY', 'A_NO_VALIDITY_GUIDANCE')


class Search:
    def __init__(self, method, seed, families):
        if method not in METHODS or not families:
            raise ValueError('Unknown method or empty supported family set')
        self.method, self.rng, self.families = method, random.Random(seed), tuple(families)
        self.structural, self.temporal, self.visits = set(), set(), {}
        self.draws = 0

    def candidate(self):
        self.draws += 1
        seed = self.rng.randrange(2**31)
        family = self.rng.choice(self.families)
        rounds = 1 if self.method in {'B1','A_NO_STATE'} else self.rng.randint(2,8)
        replay = 1 if self.method in {'B1','A_NO_STATE'} else self.rng.choice((1,2,4,8))
        case = generate(seed, family, rounds=rounds, size=self.rng.choice(BOUNDARIES),
                        streams=self.rng.randint(2,4), replay_count=replay)
        # Invalid proposals are software-level inputs only. Every policy retains
        # the final safety validator. Never send this deletion directly to CUDA.
        if self.rng.random() < .15:
            case = deepcopy(case)
            index = next(i for i,o in enumerate(case['operations']) if o['op']=='sync')
            del case['operations'][index]
            case['proposal_mutation'] = 'deleted_sync_REJECT_BEFORE_DEVICE'
        return case

    def next(self):
        count = 1 if self.method in {'B1','B2'} else 16
        candidates = [self.candidate() for _ in range(count)]
        if count == 1:
            return candidates[0]
        ranked = []
        for index, case in enumerate(candidates):
            try:
                validate(case)
                legal = True
            except InvalidScenario:
                legal = False
            if not legal and self.method != 'A_NO_VALIDITY_GUIDANCE':
                continue
            structural, temporal = features(case)
            novelty = len(structural-self.structural)
            if self.method != 'B3':
                novelty += len(temporal-self.temporal)
            signature = tuple(sorted(temporal))
            diversity = 0 if self.method in {'B3','A_NO_DIVERSITY'} else 1/(1+self.visits.get(signature,0))
            ranked.append((novelty,diversity,-index,case))
        # If every proposal is invalid, final validator records a rejection.
        return max(ranked,key=lambda x:x[:3])[3] if ranked else candidates[0]

    def observe(self, case):
        structural, temporal = features(case)
        self.structural |= structural
        self.temporal |= temporal
        signature = tuple(sorted(temporal))
        self.visits[signature] = self.visits.get(signature,0)+1


def schedule(blocks=20, budget_seconds=600, seed=41001):
    if blocks < 1 or budget_seconds <= 0:
        raise ValueError('Positive block count and budget required')
    rng = random.Random(seed)
    result = []
    for block in range(blocks):
        order = list(METHODS)
        rng.shuffle(order)
        block_seed = 1_000_000 + rng.randrange(2**31-1_000_000)
        for position,method in enumerate(order):
            result.append({'block':block,'position':position,'method':method,'seed':block_seed,
                           'budget_seconds':budget_seconds,'partition':'reserved_evaluation'})
    return result
