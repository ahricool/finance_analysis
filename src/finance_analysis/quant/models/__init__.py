QLIB_TRAINABLE_MODEL_KEYS = frozenset(
    {
        "cross_section_lgbm",
        "time_series_lgbm",
    }
)
CROSS_SECTION_MODEL_KEY = "cross_section_lgbm"
TIME_SERIES_MODEL_KEY = "time_series_lgbm"

__all__ = ["CROSS_SECTION_MODEL_KEY", "QLIB_TRAINABLE_MODEL_KEYS", "TIME_SERIES_MODEL_KEY"]
