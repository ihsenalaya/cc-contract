import copy
import math
import tempfile
import unittest
from cc_contract.contracts import validate, InvalidScenario
from cc_contract.generators import generate, qualification_corpus
from cc_contract.model import execute
from cc_contract.oracles import dot_reference, dot_verdict
from cc_contract.search import Search, METHODS, schedule
from cc_contract.reducer import reduce
from cc_contract.runner import ModelExecutor, campaign


class ExtendedTests(unittest.TestCase):
    def test_all_eight_families_and_boundaries(self):
        cases=qualification_corpus()
        self.assertEqual(len(cases),96)
        for case in cases:
            validate(case)
            self.assertTrue(all(o['verdict']=='PASS' for o in execute(case)))

    def test_graph_retains_buffers_and_requires_completion(self):
        case=generate(81,'T08',size=2)
        case['operations'].remove(next(o for o in case['operations'] if o['op']=='destroy_graph'))
        with self.assertRaisesRegex(InvalidScenario,'live graph'):
            validate(case)
        case=generate(81,'T08',size=2)
        del case['operations'][next(i for i,o in enumerate(case['operations']) if o['op']=='sync')]
        with self.assertRaises(InvalidScenario):
            validate(case)

    def test_mapped_kernel_requires_mapped_allocation(self):
        case=generate(82,'T07',size=3)
        case['operations'][0]['memory']='pinned'
        with self.assertRaisesRegex(InvalidScenario,'mapped kernel'):
            validate(case)

    def test_double_buffer_submits_both_slots_before_observing(self):
        case=generate(83,'T04',size=3)
        kinds=[o['op'] for o in case['operations']]
        first=kinds.index('observe')
        self.assertEqual(kinds[:first].count('copy'),4)
        self.assertEqual(len(execute(case)),6)

    def test_shape_and_protocol_identifier_fail_closed(self):
        case=generate(84,'T06',size=32)
        case['operations'][0]['shape']=[3,10]
        with self.assertRaises(InvalidScenario): validate(case)
        case=generate(84,'T01',size=3)
        case['operations'][0]['buffer']='name\nEND'
        with self.assertRaises(InvalidScenario): validate(case)

    def test_float_bound_rejects_consistently_wrong_result(self):
        a,b=[.25,.5,-.75],[1.,2.,3.]
        ref,_=dot_reference(a,b)
        self.assertEqual(dot_verdict(ref,a,b)['verdict'],'PASS')
        for _ in range(5): self.assertEqual(dot_verdict(ref+.01,a,b)['verdict'],'FAIL')
        self.assertEqual(dot_verdict(math.nan,a,b)['verdict'],'INCONCLUSIVE')
        self.assertEqual(dot_verdict(0,[2**-140],[1.])['verdict'],'INCONCLUSIVE')

    def test_schedule_independent_blocks_and_equal_budgets(self):
        jobs=schedule()
        self.assertEqual(len(jobs),140)
        self.assertEqual(len({j['seed'] for j in jobs}),20)
        for block in range(20):
            group=[j for j in jobs if j['block']==block]
            self.assertEqual({j['method'] for j in group},set(METHODS))
            self.assertEqual({j['budget_seconds'] for j in group},{600})

    def test_search_reproducible_not_claiming_defects(self):
        for method in METHODS:
            a,b=Search(method,7,['T01','T02']),Search(method,7,['T01','T02'])
            self.assertEqual(a.next(),b.next())

    def test_reducer_preserves_legality_and_trigger(self):
        original=generate(8,'T02',rounds=4,size=2)
        def controlled_predicate(case):
            # Software fixture only: never a real GPU defect.
            return any(o['op']=='observe' and o['generation']==2 for o in case['operations'])
        for strategy in ('contract','ddmin'):
            reduced=reduce(original,controlled_predicate,strategy,budget_seconds=2)
            validate(reduced['scenario'])
            self.assertTrue(controlled_predicate(reduced['scenario']))
            self.assertLess(reduced['after_operations'],reduced['before_operations'])

    def test_campaign_persists_and_censors_nondetection(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest=campaign(ModelExecutor(),{'method':'B2','seed':9,'budget_seconds':10},directory,3)
            self.assertEqual(manifest['completed_cases'],3)
            self.assertFalse(manifest['environment']['gpu_executed'])
            self.assertEqual(manifest['confirmed_defects'],[])
            self.assertTrue(manifest['nondetection_is_censored'])
