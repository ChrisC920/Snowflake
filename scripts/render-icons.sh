#!/bin/sh
# Rasterize Design/ artwork and install it into the Xcode project.
#   - Snowflake/Resources/AppIcon.icon      layered Liquid Glass icon (Icon Composer format)
#   - Assets.xcassets/SnowflakeMark         bare mark, vector PDF, template rendering
#   - Assets.xcassets/MenuBarIcon           18pt menu bar glyph, vector PDF, template rendering
# Requires rsvg-convert (brew install librsvg). Run scripts/make-icon-art.py first if the design changed.
set -eu
cd "$(dirname "$0")/.."

command -v rsvg-convert >/dev/null || { echo "rsvg-convert not found: brew install librsvg" >&2; exit 1; }

ICON=Snowflake/Resources/AppIcon.icon
ASSETS=Snowflake/Resources/Assets.xcassets

mkdir -p "$ICON/Assets"
for layer in sheen flake-glass flake-solid; do
  rsvg-convert -w 1024 -h 1024 "Design/icon/$layer.svg" -o "$ICON/Assets/$layer.png"
done

mkdir -p "$ASSETS/SnowflakeMark.imageset" "$ASSETS/MenuBarIcon.imageset"
rsvg-convert -f pdf Design/mark.svg -o "$ASSETS/SnowflakeMark.imageset/SnowflakeMark.pdf"
rsvg-convert -f pdf Design/menubar.svg -o "$ASSETS/MenuBarIcon.imageset/MenuBarIcon.pdf"

rsvg-convert -w 512 Design/app-icon.svg -o Design/app-icon.png
echo "Icons rendered."
