import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest
from cc_contract.runner import campaign,ModelExecutor
from cc_contract.generators import generate
from cc_contract.runner import qualify
from cc_contract.cli import canonical
from cc_contract.native import InfrastructureFailure

spec=importlib.util.spec_from_file_location('analysis',Path(__file__).resolve().parents[2]/'scripts/analyze-campaigns.py')
analysis=importlib.util.module_from_spec(spec); spec.loader.exec_module(analysis)
spec=importlib.util.spec_from_file_location('qualification_review',Path(__file__).resolve().parents[2]/'scripts/review-ir-qualification.py')
qualification_review=importlib.util.module_from_spec(spec);spec.loader.exec_module(qualification_review)


class AnalysisTests(unittest.TestCase):
    def test_independent_qualification_review_rejects_wrong_raw_generation(self):
        class PartialFixture(ModelExecutor):
            calls=0
            def execute(self,case):
                self.calls+=1
                if self.calls>1:raise InfrastructureFailure('controlled partial CPU fixture')
                return super().execute(case)
        records=[];summary=qualify(PartialFixture(),records.append)
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'qualification.stdout'
            def save():
                data=b''.join(canonical(r) for r in records)
                summary['case_records_sha256']=hashlib.sha256(data).hexdigest()
                path.write_bytes(data+json.dumps(summary,indent=2).encode())
            save()
            self.assertEqual(qualification_review.review(path)['verdict'],'INCOMPLETE')
            records[0]['observations'][0]['observed']['generation']+=1
            save()
            with self.assertRaisesRegex(ValueError,'raw payload/generation'):
                qualification_review.review(path)

    def test_replay_cli_evidence_is_readable_by_review_loader(self):
        with tempfile.TemporaryDirectory() as root:
            scenario=Path(root)/'scenario.json';scenario.write_text(json.dumps(generate(17,'T02',size=2)))
            output=Path(root)/'replay'
            env={**os.environ,'PYTHONPATH':str(Path(__file__).resolve().parents[2]/'src')}
            subprocess.run([sys.executable,str(Path(__file__).resolve().parents[2]/'scripts/replay-scenario.py'),
                            '--scenario',str(scenario),'--output',str(output),'--backend','model'],
                           env=env,capture_output=True,text=True,check=True)
            manifest,rows=analysis.load_campaign(output/'manifest.json')
            self.assertEqual(manifest['state'],'CONDITIONAL_NOT_APPLICABLE')
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]['scenario'],json.loads(scenario.read_text()))
            self.assertFalse(rows[0]['gpu_executed'])

    def test_supplied_empty_reviews_do_not_hide_unreviewed_candidates(self):
        class CandidateFixture(ModelExecutor):
            def execute(self,case):
                records=super().execute(case)
                records[0]['verdict']='FAIL'
                return records
        with tempfile.TemporaryDirectory() as root:
            campaign(CandidateFixture(),{'method':'B4','seed':5,'budget_seconds':10},root,1)
            reviews=Path(root)/'reviews.json'; reviews.write_text('[]')
            result=analysis.analyze(list(Path(root).glob('*/manifest.json')),reviews)
            self.assertEqual(result['analysis_state'],'INCOMPLETE_DEFECT_REVIEW')
            self.assertEqual(result['unreviewed_candidate_failures'],1)
            self.assertEqual(result['campaign_rows'][0]['confirmed_defects'],0)

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
