"""Copy the web app into public/ so Vercel serves it from the CDN.

The Python function stays responsible for /api. Static files, including the
3D session video, must not pass through that function: its response cap splits
the video into several round trips to the function region.
"""

from pathlib import Path
import shutil


ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "web"
TARGET = ROOT / "public"
SKIP = {
    "substation-inspection-public-domain.jpg",
    "substation-inspection-2-public-domain.jpg",
}


def main() -> None:
    if TARGET.exists():
        shutil.rmtree(TARGET)
    shutil.copytree(
        SOURCE,
        TARGET,
        ignore=lambda _dir, names: [name for name in names if name in SKIP],
    )


if __name__ == "__main__":
    main()
