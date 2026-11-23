"""Loopback-only Kronos inference on macOS. Keep torch outside the FA images."""

import argparse
import json
import logging
import math
import os
import sys
from datetime import datetime, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import BoundedSemaphore, Lock
from time import monotonic
from typing import Literal
from zoneinfo import ZoneInfo

import pandas as pd
from pydantic import BaseModel, Field, FiniteFloat, model_validator

PROTOCOL = 1
MINUTE_MS = 60_000
MIN_LOOKBACK = 15
MAX_HORIZON = 10
MAX_BODY = 1_048_576
logger = logging.getLogger(__name__)


class Bar(BaseModel):
    timestamp: int
    open: FiniteFloat = Field(gt=0)
    high: FiniteFloat = Field(gt=0)
    low: FiniteFloat = Field(gt=0)
    close: FiniteFloat = Field(gt=0)
    volume: FiniteFloat = Field(ge=0)
    amount: FiniteFloat | None = Field(default=None, ge=0)


class Window(BaseModel):
    symbol: str = Field(min_length=1, max_length=36)
    timezone: str = Field(max_length=64)
    bars: list[Bar] = Field(min_length=MIN_LOOKBACK, max_length=240)
    targets: list[int] = Field(min_length=1, max_length=MAX_HORIZON)

    def validate_times(self, interval: str) -> None:
        stamps = [bar.timestamp for bar in self.bars] + self.targets
        if stamps != sorted(set(stamps)) or stamps[0] <= 0:
            raise ValueError("timestamps must be positive, distinct and ordered")
        zone = ZoneInfo(self.timezone)
        if interval == "1d":
            if any(datetime.fromtimestamp(stamp / 1000, zone).time() != time.min for stamp in stamps):
                raise ValueError("daily timestamps must be at market-local midnight")
        else:
            if any(stamp % MINUTE_MS for stamp in stamps):
                raise ValueError("timestamps must be minute starts")
            last = self.bars[-1].timestamp
            if self.targets != [last + MINUTE_MS * i for i in range(1, len(self.targets) + 1)]:
                raise ValueError("targets must follow the last confirmed candle")


class Request(BaseModel):
    protocol: int
    interval: Literal["1m", "1d"] = "1m"
    windows: list[Window] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def validate_batch(self):
        if self.protocol != PROTOCOL:
            raise ValueError("unsupported protocol")
        if len({item.symbol for item in self.windows}) != len(self.windows):
            raise ValueError("duplicate symbol")
        if len({(len(item.bars), len(item.targets)) for item in self.windows}) != 1:
            raise ValueError("a batch must use the same lookback and horizon")
        for window in self.windows:
            window.validate_times(self.interval)
        return self


def prices(frame: pd.DataFrame, timestamps: list[int]) -> list[dict] | None:
    result = []
    rows = frame[["open", "high", "low", "close"]].itertuples(index=False)
    for at, (open_, high, low, close) in zip(timestamps, rows, strict=True):
        if not all(math.isfinite(value) and value > 0 for value in (open_, high, low, close)):
            return None
        # Kronos decodes price channels separately. Wicks must enclose the body.
        result.append({"timestamp": at, "open": open_, "close": close,
                       "high": max(open_, high, close), "low": min(open_, low, close)})
    return result


class Runner:
    def __init__(self, args):
        import torch

        sys.path.insert(0, str(args.source))
        from model import Kronos, KronosPredictor, KronosTokenizer

        if not torch.backends.mps.is_available():
            raise RuntimeError("Kronos requires a working Apple MPS runtime")
        torch.set_num_threads(2)
        torch.set_num_interop_threads(1)
        model = Kronos.from_pretrained(args.model_dir, local_files_only=True).eval()
        tokenizer = KronosTokenizer.from_pretrained(args.tokenizer_dir, local_files_only=True).eval()
        self.predictor = KronosPredictor(model, tokenizer, device="mps", max_context=512)
        self.identity = {
            "protocol": PROTOCOL, "model": args.model, "weights_revision": args.weights_revision,
            "device": "mps", "release": args.release, "intervals": ["1m", "1d"],
        }
        self.slot = BoundedSemaphore(1)
        self._priority_lock = Lock()
        self._minute_retry_until = 0.0
        # Trigger real MPS kernels before advertising readiness to deployment.
        stamps = pd.Series(pd.date_range("2026-01-01", periods=MIN_LOOKBACK + MAX_HORIZON, tz="UTC", freq="min"))
        values = [100.0 + i / 100 for i in range(MIN_LOOKBACK)]
        frame = pd.DataFrame({col: values for col in ("open", "high", "low", "close")})
        self.predictor.predict_batch(
            [frame], [stamps[:MIN_LOOKBACK]], [stamps[MIN_LOOKBACK:]], pred_len=MAX_HORIZON, verbose=False,
        )
        torch.mps.synchronize()

    def acquire_slot(self, interval: str) -> bool:
        with self._priority_lock:
            if interval == "1d" and monotonic() < self._minute_retry_until:
                return False
            if self.slot.acquire(blocking=False):
                return True
            if interval == "1m":
                # The Streamer retries in ten seconds after a busy response.
                self._minute_retry_until = monotonic() + 12
            return False

    def predict(self, request: Request) -> dict:
        inputs, starts, ends = [], [], []
        for window in request.windows:
            frame = pd.DataFrame([bar.model_dump() for bar in window.bars]).drop(columns="timestamp")
            amount = frame["volume"] * frame[["open", "high", "low", "close"]].mean(axis=1)
            frame["amount"] = pd.to_numeric(frame["amount"]).fillna(amount)
            inputs.append(frame)
            starts.append(pd.Series(pd.to_datetime([bar.timestamp for bar in window.bars], unit="ms", utc=True))
                          .dt.tz_convert(window.timezone))
            ends.append(pd.Series(pd.to_datetime(window.targets, unit="ms", utc=True)).dt.tz_convert(window.timezone))
        frames = self.predictor.predict_batch(inputs, starts, ends, pred_len=len(ends[0]),
                                              sample_count=1, verbose=False)
        predictions = []
        for window, frame in zip(request.windows, frames, strict=True):
            if bars := prices(frame, window.targets):
                predictions.append({"symbol": window.symbol, "bars": bars})
        return {**self.identity, "predictions": predictions}


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def respond(self, status: int, value: dict) -> None:
        body = json.dumps(value, allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        if len(args) < 2 or str(args[1]) != "200":
            logger.info(format, *args)

    def do_GET(self):
        if self.path != "/healthz":
            self.respond(404, {"error": "not found"})
            return
        self.respond(200, self.server.runner.identity)

    def do_POST(self):
        if self.path != "/predict":
            self.respond(404, {"error": "not found"})
            return
        self.close_connection = True
        try:
            length = int(self.headers.get("Content-Length", 0))
            if not 0 < length <= MAX_BODY:
                self.respond(413, {"error": "invalid request size"})
                return
            request = Request.model_validate_json(self.rfile.read(length))
        except (LookupError, OSError, OverflowError, ValueError):
            self.respond(400, {"error": "invalid forecast request"})
            return
        runner = self.server.runner
        if not runner.acquire_slot(request.interval):
            self.respond(503, {"error": "inference busy"})
            return
        try:
            result = runner.predict(request)
        except Exception:
            logger.exception("Kronos prediction failed")
            self.respond(500, {"error": "inference failed"})
        else:
            self.respond(200, result)
        finally:
            runner.slot.release()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    # Never silently execute a GPU deployment on CPU.
    if os.environ.get("PYTORCH_ENABLE_MPS_FALLBACK", "0") != "0":
        raise RuntimeError("MPS fallback must be disabled for this service")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--tokenizer-dir", type=Path, required=True)
    parser.add_argument("--model", choices=("small", "base", "large"), required=True)
    parser.add_argument("--weights-revision", required=True)
    parser.add_argument("--release", required=True)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        server.runner = Runner(args)
        logger.info("Kronos %s is ready on MPS", args.model)
        server.serve_forever()


if __name__ == "__main__":
    main()
