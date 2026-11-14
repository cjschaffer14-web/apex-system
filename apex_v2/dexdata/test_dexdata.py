import json
import os
import tempfile
import unittest

from .archive import audit, load, opportunities
from .collect import dec_string, word
from .univ2 import best_cycle_input, cycle_out, get_amount_out, invariant_ok


class MathTests(unittest.TestCase):
    def test_known_get_amount_out(self):
        # 1000/1000 reserves, 100 in, 0.3% fee: 100*997*1000 // (1000*1000 + 100*997) = 90
        self.assertEqual(get_amount_out(100, 1000, 1000), 90)
        self.assertEqual(get_amount_out(0, 1000, 1000), 0)

    def test_invariant_holds_for_exact_output_and_fails_for_one_more(self):
        r0, r1, a = 10**6, 2 * 10**6, 12345
        out = get_amount_out(a, r0, r1)
        self.assertTrue(invariant_ok(r0, r1, r0 + a, r1 - out, a, 0, 997, 1000))
        self.assertFalse(invariant_ok(r0, r1, r0 + a, r1 - out - 1, a, 0, 997, 1000))

    def test_best_cycle_is_integer_optimal(self):
        # sell WETH on pool A at ~3030, buy it back on pool B at ~3000 (A is 1% richer)
        a = (10_000 * 10**18, 30_300_000 * 10**6, 997, 1000)
        b = (30_000_000 * 10**6, 10_000 * 10**18, 997, 1000)
        x, p = best_cycle_input([a, b])
        self.assertGreater(p, 0)
        for dx in (-10**17, 10**17, -10**18, 10**18):
            self.assertLessEqual(cycle_out(x + dx, [a, b]) - (x + dx), p)

    def test_no_cycle_when_prices_equal(self):
        a = (10_000 * 10**18, 30_000_000 * 10**6, 997, 1000)
        b = (30_000_000 * 10**6, 10_000 * 10**18, 997, 1000)
        self.assertEqual(best_cycle_input([a, b]), (0, 0))


class DecodeTests(unittest.TestCase):
    def test_word_and_string(self):
        self.assertEqual(word("0x" + "00" * 31 + "05" + "00" * 31 + "07", 1), 7)
        s = "0x" + "20".rjust(64, "0") + "4".rjust(64, "0") + "57455448".ljust(64, "0")
        self.assertEqual(dec_string(s), "WETH")
        self.assertEqual(dec_string("0x" + "57455448".ljust(64, "0")), "WETH")


class ArchiveTests(unittest.TestCase):
    def build(self, tamper=False):
        P = "0xpool"
        r0, r1 = 10**18 * 100, 10**6 * 300_000
        a = 10**18
        out = get_amount_out(a, r0, r1)
        post = (r0 + a, r1 - out)
        recs = [
            {"type": "pool", "dex": "uniswap_v2", "pool": P, "token0": "0xw", "token1": "0xu", "symbol0": "WETH", "symbol1": "USDC"},
            {"type": "block", "n": 1, "hash": "h1", "parent": "h0", "time": 1, "base_fee": 10**6},
            {"type": "block", "n": 2, "hash": "h2", "parent": "h1", "time": 3, "base_fee": 10**6},
            {"type": "state", "n": 1, "pool": P, "r0": r0, "r1": r1, "ts_last": 0},
            {"type": "state", "n": 2, "pool": P, "r0": post[0], "r1": post[1] + (5 if tamper else 0), "ts_last": 0},
            {"type": "log", "n": 2, "pool": P, "tx": "t", "tx_index": 0, "log_index": 0, "kind": "sync", "r0": post[0], "r1": post[1]},
            {"type": "log", "n": 2, "pool": P, "tx": "t", "tx_index": 0, "log_index": 1, "kind": "swap",
             "in0": a, "in1": 0, "out0": 0, "out1": out, "sender": "0xs", "to": "0xt"},
        ]
        f = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
        for r in recs:
            f.write(json.dumps(r) + "\n")
        f.close()
        return f.name

    def test_audit_passes_on_consistent_archive(self):
        p = self.build()
        try:
            a = audit(load(p))
            pa = list(a["pool_audit"].values())[0]
            self.assertEqual(pa["swaps_replayed"], 1)
            self.assertEqual(pa["exact_getAmountOut_match"], 1)
            self.assertEqual(pa["inferred_fee"], "997/1000")
            self.assertEqual(a["state_continuity_broken"], 0)
            self.assertEqual(a["missing_blocks"], 0)
            self.assertEqual(a["parent_hash_breaks"], 0)
        finally:
            os.unlink(p)

    def test_audit_detects_state_discontinuity(self):
        p = self.build(tamper=True)
        try:
            self.assertGreater(audit(load(p))["state_continuity_broken"], 0)
        finally:
            os.unlink(p)

    def test_opportunities_runs(self):
        p = self.build()
        try:
            A = load(p)
            self.assertEqual(opportunities(A, {"0xpool": (997, 1000)})["rows"], [])  # single pool: no pair
        finally:
            os.unlink(p)


if __name__ == "__main__":
    unittest.main()
