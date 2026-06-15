"""Estatística de latência e a ação pendente — port fiel do `mitigate.py`."""
from __future__ import annotations

import collections
import dataclasses
import math
import typing


@dataclasses.dataclass
class PendingAction:
    action_id: int
    sequence: int
    request_timestamp: float = 0.0
    response_timestamp: float = 0.0
    original_wait_time: float = 0.0
    is_cast: bool = False


class NumericStatisticsTracker:
    """Janela dos últimos N valores (eviction por contagem), como o original."""

    def __init__(self, count: int, max_age: typing.Optional[float] = None):
        self._count = count
        self._max_age = max_age
        self._values: collections.deque = collections.deque()

    def add(self, v: float) -> None:
        self._values.append(v)
        while len(self._values) > self._count:
            self._values.popleft()

    def min(self) -> typing.Optional[float]:
        return min(self._values) if self._values else None

    def max(self) -> typing.Optional[float]:
        return max(self._values) if self._values else None

    def mean(self) -> typing.Optional[float]:
        return sum(self._values) / len(self._values) if self._values else None

    def median(self) -> typing.Optional[float]:
        if not self._values:
            return None
        s = sorted(self._values)
        n = len(s)
        if n % 2 == 0:
            return (s[n // 2] + s[n // 2 - 1]) / 2
        return s[n // 2]

    def deviation(self) -> typing.Optional[float]:
        if not self._values:
            return None
        mean = self.mean()
        return math.sqrt(sum((x - mean) ** 2 for x in self._values) / len(self._values))

    def __bool__(self) -> bool:
        return bool(self._values)
