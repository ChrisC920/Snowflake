#!/usr/bin/env python3
"""Generate Snowflake's icon artwork as SVG from one set of design constants.

Outputs (all in Design/):
  icon/sheen.svg, icon/flake-solid.svg, icon/flake-glass.svg   Icon Composer layers, 1024x1024
  app-icon.svg                                                  flattened preview with tile (README, docs)
  mark.svg                                                      bare mark, no tile (in-app UI)
  menubar.svg                                                   18pt menu bar template glyph

Run `make icons` (scripts/render-icons.sh) afterwards to rasterize and install into the Xcode project.
Design spec: docs/BRAND.md.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DESIGN = ROOT / "Design"

# Snowflake geometry in "design units": the tile is 144 units wide, centered at 0,0.
ARM = 44            # arm length from center
ARM_W = 12          # arm stroke width
BRANCH_W = 10       # branch stroke width
BRANCH = [(-13, -38), (0, -25), (13, -38)]  # one V-branch per arm
ANGLES = [0, 60, 120, 180, 240, 300]

ICON_GLASS_OPACITY = 0.76   # glass half on the app icon
MARK_GLASS_OPACITY = 0.68   # glass half on the mark and menu bar glyph (no tile behind)

GRADIENT_TOP_RIGHT = "#8ED2FF"
GRADIENT_BOTTOM_LEFT = "#2C74DA"
# Soft sheen: bands parallel to the 45° split, as (from, to, opacity) on the line x + y = c in tile units (0-144).
SHEEN = [(102, 190, 0.07), (134, 154, 0.05)]


def flake(scale: float, color: str, arm_w: float = ARM_W, branch_w: float = BRANCH_W) -> str:
    s = scale
    pts = " ".join(f"{'M' if i == 0 else 'L'}{x * s:.2f} {y * s:.2f}" for i, (x, y) in enumerate(BRANCH))
    arms = "".join(
        f'<g transform="rotate({a})">'
        f'<path d="M0 0V{-ARM * s:.2f}" stroke-width="{arm_w * s:.2f}"/>'
        f'<path d="{pts}" stroke-width="{branch_w * s:.2f}"/></g>'
        for a in ANGLES
    )
    return (f'<g stroke="{color}" stroke-linecap="round" stroke-linejoin="round" fill="none">'
            f"{arms}</g>")


def split_clips(half: float) -> str:
    """Clip paths for the top-left (solid) and bottom-right (glass) halves, split at 45° through the center."""
    e = half * 1.2
    return (f'<clipPath id="solid"><polygon points="{-e},{-e} {e},{-e} {-e},{e}"/></clipPath>'
            f'<clipPath id="glass"><polygon points="{e},{-e} {e},{e} {-e},{e}"/></clipPath>')


def svg(size: float, body: str, view: str | None = None) -> str:
    view = view or f"0 0 {size} {size}"
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="{view}">'
            f"{body}</svg>\n")


def sheen_bands(scale: float, extent: float) -> str:
    out = []
    for c1, c2, op in SHEEN:
        a, b = c1 * scale, c2 * scale
        out.append(f'<polygon points="0,{a:.1f} {a:.1f},0 {b:.1f},0 0,{b:.1f}" fill="#FFFFFF" fill-opacity="{op}"/>')
    return f'<g clip-path="url(#tile)">' + "".join(out) + "</g>"


def main() -> None:
    (DESIGN / "icon").mkdir(parents=True, exist_ok=True)
    px = 1024
    s = px / 144  # design units -> pixels
    c = px / 2

    # Icon Composer layers: full-bleed 1024 canvas; Icon Composer applies the rounded mask.
    tile_clip = f'<clipPath id="tile"><rect width="{px}" height="{px}"/></clipPath>'
    (DESIGN / "icon/sheen.svg").write_text(svg(px, f"<defs>{tile_clip}</defs>{sheen_bands(s, px)}"))
    for name, clip, op in (("flake-solid", "solid", 1.0), ("flake-glass", "glass", ICON_GLASS_OPACITY)):
        body = (f"<defs>{split_clips(c)}</defs><g transform=\"translate({c} {c})\">"
                f'<g clip-path="url(#{clip})" opacity="{op}">{flake(s, "#FFFFFF")}</g></g>')
        (DESIGN / f"icon/{name}.svg").write_text(svg(px, body))

    # Flattened preview with the macOS tile (824px rounded rect on a 1024 canvas, per Apple's grid).
    tile, r, off = 824, 185, 100
    ps = tile / 144
    preview = (
        "<defs>"
        f'<linearGradient id="bg" x1="1" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{GRADIENT_TOP_RIGHT}"/>'
        f'<stop offset="1" stop-color="{GRADIENT_BOTTOM_LEFT}"/></linearGradient>'
        f'<clipPath id="tile"><rect width="{tile}" height="{tile}" rx="{r}"/></clipPath>'
        f"{split_clips(tile / 2)}</defs>"
        f'<g transform="translate({off} {off})"><rect width="{tile}" height="{tile}" rx="{r}" fill="url(#bg)"/>'
        f"{sheen_bands(ps, tile)}"
        f'<g transform="translate({tile / 2} {tile / 2})">'
        f'<g clip-path="url(#solid)">{flake(ps, "#FFFFFF")}</g>'
        f'<g clip-path="url(#glass)" opacity="{ICON_GLASS_OPACITY}">{flake(ps, "#FFFFFF")}</g></g></g>'
    )
    (DESIGN / "app-icon.svg").write_text(svg(px, preview))

    # Bare mark (no tile), template-rendered in the app: black + alpha only.
    mark = (f"<defs>{split_clips(60)}</defs>"
            f'<g clip-path="url(#solid)">{flake(1, "#000000", 14, 12)}</g>'
            f'<g clip-path="url(#glass)" opacity="{MARK_GLASS_OPACITY}">{flake(1, "#000000", 14, 12)}</g>')
    (DESIGN / "mark.svg").write_text(svg(32, mark, "-60 -60 120 120"))

    # Menu bar glyph: 18pt template, slightly heavier strokes so it holds up at 1x.
    mb = (f"<defs>{split_clips(12)}</defs>"
          f'<g clip-path="url(#solid)">{flake(0.2272, "#000000", 9.2, 7.9)}</g>'
          f'<g clip-path="url(#glass)" opacity="{MARK_GLASS_OPACITY}">{flake(0.2272, "#000000", 9.2, 7.9)}</g>')
    (DESIGN / "menubar.svg").write_text(svg(18, mb, "-12 -12 24 24"))
    print("Wrote Design/icon/*.svg, Design/app-icon.svg, Design/mark.svg, Design/menubar.svg")


if __name__ == "__main__":
    main()
