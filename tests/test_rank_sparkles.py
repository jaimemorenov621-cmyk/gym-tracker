"""Destellos de los emblemas: solo en huecos vacíos (tools/place_rank_sparkles.py).

Comprueba con la máscara guardada de cada rango (alpha > 0 = ocupado, a 512 px)
que la caja de ningún destello toca un píxel ocupado, y el resto de reglas:
cantidad máxima por rango, tamaños, separación y que el generador use estas
posiciones."""
import json
import math
import os
import sys
import unittest

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import place_rank_sparkles as place  # noqa: E402

CONFIG = os.path.join(ROOT, "tools", "rank_sparkles.json")
MASKS = os.path.join(ROOT, "tools", "rank_masks")


class RankSparkleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(CONFIG, encoding="utf-8") as fh:
            cls.config = json.load(fh)

    def mask(self, key):
        img = Image.open(os.path.join(MASKS, f"{key}.png")).convert("1")
        self.assertEqual(img.size, (place.SIZE, place.SIZE))
        return img.load()

    def test_every_rank_is_configured(self):
        self.assertEqual(set(self.config), set(place.MAX_PER_RANK))

    def test_sparkle_boxes_never_touch_the_silhouette(self):
        size = place.SIZE
        for key, items in self.config.items():
            px = self.mask(key)
            for fx, fy, fr in items:
                x, y, r = fx * size, fy * size, fr * size
                x0, x1 = math.floor(x - r), math.ceil(x + r)
                y0, y1 = math.floor(y - r), math.ceil(y + r)
                self.assertTrue(0 <= x0 and x1 < size and 0 <= y0 and y1 < size, key)
                hits = [(i, j) for j in range(y0, y1 + 1) for i in range(x0, x1 + 1) if px[i, j]]
                self.assertEqual(hits, [], f"{key}: el destello en ({x:.0f}, {y:.0f}) tapa la silueta")

    def test_counts_sizes_and_separation(self):
        size = place.SIZE
        for key, items in self.config.items():
            self.assertLessEqual(len(items), place.MAX_PER_RANK[key], key)
            px = self.mask(key)
            xs = [i for j in range(size) for i in range(size) if px[i, j]]
            width = max(xs) - min(xs) + 1
            for n, (fx, fy, fr) in enumerate(items):
                diameter = 2 * fr * size / width
                self.assertGreaterEqual(diameter, place.MIN_SIZE - 1e-3, key)
                if n == 0:
                    self.assertTrue(0.06 - 1e-3 <= diameter <= 0.08 + 1e-3, f"{key}: dominante {diameter:.3f}")
                for gx, gy, _ in items[:n]:
                    gap = math.hypot((fx - gx) * size, (fy - gy) * size)
                    self.assertGreaterEqual(gap, place.SEPARATION * width - 1, key)

    def test_generator_uses_the_saved_positions(self):
        import make_rank_emblems as mre
        for key, items in self.config.items():
            svg = mre.build(key, 3 if key == "titan" else 1)
            group = svg.split('<g id="sparkles">', 1)[1].split("</g>", 1)[0] if items else ""
            self.assertEqual(group.count("<path"), len(items), key)
            self.assertEqual('<g id="sparkles">' in svg, bool(items), key)
            small = mre.build(key, 3 if key == "titan" else 1, sparkle=False)
            self.assertNotIn('id="sparkles"', small)


if __name__ == "__main__":
    unittest.main()
