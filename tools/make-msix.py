"""Stage the Windows one-folder build, manifest and tile assets for makeappx."""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from string import Template
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
IDENTITY_DEFAULTS = {
    "MSIX_IDENTITY_NAME": "StetSoftware.Annotshot",
    "MSIX_PUBLISHER": "CN=Stet Software",
    "MSIX_PUBLISHER_DISPLAY": "Stet Software",
}
ASSETS = {
    "Square44x44Logo.png": (44, 44),
    "Square150x150Logo.png": (150, 150),
    "Wide310x150Logo.png": (310, 150),
    "StoreLogo.png": (50, 50),
    "Square44x44Logo.targetsize-44_altform-unplated.png": (44, 44),
}


class StopParser(argparse.ArgumentParser):
    def error(self, message):
        print(f"STOP {message}")
        raise SystemExit(1)


def stage(dist: Path, version: str, out: Path) -> None:
    """Build a fresh layout without touching the frozen build's contents."""
    if not (dist / "Annotshot.exe").is_file():
        raise ValueError(f"no Annotshot.exe in {dist}")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise ValueError("version must be three numbers, for example 0.3.1")
    parts = [int(part) for part in version.split(".")]
    if any(part > 65535 for part in parts):
        raise ValueError("each version number must be at most 65535")
    identity = {name: os.environ.get(name, default)
                for name, default in IDENTITY_DEFAULTS.items()}
    for name, value in identity.items():
        if not value.strip():
            raise ValueError(f"{name} must not be empty")
    dist, out = dist.resolve(), out.resolve()
    if dist == out or dist in out.parents or out in dist.parents:
        raise ValueError("dist and out must be separate folders")
    # A retry may replace a generated package, never an unrelated folder.
    if out.exists() and (not out.is_dir() or (any(out.iterdir()) and not
            ((out / "AppxManifest.xml").is_file() and
             (out / "Annotshot.exe").is_file()))):
        raise ValueError(f"out is not an empty folder or an MSIX layout: {out}")
    try:
        from PIL import Image, ImageOps
    except ImportError:
        raise ValueError("Pillow is needed: run python -m pip install Pillow") from None

    # icon.png is make_icon.py's original, before its 256 px ICO limit.
    source = ROOT / "icon.png"
    if not source.is_file():
        source = ROOT / "annotshot.ico"
    with Image.open(source) as image:
        icon = image.convert("RGBA")
    template = Template((ROOT / "packaging/msix/AppxManifest.xml.in").read_text(
        encoding="utf-8"))
    values = [escape(value, {'"': "&quot;", "'": "&apos;"})
              for value in identity.values()]
    manifest = template.substitute(
        identity_name=values[0], publisher=values[1], publisher_display=values[2],
        version=".".join(str(part) for part in parts) + ".0")
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".msix-", dir=out.parent) as tmp:
        layout = Path(tmp) / "package"
        shutil.copytree(dist, layout)
        # python-docx ships this unpacked source of default.docx and never opens
        # it. Its [Content_Types].xml is a name MakeAppx refuses (0x8007007b).
        unused = layout / "_internal/docx/templates/default-docx-template"
        if unused.is_dir():
            shutil.rmtree(unused)
        illegal = sorted(path.relative_to(layout).as_posix()
                         for path in layout.rglob("*") if set(path.name) & set("[]"))
        if illegal:
            raise ValueError("a name MakeAppx refuses: " + ", ".join(illegal))
        (layout / "AppxManifest.xml").write_text(manifest, encoding="utf-8")
        assets = layout / "Assets"
        assets.mkdir(exist_ok=True)
        for name, size in ASSETS.items():
            # Preserve the picture's aspect ratio, including on the wide tile.
            picture = ImageOps.contain(icon, size, Image.Resampling.LANCZOS)
            tile = Image.new("RGBA", size, (0, 0, 0, 0))
            tile.alpha_composite(picture, ((size[0] - picture.width) // 2,
                                           (size[1] - picture.height) // 2))
            tile.save(assets / name)
        if out.exists():
            shutil.rmtree(out)
        layout.rename(out)
    print("MSIX identity: " + " | ".join(f"{name}={value}"
                                        for name, value in identity.items()))
    print(f"MSIX layout ready: {out}")


def main(argv=None) -> int:
    parser = StopParser(description=__doc__)
    parser.add_argument("--dist", required=True, type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        stage(args.dist, args.version, args.out)
    except (OSError, ValueError, shutil.Error) as error:
        print(f"STOP {error}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
