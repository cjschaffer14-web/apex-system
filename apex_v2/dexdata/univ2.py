"""Exact integer Uniswap-V2-style pair math (what the contract computes), plus exact cycle sizing."""
from __future__ import annotations

import math
from typing import Sequence, Tuple

Leg = Tuple[int, int, int, int]  # (reserve_in, reserve_out, fee_num, fee_den), e.g. (.., .., 997, 1000)


def get_amount_out(amount_in: int, r_in: int, r_out: int, fee_num: int = 997, fee_den: int = 1000) -> int:
    """UniswapV2Library.getAmountOut with a configurable fee ratio."""
    if amount_in <= 0 or r_in <= 0 or r_out <= 0:
        return 0
    a = amount_in * fee_num
    return a * r_out // (r_in * fee_den + a)


def invariant_ok(r0: int, r1: int, b0: int, b1: int, in0: int, in1: int, fee_num: int, fee_den: int) -> bool:
    """Pair.swap's K check: (b0*den - in0*(den-num)) * (b1*den - in1*(den-num)) >= r0*r1*den^2."""
    fee = fee_den - fee_num
    return (b0 * fee_den - in0 * fee) * (b1 * fee_den - in1 * fee) >= r0 * r1 * fee_den * fee_den


def cycle_out(x: int, legs: Sequence[Leg]) -> int:
    for r_in, r_out, fn, fd in legs:
        x = get_amount_out(x, r_in, r_out, fn, fd)
    return x


def best_cycle_input(legs: Sequence[Leg]) -> Tuple[int, int]:
    """Exact integer argmax of cycle_out(x) - x. Returns (x*, profit); (0, 0) if unprofitable.
    Float closed form gives the bracket; integer ternary search finishes it (profit is concave in x)."""
    A, B, C = 1.0, 1.0, 0.0
    for r_in, r_out, fn, fd in legs:
        g = fn / fd
        a, b, c = g * r_out, float(r_in), g
        A, B, C = A * a, B * b, C * b + c * A
    if A <= B or C <= 0:
        return 0, 0
    t = (math.sqrt(A * B) - B) / C
    lo, hi = 0, max(2, int(t * 2) + 2)
    f = lambda x: cycle_out(x, legs) - x
    while hi - lo > 4:
        m1, m2 = lo + (hi - lo) // 3, hi - (hi - lo) // 3
        if f(m1) < f(m2):
            lo = m1
        else:
            hi = m2
    best = max(range(lo, hi + 1), key=f)
    p = f(best)
    return (best, p) if p > 0 else (0, 0)
