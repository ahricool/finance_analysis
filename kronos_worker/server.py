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
MAX_DAILY_LOOKBACK = 240
MAX_DAILY_HORIZON = 10
MAX_SESSION_MINUTES = 390
MODEL_CONTEXT = 512
LUNCH_LAST_MINUTE = {"Asia/Shanghai": time(11, 29), "Asia/Hong_Kong": time(11, 59)}
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
    bars: list[Bar] = Field(min_length=MIN_LOOKBACK, max_length=MAX_SESSION_MINUTES)
    targets: list[int] = Field(min_length=1, max_length=MAX_SESSION_MINUTES)

    def validate_times(self, interval: str) -> None:
        stamps = [bar.timestamp for bar in self.bars] + self.targets
        if stamps != sorted(set(stamps)) or stamps[0] <= 0:
            raise ValueError("timestamps must be positive, distinct and ordered")
        zone = ZoneInfo(self.timezone)
        if interval == "1d":
            if len(self.bars) > MAX_DAILY_LOOKBACK or len(self.targets) > MAX_DAILY_HORIZON:
                raise ValueError("daily forecast window is too long")
            if any(datetime.fromtimestamp(stamp / 1000, zone).time() != time.min for stamp in stamps):
                raise ValueError("daily timestamps must be at market-local midnight")
            return
        if len(stamps) > MAX_SESSION_MINUTES or any(stamp % MINUTE_MS for stamp in stamps):
            raise ValueError("minute windows must fit a regular session and use minute starts")
        targets = [self.bars[-1].timestamp, *self.targets]
        for before, after in zip(targets, targets[1:]):
            if after - before == MINUTE_MS:
                continue
            start, end = (datetime.fromtimestamp(stamp / 1000, zone) for stamp in (before, after))
            if (start.time() != LUNCH_LAST_MINUTE.get(self.timezone) or end.time() != time(13)
                    or start.date() != end.date()):
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


def session_autoregression(predictor, x, x_stamp, y_stamp, sample):
    """Use the pinned Kronos layers and FP32 sampling with a growing attention cache."""
    from torch.nn import functional as F
    import torch

    def project(projection, values, attention):
        return projection(values).unflatten(-1, (attention.n_heads, attention.head_dim)).transpose(1, 2)

    def cache(attention):
        shape = (batch_size, attention.n_heads, total, attention.head_dim)
        return x.new_empty(shape), x.new_empty(shape)

    tokenizer, model = predictor.tokenizer, predictor.model
    initial = tokenizer.encode(x, half=True)
    batch_size, history = initial[0].shape
    horizon = y_stamp.size(1)
    total = history + horizon
    tokens = [part.new_empty((batch_size, total)) for part in initial]
    for buffer, part in zip(tokens, initial, strict=True):
        buffer[:, :history] = part
    times = model.time_emb(torch.cat((x_stamp, y_stamp), dim=1))
    layers = [(layer, *cache(layer.self_attn)) for layer in model.transformer]
    dependency = model.dep_layer
    cross_attention = dependency.cross_attn
    cross_keys, cross_values = cache(cross_attention)

    for length in range(history, total):
        first_step = length == history
        start = 0 if first_step else length - 1
        hidden = model.embedding([part[:, start:length] for part in tokens]) + times[:, start:length]
        for layer, keys, values in layers:
            attention = layer.self_attn
            norm = layer.norm1(hidden)
            rotary = attention.rotary
            cos, sin = rotary._update_cos_sin_cache(norm, total)
            cos, sin = cos[..., start:length, :], sin[..., start:length, :]
            query = project(attention.q_proj, norm, attention)
            key = project(attention.k_proj, norm, attention)
            query = query * cos + rotary._rotate_half(query) * sin
            key = key * cos + rotary._rotate_half(key) * sin
            value = project(attention.v_proj, norm, attention)
            keys[..., start:length, :] = key
            values[..., start:length, :] = value
            result = F.scaled_dot_product_attention(
                query, key if first_step else keys[..., :length, :],
                value if first_step else values[..., :length, :], is_causal=first_step,
            )
            hidden = hidden + attention.out_proj(result.transpose(1, 2).flatten(-2))
            hidden = hidden + layer.ffn(layer.norm2(hidden))

        hidden = model.norm(hidden)
        last = hidden[:, -1:, :]
        first = sample(model.head(last)[:, 0, :])
        # The pinned cross-attention sizes its rotary cache by the single sibling query. Its rotation is identity.
        sibling = model.embedding.emb_s1(first)
        query = project(cross_attention.q_proj, sibling, cross_attention)
        key = project(cross_attention.k_proj, hidden, cross_attention)
        value = project(cross_attention.v_proj, hidden, cross_attention)
        cross_keys[..., start:length, :] = key
        cross_values[..., start:length, :] = value
        result = F.scaled_dot_product_attention(
            query, key if first_step else cross_keys[..., :length, :],
            value if first_step else cross_values[..., :length, :],
        )
        last = dependency.norm(last + cross_attention.out_proj(result.transpose(1, 2).flatten(-2)))
        second = sample(model.head.cond_forward(last)[:, 0, :])
        tokens[0][:, length] = first[:, 0]
        tokens[1][:, length] = second[:, 0]
    return tokenizer.decode(tokens, half=True)[:, -horizon:, :].cpu().numpy()


class Runner:
    def __init__(self, args):
        import torch

        sys.path.insert(0, str(args.source))
        from model import Kronos, KronosPredictor, KronosTokenizer
        from model.kronos import sample_from_logits

        class SessionPredictor(KronosPredictor):
            def generate(self, x, x_stamp, y_stamp, pred_len, T, top_k, top_p, sample_count, verbose):
                if pred_len <= MAX_DAILY_HORIZON or sample_count != 1 or x.shape[1] + pred_len > self.max_context:
                    return super().generate(x, x_stamp, y_stamp, pred_len, T, top_k, top_p, sample_count, verbose)

                def sample(logits):
                    return sample_from_logits(logits, temperature=T, top_k=top_k, top_p=top_p, sample_logits=True)

                with torch.no_grad():
                    inputs = [torch.as_tensor(value, dtype=torch.float32, device=self.device)
                              for value in (x, x_stamp, y_stamp)]
                    return session_autoregression(self, inputs[0].clamp(-self.clip, self.clip), *inputs[1:], sample)

        if not torch.backends.mps.is_available():
            raise RuntimeError("Kronos requires a working Apple MPS runtime")
        torch.set_num_threads(2)
        torch.set_num_interop_threads(1)
        model = Kronos.from_pretrained(args.model_dir, local_files_only=True).eval()
        tokenizer = KronosTokenizer.from_pretrained(args.tokenizer_dir, local_files_only=True).eval()
        self.predictor = SessionPredictor(model, tokenizer, device="mps", max_context=MODEL_CONTEXT)
        self.identity = {
            "protocol": PROTOCOL, "model": args.model, "weights_revision": args.weights_revision,
            "device": "mps", "release": args.release, "intervals": ["1m", "1d"],
        }
        self.slot = BoundedSemaphore(1)
        self._priority_lock = Lock()
        self._minute_retry_until = 0.0
        # Trigger real MPS kernels before advertising readiness to deployment.
        warmup_horizon = MAX_DAILY_HORIZON + 1
        stamps = pd.Series(pd.date_range("2026-01-01", periods=MIN_LOOKBACK + warmup_horizon, tz="UTC", freq="min"))
        values = [100.0 + i / 100 for i in range(MIN_LOOKBACK)]
        frame = pd.DataFrame({col: values for col in ("open", "high", "low", "close")})
        self.predictor.predict_batch(
            [frame], [stamps[:MIN_LOOKBACK]], [stamps[MIN_LOOKBACK:]], pred_len=warmup_horizon, verbose=False,
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
