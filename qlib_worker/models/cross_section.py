from qlib_worker.models.base import BaseLGBMRunner


class CrossSectionLGBMRunner(BaseLGBMRunner):
    """Cross-sectional excess-return regression using the full feature panel."""

    name = "cross_section_lgbm"
    version = "1"
