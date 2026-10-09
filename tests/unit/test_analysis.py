import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from cc_contract.runner import campaign,ModelExecutor

spec=importlib.util.spec_from_file_location('analysis',Path(__file__).resolve().parents[2]/'scripts/analyze-campaigns.py')
analysis=importlib.util.module_from_spec(spec); spec.loader.exec_module(analysis)


class AnalysisTests(unittest.TestCase):
    def test_zero_detections_have_positive_upper_confidence_limit(self):
        interval=analysis.wilson(0,20)
        self.assertLess(interval[0],1e-14)
        self.assertGreater(interval[1],.1)
        self.assertLess(interval[1],.2)

    def test_exact_paired_test_and_multiple_comparisons(self):
        self.assertEqual(analysis.mcnemar_exact([False]*20,[False]*20),1)
        self.assertAlmostEqual(analysis.mcnemar_exact([True]*10,[False]*10),2/1024)
        self.assertEqual(analysis.holm({'a':.01,'b':.04,'c':.2}),{'a':.03,'b':.08,'c':.2})

    def test_bootstrap_preserves_campaign_pairs(self):
        self.assertEqual(analysis.paired_bootstrap([2]*20),[2.,2.])
        self.assertIsNone(analysis.paired_bootstrap([2]))

    def test_tampering_rejected_and_pilot_excluded(self):
        with tempfile.TemporaryDirectory() as root:
            m=campaign(ModelExecutor(),{'method':'B4','seed':5,'budget_seconds':10},root,2)
            path=next(Path(root).glob('*/manifest.json'))
            result=analysis.analyze([path])
            self.assertEqual(len(result['excluded_from_confirmatory_comparison']),1)
            self.assertEqual(result['comparisons'],{})
            raw=path.parent/'records.jsonl'; raw.chmod(0o600)
            raw.write_bytes(raw.read_bytes()+b'{}\n')
            with self.assertRaisesRegex(ValueError,'integrity'): analysis.load_campaign(path)
