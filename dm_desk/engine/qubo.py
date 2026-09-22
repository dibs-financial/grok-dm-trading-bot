"""QUBO formulation + quantum-inspired classical solver (simulated annealing, stdlib only).

Energy(x) = sum_i Q[i][i] x_i + sum_{i<j} Q[i][j] x_i x_j, x in {0,1}^n. Lower is better.
`Solver` is an interface so an external annealer (hardware or service) can be plugged in.
"""
from __future__ import annotations

import math
import random
from typing import Protocol


class Solver(Protocol):
    name: str
    def solve(self, Q: list[list[float]], k: int = 3) -> list[tuple[float, list[int]]]: ...


def energy(Q: list[list[float]], x: list[int]) -> float:
    n = len(x)
    e = 0.0
    for i in range(n):
        if x[i]:
            e += Q[i][i]
            for j in range(i + 1, n):
                if x[j]:
                    e += Q[i][j]
    return e


class SimulatedAnnealer:
    name = "simulated-annealing (quantum-inspired classical)"

    def __init__(self, sweeps: int = 400, restarts: int = 8, t0: float = 2.0, t1: float = 0.02, seed: int | None = 7):
        self.sweeps, self.restarts, self.t0, self.t1 = sweeps, restarts, t0, t1
        self.rng = random.Random(seed)

    def solve(self, Q: list[list[float]], k: int = 3) -> list[tuple[float, list[int]]]:
        n = len(Q)
        if n == 0:
            return []
        seen: dict[tuple[int, ...], float] = {}
        for _ in range(self.restarts):
            x = [self.rng.randint(0, 1) for _ in range(n)]
            e = energy(Q, x)
            for s in range(self.sweeps):
                t = self.t0 * (self.t1 / self.t0) ** (s / max(1, self.sweeps - 1))
                for i in range(n):
                    # delta of flipping bit i
                    d = Q[i][i] * (1 - 2 * x[i])
                    for j in range(n):
                        if j != i and x[j]:
                            d += (Q[min(i, j)][max(i, j)]) * (1 - 2 * x[i])
                    if d <= 0 or self.rng.random() < math.exp(-d / t):
                        x[i] ^= 1
                        e += d
                        seen[tuple(x)] = e
            seen[tuple(x)] = e
        ranked = sorted(seen.items(), key=lambda kv: kv[1])
        return [(e, list(x)) for x, e in ranked[:k]]


def build_qubo(utility: list[float], novelty: list[float], conflicts: list[tuple[int, int]],
               lam_novelty: float = 1.0, one_slot_penalty: float = 4.0, conflict_penalty: float = 3.0) -> list[list[float]]:
    """Minimize -(u + lam*n) x + P (sum x - 1)^2 + conflict penalties. Upper-triangular Q."""
    n = len(utility)
    Q = [[0.0] * n for _ in range(n)]
    for i in range(n):
        # -(u+lam n) x_i + P(x_i^2 - 2 x_i) -> x_i^2 = x_i for binaries
        Q[i][i] = -(utility[i] + lam_novelty * novelty[i]) + one_slot_penalty * (1 - 2)
        for j in range(i + 1, n):
            Q[i][j] = 2 * one_slot_penalty
    for i, j in conflicts:
        a, b = min(i, j), max(i, j)
        Q[a][b] += conflict_penalty
    return Q
