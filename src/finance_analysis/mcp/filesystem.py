"""Fixed /data jail. Descriptor-relative no-follow opens also prevent symlink races."""

import os
from pathlib import Path
import stat

from .errors import ReadValidationError
from .serialization import text_or_binary

MAX_BYTES = 1024 * 1024
MAX_ENTRIES = 2000


class FileReader:
    def __init__(self, root: Path = Path("/data")):
        self.root = root

    def open(self, path: str):
        if len(path) > 4096 or "\x00" in path or ".." in Path(path).parts:
            raise ReadValidationError("Invalid data path")
        relative = path.lstrip("/")
        # Both /logs/a and logs/a mean paths relative to the jail, never host paths.
        target = self.root / relative
        if not target.resolve().is_relative_to(self.root.resolve()):
            raise ReadValidationError("Path escapes /data")
        fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            parts = Path(relative).parts
            for i, part in enumerate(parts):
                flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
                if i < len(parts) - 1:
                    flags |= os.O_DIRECTORY
                next_fd = os.open(part, flags, dir_fd=fd)
                os.close(fd)
                fd = next_fd
            info = os.fstat(fd)
            if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
                raise ReadValidationError("Only regular files and directories are accessible")
            return fd
        except BaseException:
            os.close(fd)
            raise

    @staticmethod
    def metadata(name, info):
        kind = "file" if stat.S_ISREG(info.st_mode) else "directory" if stat.S_ISDIR(info.st_mode) else "other"
        return {"filename": name, "type": kind, "size": info.st_size, "mtime": info.st_mtime}

    def stat(self, path: str):
        fd = self.open(path)
        try:
            return self.metadata(Path(path).name or "/", os.fstat(fd))
        finally:
            os.close(fd)

    def list(self, path: str):
        fd = self.open(path)
        try:
            entries = []
            with os.scandir(fd) as iterator:
                for entry in iterator:
                    if len(entries) == MAX_ENTRIES:
                        return {"entries": entries, "truncated": True}
                    entries.append(self.metadata(entry.name, entry.stat(follow_symlinks=False)))
            return {"entries": entries, "truncated": False}
        finally:
            os.close(fd)

    def file(self, path: str):
        fd = self.open(path)
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            os.close(fd)
            raise ReadValidationError("A regular file is required")
        return os.fdopen(fd, "rb")

    @staticmethod
    def content(data):
        return text_or_binary(data)

    def read(self, path: str, offset: int = 0, max_bytes: int = 256 * 1024):
        if offset < 0 or not 1 <= max_bytes <= MAX_BYTES:
            raise ReadValidationError("offset must be nonnegative; max_bytes must be 1–1048576")
        with self.file(path) as stream:
            stream.seek(offset)
            data = stream.read(max_bytes)
            return {
                **self.content(data),
                "bytes_read": len(data),
                "next_offset": offset + len(data),
                "truncated": bool(stream.read(1)),
            }

    def tail(self, path: str, lines: int = 200):
        if not 1 <= lines <= 5000:
            raise ReadValidationError("lines must be 1–5000")
        with self.file(path) as stream:
            size = os.fstat(stream.fileno()).st_size
            start = max(0, size - MAX_BYTES)
            stream.seek(start)
            data = stream.read(MAX_BYTES)
        chunks = data.splitlines(keepends=True)
        # Discard an incomplete first line when the byte window starts mid-file.
        if start and chunks:
            chunks = chunks[1:]
        chosen = chunks[-lines:]
        return {
            **self.content(b"".join(chosen)),
            "line_count": len(chosen),
            "truncated": start > 0 or len(chunks) > lines,
        }
