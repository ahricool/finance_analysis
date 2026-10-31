"""Compatibility for published migration 0068 only; runtime uses shared research inputs."""


def seed_us_postmarket_symbols(connection) -> None:
    from finance_analysis.database.us_research import seed_us_research_symbols

    seed_us_research_symbols(connection, source="US_POSTMARKET_REVIEW")
