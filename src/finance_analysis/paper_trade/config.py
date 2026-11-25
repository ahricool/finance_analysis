from dataclasses import dataclass, field

from finance_analysis.config.env_parsing import env_str


@dataclass(frozen=True)
class DemoConfig:
    key: str = field(repr=False)
    secret: str = field(repr=False)

    @classmethod
    def from_env(cls):
        return cls(env_str("BINANCE_DEMO_API_KEY") or "", env_str("BINANCE_DEMO_API_SECRET") or "")

    @property
    def status(self):
        return "CONFIGURED" if self.key and self.secret else "NOT_CONFIGURED"
