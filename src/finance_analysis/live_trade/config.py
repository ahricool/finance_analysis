from dataclasses import dataclass, field

from finance_analysis.config.env_parsing import env_str


@dataclass(frozen=True)
class LiveConfig:
    key: str = field(repr=False)
    secret: str = field(repr=False)

    @classmethod
    def from_env(cls):
        return cls(env_str("BINANCE_LIVE_API_KEY") or "", env_str("BINANCE_LIVE_API_SECRET") or "")

    @property
    def configured(self):
        return bool(self.key and self.secret)
