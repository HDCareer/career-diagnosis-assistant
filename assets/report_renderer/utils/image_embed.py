from __future__ import annotations

import base64
import io
from pathlib import Path


SUPPORTED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def image_to_png_data_uri(image_path: str, max_side: int = 600) -> str:
    path = Path(image_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Image file does not exist: {path}")
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_IMAGE_SUFFIXES:
        raise ValueError("Image must be PNG, JPG, JPEG, or WEBP.")

    try:
        from PIL import Image
    except ImportError:
        if suffix != ".png":
            raise RuntimeError("Pillow is required to convert non-PNG images into PNG data URIs.")
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:image/png;base64,{encoded}"

    with Image.open(path) as image:
        image = image.convert("RGBA")
        width, height = image.size
        longest = max(width, height)
        if longest > max_side:
            scale = max_side / longest
            image = image.resize((round(width * scale), round(height * scale)), Image.Resampling.LANCZOS)
        output = io.BytesIO()
        image.save(output, format="PNG", optimize=True)
    encoded = base64.b64encode(output.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"