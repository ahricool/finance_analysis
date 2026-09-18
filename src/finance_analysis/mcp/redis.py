"""Independent Redis ACL client with an explicit command and argument boundary."""

from redis import Redis
from redis._parsers.resp2 import _RESP2Parser
from redis.connection import ConnectionPool

from .security import MAX_RESULT_BYTES, encoded

ALLOWED = frozenset("""GET MGET HGET HMGET HGETALL HSCAN HLEN LRANGE LLEN ZRANGE ZREVRANGE
ZCARD ZSCAN SMEMBERS SCARD SSCAN SCAN TYPE EXISTS TTL PTTL XLEN XRANGE XREVRANGE INFO""".split())


class ResponseTooLarge(Exception):
    pass


class BoundedBuffer:
    """Stop oversized bulk strings before allocation; bound recursive RESP arrays too."""

    def __init__(self, buffer):
        self.buffer, self.remaining = buffer, MAX_RESULT_BYTES

    def __getattr__(self, name):
        return getattr(self.buffer, name)

    def consume(self, size):
        self.remaining -= size
        if self.remaining < 0:
            raise ResponseTooLarge()

    def read(self, length):
        self.consume(length + 2)
        return self.buffer.read(length)

    def readline(self):
        value = self.buffer.readline()
        self.consume(len(value) + 2)
        return value


class BoundedParser(_RESP2Parser):
    def read_response(self, disable_decoding=False):
        original = self._buffer
        self._buffer = BoundedBuffer(original)
        try:
            return super().read_response(disable_decoding=disable_decoding)
        finally:
            self._buffer = original


def validate_command(command: str, args: list[str]):
    command = command.upper()
    if command not in ALLOWED:
        raise ValueError("Redis command is not allowed")
    if len(args) > 1000 or sum(len(arg.encode()) for arg in args) > 65536:
        raise ValueError("Too many/large Redis arguments")
    # SORT-like writes and module commands cannot be smuggled through options: each
    # command is passed as one RESP token, with no command string interpretation.
    args = list(args)
    if command in {"SCAN", "HSCAN", "SSCAN", "ZSCAN"}:
        option_start = 1 if command == "SCAN" else 2
        for i, arg in enumerate(args):
            if arg.upper() == "COUNT" and i >= (1 if command == "SCAN" else 2):
                if i + 1 >= len(args) or not 1 <= int(args[i + 1]) <= 1000:
                    raise ValueError("SCAN COUNT must be 1–1000")
        if not any(a.upper() == "COUNT" for a in args[option_start:]):
            args += ["COUNT", "500"]
    if command in {"XRANGE", "XREVRANGE"}:
        if len(args) == 3:
            args += ["COUNT", "500"]
        elif len(args) != 5 or args[3].upper() != "COUNT" or not 1 <= int(args[4]) <= 1000:
            raise ValueError("Stream range requires key, start, end, optional COUNT 1–1000")
    if command in {"LRANGE", "ZRANGE", "ZREVRANGE"}:
        # Rank ranges only: predictable work; BYSCORE/BYLEX are intentionally unsupported.
        if len(args) not in {3, 4} or (len(args) == 4 and (command == "LRANGE" or args[3].upper() != "WITHSCORES")):
            raise ValueError("Use a bounded rank range, optionally WITHSCORES")
        start, end = int(args[1]), int(args[2])
        if (start < 0) != (end < 0) or end < start or end - start >= 1000:
            raise ValueError("Range must select at most 1000 ranks with matching index signs")
    return command, args


def json_value(value):
    if isinstance(value, bytes):
        # Lossless binary representation, compatible with filesystem reads.
        from .filesystem import FileReader

        return FileReader.content(value)
    if isinstance(value, (tuple, list)):
        return [json_value(item) for item in value]
    return value


class RedisReader:
    def __init__(self, url):
        self.pool = ConnectionPool.from_url(
            url,
            parser_class=BoundedParser,
            protocol=2,
            socket_timeout=5,
            socket_connect_timeout=3,
            max_connections=4,
            decode_responses=False,
        )
        self.client = Redis(connection_pool=self.pool)

    def read(self, command: str, args: list[str]):
        command, args = validate_command(command, args)
        # Raw RESP preserves SCAN cursor and avoids redis-py command-specific callbacks.
        connection = self.pool.get_connection()
        try:
            connection.send_command(command, *args)
            value = json_value(connection.read_response())
            if len(encoded(value)) > MAX_RESULT_BYTES:
                raise ResponseTooLarge()
            return {"data": value, "truncated": False}
        except ResponseTooLarge:
            return {
                "data": None,
                "truncated": True,
                "message": "Response exceeded 2 MiB; use SCAN/ranges or smaller values",
            }
        finally:
            # Never reuse a connection with an unread, oversized response.
            connection.disconnect()
            self.pool.release(connection)

    def close(self):
        self.client.close()
        self.pool.disconnect()
