"""生成扩展图标（纯 zlib 手写 PNG，不依赖 Pillow）。

图标含义：蓝色圆角底 + 一条白色的缠论走势折线。
运行： python tools/make_icons.py
"""
import os
import struct
import zlib

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'icons')
SIZES = [16, 32, 48, 128]

BG = (43, 108, 176, 255)      # #2b6cb0
FG = (255, 255, 255, 255)

# 归一化折线控制点（x, y），y 向下为正
POLY = [(0.16, 0.74), (0.34, 0.42), (0.52, 0.62), (0.72, 0.26), (0.88, 0.40)]


def dist_to_polyline(px, py, poly):
    best = 1e9
    for i in range(len(poly) - 1):
        ax, ay = poly[i]
        bx, by = poly[i + 1]
        dx, dy = bx - ax, by - ay
        seg = dx * dx + dy * dy
        t = 0.0 if seg == 0 else ((px - ax) * dx + (py - ay) * dy) / seg
        t = max(0.0, min(1.0, t))
        cx, cy = ax + t * dx, ay + t * dy
        d = (px - cx) ** 2 + (py - cy) ** 2
        if d < best:
            best = d
    return best ** 0.5


def in_rounded_rect(x, y, size, radius):
    r = radius
    if r < x < size - r or r < y < size - r:
        return True
    cx = min(max(x, r), size - r)
    cy = min(max(y, r), size - r)
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def render(size):
    radius = size * 0.22
    thickness = max(1.0, size * 0.075)
    rows = bytearray()
    for y in range(size):
        rows.append(0)  # filter type 0
        for x in range(size):
            px, py = (x + 0.5) / size, (y + 0.5) / size
            if not in_rounded_rect(x + 0.5, y + 0.5, size, radius):
                rows.extend((0, 0, 0, 0))
                continue
            # 注意：px/py 是归一化坐标，thickness 是像素，需先换算成同一单位
            if dist_to_polyline(px, py, POLY) < thickness / size:
                rows.extend(FG)
            else:
                rows.extend(BG)
    return bytes(rows)


def chunk(tag, data):
    return (struct.pack('>I', len(data)) + tag + data +
            struct.pack('>I', zlib.crc32(tag + data) & 0xFFFFFFFF))


def write_png(path, size):
    raw = render(size)
    header = struct.pack('>IIBBBBB', size, size, 8, 6, 0, 0, 0)  # 8bit RGBA
    png = (b'\x89PNG\r\n\x1a\n' +
           chunk(b'IHDR', header) +
           chunk(b'IDAT', zlib.compress(raw, 9)) +
           chunk(b'IEND', b''))
    with open(path, 'wb') as f:
        f.write(png)
    return len(png)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    for s in SIZES:
        p = os.path.join(OUT_DIR, 'icon%d.png' % s)
        n = write_png(p, s)
        print('OK  icon%d.png  %dx%d  %d bytes' % (s, s, s, n))


if __name__ == '__main__':
    main()
