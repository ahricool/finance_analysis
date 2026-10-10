"""Bounded, format-verified avatar normalization; no storage or transport concerns."""

from io import BytesIO
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_AVATAR_BYTES = 5 * 1024 * 1024
MAX_AVATAR_PIXELS = 16_000_000
AVATAR_FORMATS = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}


class InvalidAvatar(ValueError):
    pass


def normalize_avatar(blob: bytes, content_type: str) -> bytes:
    if content_type not in AVATAR_FORMATS:
        raise InvalidAvatar("仅支持 JPEG、PNG 和 WebP 图片")
    if not blob or len(blob) > MAX_AVATAR_BYTES:
        raise InvalidAvatar("头像不能为空且不能超过 5MB")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(blob)) as probe:
                if probe.format != AVATAR_FORMATS[content_type]:
                    raise InvalidAvatar("图片内容与声明格式不一致")
                if probe.width * probe.height > MAX_AVATAR_PIXELS:
                    raise InvalidAvatar("图片像素过大，请选择不超过 1600 万像素的图片")
                if getattr(probe, "is_animated", False):
                    raise InvalidAvatar("请上传静态图片")
                probe.verify()
            with Image.open(BytesIO(blob)) as source:
                source.load()
                oriented = ImageOps.exif_transpose(source)
                mode = "RGBA" if "A" in oriented.getbands() or "transparency" in oriented.info else "RGB"
                cropped = ImageOps.fit(
                    oriented.convert(mode), (256, 256), Image.Resampling.LANCZOS, centering=(0.5, 0.5)
                )
                # Copy only pixels, dropping EXIF/XMP/ICC and other source metadata.
                clean = Image.new(mode, (256, 256))
                clean.paste(cropped)
                output = BytesIO()
                clean.save(output, format="WEBP", quality=82)
                return output.getvalue()
    except (
        UnidentifiedImageError,
        OSError,
        SyntaxError,
        ValueError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        if isinstance(exc, InvalidAvatar):
            raise
        raise InvalidAvatar("图片内容无效或已损坏") from exc
