#!/usr/bin/env python3
"""Cut the TIQ sprite sheet out of its baked-in checkerboard.

The source sheet (design-src/sprite_tiq.png) is RGB: the "transparency"
grid is painted into the pixels, so it shows on every background. This
flood-fills the neutral light checker from the image border, clears it,
softens the one-pixel fringe left around the outlines, then re-packs the
poses: the source only roughly follows its 6x4 grid (a waving hand or a
laptop spills into the next cell), so each pose is rebuilt from the
connected shapes whose centre falls in its cell and centred, with padding,
in a strict grid. Output is a WebP with real alpha for the browser.

Usage:
    python3 scripts/sprite_cutout.py [SOURCE] [DEST]

Defaults: design-src/sprite_tiq.png -> public/tiq-sprite.webp
Requires Pillow.
"""
import sys
from collections import deque
from pathlib import Path

from PIL import Image

WEB_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = WEB_ROOT / "design-src" / "sprite_tiq.png"
DEFAULT_DEST = WEB_ROOT / "public" / "tiq-sprite.webp"
NEIGHBOURS = ((1, 0), (-1, 0), (0, 1), (0, -1))
COLUMNS, ROWS = 6, 4
OUT_CELL = 320
PADDING = 14
MIN_SHAPE_PIXELS = 12  # drop specks of leftover checker


def is_checker(rgb):
    # Checker squares are white or light grey with no hue.
    return min(rgb) > 185 and max(rgb) - min(rgb) < 18


def is_fringe(rgb):
    # Antialiased edge between checker and outline: still light, any hue.
    return min(rgb) > 200


def background_mask(pixels, width, height):
    mask = bytearray(width * height)
    queue = deque((x, y) for x in range(width) for y in (0, height - 1))
    queue.extend((x, y) for y in range(height) for x in (0, width - 1))
    while queue:
        x, y = queue.popleft()
        index = y * width + x
        if mask[index] or not is_checker(pixels[x, y]):
            continue
        mask[index] = 1
        for dx, dy in NEIGHBOURS:
            nx, ny = x + dx, y + dy
            if 0 <= nx < width and 0 <= ny < height and not mask[ny * width + nx]:
                queue.append((nx, ny))
    return mask


def touches_background(mask, x, y, width, height):
    for dx, dy in NEIGHBOURS:
        nx, ny = x + dx, y + dy
        if 0 <= nx < width and 0 <= ny < height and mask[ny * width + nx]:
            return True
    return False


def remove_background(image):
    width, height = image.size
    pixels = image.load()
    mask = background_mask(pixels, width, height)
    out = image.convert("RGBA")
    out_pixels = out.load()
    for y in range(height):
        for x in range(width):
            if mask[y * width + x]:
                out_pixels[x, y] = (0, 0, 0, 0)
            elif is_fringe(pixels[x, y]) and touches_background(mask, x, y, width, height):
                r, g, b = pixels[x, y]
                out_pixels[x, y] = (r, g, b, 90)
    return out


def same_row(y, ny, height):
    row_height = height / ROWS
    return int(y / row_height) == int(ny / row_height)


def label_shapes(image):
    """Label opaque connected shapes, never connecting across a row line."""
    width, height = image.size
    alpha = image.getchannel("A").load()
    labels = [0] * (width * height)
    shapes = {}
    for start_y in range(height):
        for start_x in range(width):
            if labels[start_y * width + start_x] or alpha[start_x, start_y] == 0:
                continue
            label = len(shapes) + 1
            labels[start_y * width + start_x] = label
            queue = deque([(start_x, start_y)])
            count = sum_x = sum_y = 0
            box = [start_x, start_y, start_x, start_y]
            while queue:
                x, y = queue.popleft()
                count += 1
                sum_x += x
                sum_y += y
                box = [min(box[0], x), min(box[1], y), max(box[2], x), max(box[3], y)]
                for dx, dy in NEIGHBOURS:
                    nx, ny = x + dx, y + dy
                    if (0 <= nx < width and 0 <= ny < height and not labels[ny * width + nx]
                            and alpha[nx, ny] and same_row(y, ny, height)):
                        labels[ny * width + nx] = label
                        queue.append((nx, ny))
            column = min(COLUMNS - 1, int(sum_x / count / (width / COLUMNS)))
            row = min(ROWS - 1, int(sum_y / count / (height / ROWS)))
            shapes[label] = {"count": count, "box": box, "seed": (start_x, start_y), "cell": (column, row)}
    return labels, shapes


def reattach_spills(labels, shapes, width, height):
    """A small piece cut off by a row line (the laptop's base) belongs to the
    pose above it; a whole pose touching the one above (the bulb's glow)
    does not."""
    above_of = {}
    for row in range(1, ROWS):
        line = int(row * height / ROWS)
        for x in range(width):
            upper, lower = labels[(line - 1) * width + x], labels[line * width + x]
            if upper and lower and upper != lower:
                above_of.setdefault(lower, upper)
    for lower, upper in above_of.items():
        if shapes[lower]["count"] < 0.25 * shapes[upper]["count"]:
            shapes[lower]["cell"] = shapes[upper]["cell"]


def shapes_by_cell(image):
    """Group opaque connected shapes by the grid cell of the pose they belong to."""
    width, height = image.size
    labels, shapes = label_shapes(image)
    reattach_spills(labels, shapes, width, height)
    cells = {}
    for shape in shapes.values():
        if shape["count"] >= MIN_SHAPE_PIXELS:
            cells.setdefault(shape["cell"], []).append((shape["box"], shape["seed"]))
    return cells


def shape_layer(image, seed):
    """Copy of `image` keeping only the connected shape that contains `seed`."""
    width, height = image.size
    source = image.load()
    layer = Image.new("RGBA", image.size)
    target = layer.load()
    queue = deque([seed])
    seen = {seed}
    while queue:
        x, y = queue.popleft()
        target[x, y] = source[x, y]
        for dx, dy in NEIGHBOURS:
            nx, ny = x + dx, y + dy
            if (0 <= nx < width and 0 <= ny < height and (nx, ny) not in seen
                    and source[nx, ny][3] and same_row(y, ny, height)):
                seen.add((nx, ny))
                queue.append((nx, ny))
    return layer


def repack(image):
    cells = shapes_by_cell(image)
    sheet = Image.new("RGBA", (COLUMNS * OUT_CELL, ROWS * OUT_CELL))
    for (column, row), shapes in sorted(cells.items()):
        pose = Image.new("RGBA", image.size)
        for _, seed in shapes:
            pose.alpha_composite(shape_layer(image, seed))
        left = min(box[0] for box, _ in shapes)
        top = min(box[1] for box, _ in shapes)
        right = max(box[2] for box, _ in shapes) + 1
        bottom = max(box[3] for box, _ in shapes) + 1
        crop = pose.crop((left, top, right, bottom))
        fit = (OUT_CELL - 2 * PADDING) / max(crop.size)
        if fit < 1:
            crop = crop.resize((round(crop.width * fit), round(crop.height * fit)), Image.LANCZOS)
        # Bottom-aligned so every pose stands on the same floor line.
        x = column * OUT_CELL + (OUT_CELL - crop.width) // 2
        y = row * OUT_CELL + OUT_CELL - PADDING - crop.height
        sheet.alpha_composite(crop, (x, y))
    return sheet, len(cells)


def cut_out(source, dest):
    image = Image.open(source).convert("RGB")
    sheet, poses = repack(remove_background(image))
    if poses != COLUMNS * ROWS:
        print(f"warning: found {poses} poses, expected {COLUMNS * ROWS}", file=sys.stderr)
    dest.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(dest, "WEBP", quality=88, method=6)
    print(f"{dest}: {sheet.width}x{sheet.height}, {poses} poses")


def main(argv):
    if any(arg in ("-h", "--help") for arg in argv):
        print(__doc__)
        return 0
    source = Path(argv[0]) if argv else DEFAULT_SOURCE
    dest = Path(argv[1]) if len(argv) > 1 else DEFAULT_DEST
    if not source.is_file():
        print(f"error: source sheet not found: {source}", file=sys.stderr)
        return 1
    cut_out(source, dest)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
