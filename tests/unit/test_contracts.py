import copy
import unittest
from unittest.mock import patch
from cc_contract.cli import run_case, provenance
from cc_contract.contracts import InvalidScenario, UnsupportedScenario, validate
from cc_contract.corpus import initial_corpus, scenario
from cc_contract.model import execute


class ContractTests(unittest.TestCase):
    def test_container_without_git_uses_pinned_commit(self):
        with patch.dict("os.environ", {"CC_COMMIT": "a" * 40}), patch("cc_contract.cli.subprocess.run", side_effect=FileNotFoundError):
            self.assertEqual(provenance(), ("a" * 40, None))

    def test_initial_corpus_counts_and_expected_classification(self):
        corpus = initial_corpus()
        self.assertEqual(len(corpus), 60)
        self.assertEqual(len({e["scenario"]["id"] for e in corpus}), 60)
        for entry in corpus:
            with self.subTest(id=entry["scenario"]["id"]):
                self.assertTrue(run_case(entry)["matches_expectation"])

    def test_unsynchronized_host_observation_rejected(self):
        s = scenario(10, "T01")
        s["operations"] = [o for o in s["operations"] if o["op"] != "sync"]
        with self.assertRaisesRegex(InvalidScenario, "C1"):
            validate(s)

    def test_cross_stream_copy_requires_event(self):
        s = scenario(3, "T03")
        s["operations"] = [o for o in s["operations"] if o["op"] != "wait_event"]
        with self.assertRaisesRegex(InvalidScenario, "C1"):
            validate(s)

    def test_rewrite_source_while_copy_pending_rejected(self):
        s = scenario(1, "T01")
        write = copy.deepcopy(s["operations"][3])
        write["generation"] = 1
        s["operations"].insert(5, write)
        with self.assertRaisesRegex(InvalidScenario, "C2"):
            validate(s)

    def test_cross_stream_write_after_read_rejected(self):
        s = scenario(0, "T01")
        s["operations"].insert(6, {"op": "copy", "source": "input", "target": "gpu", "stream": "other"})
        with self.assertRaisesRegex(InvalidScenario, "C2"):
            validate(s)

    def test_missing_field_and_wrong_size_rejected(self):
        s = scenario(0, "T01")
        del s["operations"][0]["size"]
        with self.assertRaises(InvalidScenario):
            validate(s)
        s = scenario(0, "T01")
        s["operations"][0]["size"] = True
        with self.assertRaises(InvalidScenario):
            validate(s)

    def test_no_observation_rejected(self):
        s = scenario(0, "T01")
        s["operations"] = [o for o in s["operations"] if o["op"] != "observe"]
        with self.assertRaisesRegex(InvalidScenario, "observable"):
            validate(s)

    def test_graphs_report_unsupported(self):
        s = scenario(0, "T01")
        s["family"] = "T08"
        with self.assertRaises(UnsupportedScenario):
            validate(s)

    def test_model_replay_deterministic_and_nonmutating(self):
        s = scenario(9, "T02")
        original = copy.deepcopy(s)
        self.assertEqual(execute(s), execute(s))
        self.assertEqual(s, original)

    def test_stale_metadata_detected_independently_of_payload(self):
        s = scenario(5, "T05")
        observations = execute(s, "stale_generation")
        self.assertTrue(all(o["verdict"] == "FAIL" for o in observations))
        self.assertTrue(all(o["observed"]["values"] == o["expected"]["values"] for o in observations))

    def test_unknown_mutation_fails_closed(self):
        with self.assertRaises(ValueError):
            execute(scenario(0, "T01"), "unknown")


if __name__ == "__main__":
    unittest.main()
