"""Create ``packaging/specdash.icns`` from the Windows icon (needs Pillow, a matplotlib dependency)."""

from pathlib import Path

from PIL import Image

here = Path(__file__).parent
Image.open(here / "specdash.ico").convert("RGBA").resize((256, 256)).save(here / "specdash.icns")
