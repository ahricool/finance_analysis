"""Explicit failures surfaced by quant tasks and APIs."""


class QuantError(RuntimeError):
    pass


class UnsupportedQuantUniverseError(QuantError, ValueError):
    """A new quant operation targeted a disabled or non-market universe."""


class QuantDatasetMissingError(QuantError):
    pass


class QuantDatasetValidationError(QuantError):
    pass


class AdjustmentFactorMissingError(QuantDatasetValidationError):
    """Daily raw bars exist without matching forward-adjustment factors."""


class QlibUnavailableError(QuantError):
    pass


class ModelArtifactMissingError(QuantError):
    pass


class ModelNotPublishedError(QuantError):
    pass


class FeatureDataMissingError(QuantError):
    pass


class BenchmarkDataMissingError(QuantError):
    pass


class EventProviderUnavailableError(QuantError):
    pass


class PredictionFailedError(QuantError):
    pass


class PortfolioConstraintError(QuantError):
    pass


class IntradayConfirmationDataMissingError(QuantError):
    pass
