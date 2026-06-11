#!/usr/bin/env python3
"""Generate icons for the browser extension using only stdlib."""
import struct
import zlib
import os

def make_png(size, color=(0, 120, 212)):
    """Create a minimal valid PNG with the SE downloader icon."""
    w = h = size
    r, g, b = color

    # Build pixel data (RGBA)
    pixels = []
    for y in range(h):
        row = []
        for x in range(w):
            # Circle background
            cx, cy = w / 2, h / 2
            radius = w * 0.45
            dist = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5

            if dist <= radius:
                # Arrow down icon
                center_x = w / 2
                # Vertical line
                in_line = (abs(x - center_x) <= w * 0.08) and (y >= h * 0.2) and (y <= h * 0.65)
                # Arrow head
                progress = (y - h * 0.45) / (h * 0.25)  # 0 to 1
                half_width = w * 0.22 * progress if 0 <= progress <= 1 else 0
                in_arrow = (abs(x - center_x) <= half_width) and (h * 0.45 <= y <= h * 0.7)
                # Base line
                in_base = (abs(y - h * 0.78) <= h * 0.06) and (w * 0.25 <= x <= w * 0.75)

                if in_line or in_arrow or in_base:
                    row.extend([255, 255, 255, 255])
                else:
                    row.extend([r, g, b, 255])
            else:
                row.extend([0, 0, 0, 0])
        pixels.append(bytes(row))

    # PNG file structure
    def chunk(name, data):
        c = struct.pack(">I", len(data)) + name + data
        return c + struct.pack(">I", zlib.crc32(name + data) & 0xFFFFFFFF)

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))

    raw = b""
    for row in pixels:
        raw += b"\x00" + row

    idat = chunk(b"IDAT", zlib.compress(raw, 9))
    iend = chunk(b"IEND", b"")

    return sig + ihdr + idat + iend


if __name__ == "__main__":
    icons_dir = os.path.join(os.path.dirname(__file__), "browser_extension", "icons")
    os.makedirs(icons_dir, exist_ok=True)

    for size in [16, 48, 128]:
        data = make_png(size)
        path = os.path.join(icons_dir, f"icon{size}.png")
        with open(path, "wb") as f:
            f.write(data)
        print(f"Generated {path} ({size}x{size})")

    print("Icons generated successfully.")
