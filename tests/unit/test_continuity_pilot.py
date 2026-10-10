import copy
import inspect
import importlib.util
import json
from pathlib import Path
import random
import struct
import unittest
from unittest.mock import patch

from cc_contract import continuity_oracle as oracle
from cc_contract.continuity_model import FAULTS, simulate
from cc_contract.continuity_pilot import execute, inputs, schedule, summarize


class ContinuityTests(unittest.TestCase):
    def test_exported_schedule_matches_runner(self):
        root = Path(__file__).resolve().parents[2]
        self.assertEqual(schedule(), json.loads((root / "experiments/state-continuity-schedule-v0.1.json").read_text()))

    def test_independent_auditor_rejects_tampering(self):
        root = Path(__file__).resolve().parents[2]
        spec = importlib.util.spec_from_file_location("continuity_audit", root / "scripts/audit-continuity-pilot.py")
        audit = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(audit)
        records = [execute(row, "cpu-model") for row in schedule()]
        self.assertEqual(audit.audit(records, schedule())["runs"], 50)
        mutations = [lambda r: r[0]["verdict"].update(classification="PASS"),
                     lambda r: r[0]["expected_state"].update(generation_id=1),
                     lambda r: r[0].update(activated=False),
                     lambda r: r[0]["observation"].update(consumer_sum=0),
                     lambda r: r[0].update(seed=0),
                     lambda r: r.reverse()]
        for mutate in mutations:
            changed = copy.deepcopy(records)
            mutate(changed)
            with self.assertRaises(ValueError):
                audit.audit(changed, schedule())

    def test_all_healthy_and_injected_paths(self):
        # Each fault has its own neutralized control, beyond the 10 pilot controls.
        for seed in (0, 71001, 2 ** 32 - 1):
            expected, packets = inputs(seed)
            for fault in FAULTS:
                with self.subTest(seed=seed, fault=fault):
                    good = oracle.classify(expected, simulate(packets, fault, False))
                    bad = oracle.classify(expected, simulate(packets, fault, True))
                    self.assertEqual(good["classification"], "PASS")
                    self.assertEqual(bad["classification"], "STATE_CONTINUITY_VIOLATION")
                    self.assertEqual(bad["observed_state"]["observed_buffer_id"], 2 if fault == "C2" else 1)
                    self.assertEqual(bad["observed_state"]["observed_generation"], 2 if fault == "C2" else 1)

    def test_detector_does_not_receive_fault_identity(self):
        self.assertEqual(list(inspect.signature(oracle.classify).parameters), ["expected", "observation"])
        source = inspect.getsource(oracle.classify)
        self.assertNotIn('observation.get("fault', source)
        self.assertNotIn('observation["fault', source)
        expected, packets = inputs(71)
        for active in (True, False):
            observation = simulate(packets, "C1", active)
            before = oracle.classify(expected, observation)
            for fake_flag in (False, True, "C2", None):
                observation["fault_injected"] = fake_flag
                observation["fault"] = fake_flag
                self.assertEqual(oracle.classify(expected, observation), before)

    def test_actual_bytes_override_injector_intention(self):
        # Feed current bytes to an active stale-transfer injector: no violation.
        expected, packets = inputs(17)
        packets[0] = packets[1]
        observation = simulate(packets, "C1", True)
        self.assertEqual(oracle.classify(expected, observation)["classification"], "PASS")

    def test_header_rewrite_does_not_hide_stale_payload(self):
        expected, packets = inputs(22)
        observation = simulate(packets, "C1", True)
        observation["consumed_words"][1] = 2
        verdict = oracle.classify(expected, observation)
        self.assertEqual(verdict["mismatches"], ["payload"])

    def test_payload_corruption_with_consistent_sum_detected(self):
        expected, packets = inputs(23)
        observation = simulate(packets, "C1", False)
        observation["consumed_words"][5] ^= 1
        observation["consumer_sum"] = sum(observation["consumed_words"][3:]) & oracle.MASK
        self.assertEqual(oracle.classify(expected, observation)["classification"], "STATE_CONTINUITY_VIOLATION")

    def test_inconsistent_consumer_computation_is_invalid(self):
        expected, packets = inputs(24)
        observation = simulate(packets, "C1", False)
        observation["consumer_sum"] ^= 1
        self.assertEqual(oracle.classify(expected, observation)["classification"], "INVALID_TEST")

    def test_malformed_and_bool_records_fail_closed(self):
        expected, packets = inputs(25)
        good = simulate(packets, "C1", False)
        variants = [None, {}, {"backend": "cpu-model", "execution_status": "CUDA_SUCCESS"}]
        for value in (True, -1, 2 ** 32, "1"):
            row = copy.deepcopy(good)
            row["consumed_words"][0] = value
            variants.append(row)
        for observation in variants:
            self.assertEqual(oracle.classify(expected, observation)["classification"], "INFRA_FAILURE")

    def test_cuda_error_is_never_continuity_detection(self):
        expected, _ = inputs(26)
        for status in ("CUDA_ERROR", "UNSUPPORTED", "INFRA_FAILURE"):
            self.assertEqual(oracle.classify(expected, {"execution_status": status})["classification"], status)

    def test_stale_and_wrong_buffer_contracts_are_distinguishable(self):
        expected, packets = inputs(28)
        observation = simulate(packets, "C2", True)
        actual_payload = tuple(observation["consumed_words"][3:])
        alternative_contract = oracle.ExpectedState(2, 2, actual_payload)
        self.assertEqual(oracle.classify(expected, observation)["classification"], "STATE_CONTINUITY_VIOLATION")
        self.assertEqual(oracle.classify(alternative_contract, observation)["classification"], "PASS")

    def test_schedule_and_result_accounting(self):
        rows = schedule()
        self.assertEqual(len(rows), 50)
        self.assertEqual(rows, schedule())
        self.assertEqual(len({r["run_id"] for r in rows}), 50)
        self.assertEqual(len({r["seed"] for r in rows}), 10)
        result = summarize([execute(row, "cpu-model") for row in rows])
        for entry in result:
            self.assertEqual(entry["runs"], 10)
            self.assertEqual(entry["cuda_success"], 0)
            self.assertEqual(entry["model_success"], 10)
            self.assertEqual(entry["detected"], 0 if entry["fault"] == "HEALTHY" else 10)
            self.assertEqual(entry["missed"], 0)
        self.assertEqual(result[0]["false_positives"], 0)

    def test_activation_requires_observation_not_flag(self):
        row = next(r for r in schedule() if r["group"] == "C1")
        _, packets = inputs(row["seed"])
        neutral = simulate(packets, "C1", False)
        with patch("cc_contract.continuity_pilot.simulate", return_value=neutral):
            result = execute(row, "cpu-model")
        self.assertFalse(result["activated"])
        self.assertEqual(result["verdict"]["classification"], "PASS")
        table = next(x for x in summarize([result]) if x["fault"] == "C1")
        self.assertEqual(table["not_activated"], 1)
        self.assertEqual(table["missed"], 0)

    def test_fault_and_schedule_are_separate_from_detector(self):
        expected, packets = inputs(29)
        record = simulate(packets, "L1", True)
        self.assertLess(record["operation_trace"].index("consume-completed"),
                        record["operation_trace"].index("copy:E2"))
        record.pop("operation_trace")
        self.assertEqual(oracle.classify(expected, record)["classification"], "STATE_CONTINUITY_VIOLATION")

    def test_random_blinded_observation_order(self):
        corpus = []
        for seed in range(30):
            expected, packets = inputs(seed)
            for fault in FAULTS:
                for active in (False, True):
                    record = simulate(packets, fault, active)
                    record.pop("operation_trace")
                    corpus.append((expected, record, active))
        random.Random(44).shuffle(corpus)
        for expected, record, active in corpus:
            self.assertEqual(oracle.classify(expected, record)["classification"],
                             "STATE_CONTINUITY_VIOLATION" if active else "PASS")

    def test_worker_failures_do_not_fabricate_results(self):
        row = schedule()[0]
        result = execute(row, "cuda", "/nonexistent/cc-continuity-worker")
        self.assertEqual(result["verdict"]["classification"], "INFRA_FAILURE")
        self.assertFalse(result["activated"])

    def test_packets_have_compatible_sizes_and_distinct_payloads(self):
        expected, packets = inputs(30)
        self.assertEqual([len(x) for x in packets], [76, 76, 76])
        self.assertEqual(len(set(packets)), 3)
        self.assertEqual(struct.unpack("<3I", packets[2][:12]), (2, 2, 16))


if __name__ == "__main__":
    unittest.main()
