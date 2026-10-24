"""نویسنده ساده DXF (نسخه R12 ASCII؛ با AutoCAD، BricsCAD، QGIS و Civil 3D باز می‌شود)."""
import re

_BAD = re.compile(r"[<>/\\\":;?*|=`]")


def layer_name(code) -> str:
    name = _BAD.sub("_", str(code or "0")).strip()[:31]
    return name or "0"


class Dxf:
    def __init__(self):
        self.ents: list[str] = []
        self.layers: dict[str, int] = {"0": 7}

    def _g(self, code, value) -> str:
        return f"{code}\n{value}\n"

    def _layer(self, name: str, color: int) -> str:
        name = layer_name(name)
        self.layers.setdefault(name, color)
        return name

    def point(self, x, y, z=0.0, layer="0", label=None, text_h=0.5):
        layer = self._layer(layer, 3)
        self.ents.append(self._g(0, "POINT") + self._g(8, layer) + self._g(10, f"{x:.4f}") + self._g(20, f"{y:.4f}")
                         + self._g(30, f"{z or 0:.4f}"))
        if label:
            self.text(x + text_h * 0.4, y + text_h * 0.4, label, layer, text_h)

    def text(self, x, y, value, layer="0", height=0.5):
        layer = self._layer(layer, 7)
        clean = str(value).replace("\n", " ")
        self.ents.append(self._g(0, "TEXT") + self._g(8, layer) + self._g(10, f"{x:.4f}") + self._g(20, f"{y:.4f}")
                         + self._g(30, "0.0") + self._g(40, f"{height:.3f}") + self._g(1, clean))

    def polyline(self, pts, layer="0", closed=False, z=0.0, color=5):
        """z: ارتفاع (elevation) پلی‌لاین دوبعدی؛ برای منحنی میزان همان سطح منحنی است."""
        layer = self._layer(layer, color)
        out = self._g(0, "POLYLINE") + self._g(8, layer) + self._g(66, 1) + self._g(10, "0.0") + self._g(20, "0.0") \
            + self._g(30, f"{z:.4f}") + self._g(70, 1 if closed else 0)
        for x, y in pts:
            out += self._g(0, "VERTEX") + self._g(8, layer) + self._g(10, f"{x:.4f}") + self._g(20, f"{y:.4f}") \
                + self._g(30, f"{z:.4f}")
        out += self._g(0, "SEQEND") + self._g(8, layer)
        self.ents.append(out)

    def dumps(self) -> str:
        head = self._g(0, "SECTION") + self._g(2, "HEADER") + self._g(9, "$ACADVER") + self._g(1, "AC1009") \
            + self._g(0, "ENDSEC")
        tables = self._g(0, "SECTION") + self._g(2, "TABLES") + self._g(0, "TABLE") + self._g(2, "LAYER") \
            + self._g(70, len(self.layers))
        for name, color in self.layers.items():
            tables += self._g(0, "LAYER") + self._g(2, name) + self._g(70, 0) + self._g(62, color) \
                + self._g(6, "CONTINUOUS")
        tables += self._g(0, "ENDTAB") + self._g(0, "ENDSEC")
        body = self._g(0, "SECTION") + self._g(2, "ENTITIES") + "".join(self.ents) + self._g(0, "ENDSEC")
        return head + tables + body + self._g(0, "EOF")
