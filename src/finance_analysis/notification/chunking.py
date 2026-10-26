"""Lossless UTF-8 bounded chunks shared by notification transports."""

MESSAGE_LIMIT_BYTES = 4096


def split_message(content: str, *, fits=None) -> list[str]:
    """Prefer line boundaries, split long lines, and reserve multipart numbering."""
    extra_fits = fits

    def fits(message):
        return (len(message.encode("utf-8")) <= MESSAGE_LIMIT_BYTES
                and (extra_fits is None or extra_fits(message)))

    if fits(content):
        return [content]
    # The number of parts cannot exceed the number of characters. Reserve the
    # largest possible numbering prefix, including it in both byte limits.
    digits = len(str(len(content)))
    reserved_prefix = f"[{'9' * digits}/{'9' * digits}]\n"
    if not fits(reserved_prefix):
        raise ValueError("Notification metadata leaves no room for multipart messages")
    chunks = []
    offset = 0
    while offset < len(content):
        low, high = 0, min(len(content) - offset, MESSAGE_LIMIT_BYTES)
        while low < high:
            middle = (low + high + 1) // 2
            if fits(reserved_prefix + content[offset:offset + middle]):
                low = middle
            else:
                high = middle - 1
        if not low:
            raise ValueError("Notification metadata leaves no room for a message character")
        # Prefer whole lines when possible, retaining the newline and all text.
        newline = content.rfind("\n", offset, offset + low)
        if newline >= offset + low // 2:
            low = newline + 1 - offset
        chunks.append(content[offset:offset + low])
        offset += low
    return [f"[{index}/{len(chunks)}]\n" + chunk for index, chunk in enumerate(chunks, 1)]

