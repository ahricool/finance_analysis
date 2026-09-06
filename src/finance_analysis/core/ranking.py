"""Shared rank changes across historical snapshot offsets."""

from collections.abc import Mapping


def calculate_rank_changes(
    current_rank: int,
    historical_ranks: Mapping[int, int | None],
) -> dict[str, int | None]:
    """Return historical rank minus current rank for 1/3/5 snapshot offsets."""
    return {
        f"rank_change_{offset}d": (
            None if historical_ranks.get(offset) is None else int(historical_ranks[offset]) - int(current_rank)
        )
        for offset in (1, 3, 5)
    }
