"""Group per-question results for reporting: overall, per category, per split."""

from collections.abc import Sequence
from typing import Protocol, TypeVar

from rag.evaluation.golden_set import Category

OVERALL = "all"


class GoldenResult(Protocol):
    @property
    def category(self) -> Category: ...

    @property
    def split(self) -> str: ...


ResultT = TypeVar("ResultT", bound=GoldenResult)


def group_results(results: Sequence[ResultT]) -> dict[str, list[ResultT]]:
    """Groups keyed "all", "category:<category>" and "split:<split>"."""
    groups: dict[str, list[ResultT]] = {OVERALL: list(results)}
    for result in results:
        groups.setdefault(f"category:{result.category.value}", []).append(result)
        groups.setdefault(f"split:{result.split}", []).append(result)
    return groups
