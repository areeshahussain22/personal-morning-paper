from __future__ import annotations

from app.services.learning import LearningConstants, normalize, position_factor
from app.services.recommendation import exploration_draws, exploration_share


def test_position_factor_and_normalization() -> None:
    assert position_factor(1) == 1.0
    assert position_factor(3) == 1 / 1.5
    assert normalize([3.0, 4.0]) == [0.6, 0.8]


def test_learning_constants_and_exploration_are_configurable() -> None:
    constants = LearningConstants()
    assert constants.click == 1.0
    assert constants.decay == 0.97
    assert exploration_share(0, 0.15) == 0.4
    assert exploration_share(8, 0.15) == 0.15


def test_thompson_draws_are_seeded_and_use_stats() -> None:
    stats = {"world": {"views": 10, "clicks": 5}, "sports": {"views": 2, "clicks": 0}}
    first = exploration_draws("reader", "2026-10-17", stats)
    second = exploration_draws("reader", "2026-10-17", stats)
    other = exploration_draws("reader", "2026-10-18", stats)
    assert first == second
    assert first != other
    assert set(first) == {"world", "sports"}
