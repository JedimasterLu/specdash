"""Copy package metadata (``*.dist-info``) into the py2app bundle.

py2app copies code but not metadata, and some dependencies read their own version
through ``importlib.metadata`` at import time (plotly does). Run after the build::

    python packaging/copy_metadata_macos.py dist/SpecDash.app
"""

import shutil
import sys
from importlib import metadata
from pathlib import Path

SKIP = {"py2app", "pip", "setuptools", "wheel", "modulegraph", "altgraph", "macholib", "specdash"}


def main(app: str) -> None:
    libs = sorted(Path(app, "Contents", "Resources", "lib").glob("python3.*"))
    if not libs:
        raise SystemExit(f"No python lib directory found inside {app}")
    target = libs[0]
    count = 0
    for dist in metadata.distributions():
        path = Path(str(dist._path))  # type: ignore[attr-defined]
        name = dist.metadata["Name"]
        if name and name.lower().replace("_", "-") not in SKIP and path.suffix == ".dist-info":
            shutil.copytree(path, target / path.name, dirs_exist_ok=True)
            count += 1
    print(f"Copied metadata of {count} distributions into {target}")


if __name__ == "__main__":
    main(sys.argv[1])
