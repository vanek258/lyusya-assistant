"""Пиксельная героиня Люся.

Образ: длинные прямые чёрные волосы, красная кепка-восьмиклинка со звёздочками,
тонированные очки без оправы, красный кроп-топ с вышивкой-колоском на рукавах,
джинсовые шорты с красным ремнём в люверсах, белые носки и красные туфли.

Каждый кадр рисуется кодом на сетке 48×48 «больших пикселей»: сначала волосы
сзади, потом одежда, лицо, кепка, руки и предметы в руках. Затем вокруг фигуры
автоматически проводится тёмный контур — как в настоящем пиксель-арте.

Поза (Pose) говорит, что именно рисовать. gui.py каждый кадр выбирает позу,
а render() превращает её в картинку — из смены поз и получается анимация.
"""

import math
from dataclasses import dataclass

SIZE = 48
CX = 23.5   # центр фигуры по горизонтали
SIT_DY = 6  # насколько опускается верх тела, когда героиня сидит

C = {
    "outline": "#1c1016",
    "hair": "#24202b", "hair_shade": "#15121a", "hair_back": "#110e14", "hair_light": "#4d4760",
    "skin": "#f6d5c2", "skin_shade": "#e2b29b", "blush": "#f0a49a", "mole": "#6b3a30",
    "eye_dark": "#1f120e", "eye": "#4e2c20", "eye_light": "#8a5a42", "white": "#ffffff",
    "lash": "#140b0e",
    "lips": "#c93347", "lips_dark": "#97202f", "mouth_in": "#5a1520",
    "cap": "#b81f30", "cap_shade": "#8c1624", "cap_dark": "#6e101b", "cap_light": "#d9404f",
    "pin": "#eceaf4", "pin_shade": "#a6a3b8",
    "glass_rim": "#dcdbe8",
    "top": "#b3202f", "top_shade": "#861523", "top_light": "#d23a48", "stitch": "#f4eef0",
    "belt": "#a3182c", "metal": "#d9d8e4",
    "denim": "#8fb2d6", "denim_shade": "#6c90b8", "denim_light": "#bcd3ea",
    "sock": "#f6f4f8", "sock_shade": "#cfcbd8",
    "shoe": "#c41e33", "shoe_dark": "#85101f",
    "phones": "#2b2b36", "phones_band": "#2b2b36", "phones_light": "#ff5a6e",
    "rice": "#fbfbff", "rice_shade": "#dcdcec", "nori": "#24443a",
    "book": "#3d4f8c", "page": "#fffaf0", "page_line": "#c9c2b0",
    "pan": "#4a4a5e", "pan_dark": "#2e2e3c", "egg": "#ffffff", "yolk": "#ffc53d",
    "steam": "#e9e9f4",
    "pillow": "#f4f1ff", "pillow_shade": "#cfc8ea",
    "blanket": "#e8eef8", "blanket_shade": "#b8c4dc", "blanket_dot": "#c93347",
    "glyph": "#ffd34d", "note": "#ff8fb0", "heart": "#ff4f6d", "zzz": "#a8d8ff",
}

# Тонированные стёкла очков: сверху розоватые, снизу голубые (как на фото)
LENS_TINT = ["#f0a6d6", "#e0a8e6", "#c8aef0", "#b4b8f2", "#a4c6f2", "#9cd0f2"]

# Пиксельные значки над головой (1 — закрашено)
GLYPHS = {
    "!": ["1", "1", "1", "0", "1"],
    "?": ["111", "001", "011", "000", "010"],
    ".": ["0", "0", "0", "0", "1"],
    "Z": ["111", "001", "010", "100", "111"],
    "+": ["000", "010", "111", "010", "000"],
    "-": ["000", "000", "111", "000", "000"],
    "x": ["000", "101", "010", "101", "000"],
    "♪": ["0011", "0010", "0010", "1110", "1110"],
    "♥": ["01010", "11111", "11111", "01110", "00100"],
}
GLYPH_COLORS = {"Z": "zzz", "♪": "note", "♥": "heart"}

# Нижний край чёлки для каждого столбца лица (x = 15..32) — видна, только когда она без кепки
BANGS = [17, 13, 11, 10, 11, 11, 10, 12, 13, 11, 12, 10, 11, 11, 10, 11, 13, 17]

# Радужка глаза построчно: D — тёмная, E — основная, L — светлая, W — блик
IRIS = {
    "open": (13, ["DDDD", "WDDE", "EDDE", "EEEE", "LEEL"]),
    "big": (12, ["DDDD", "WDDE", "WDDE", "EDDE", "EEEE", "LEEL"]),
    "down": (15, ["DDDD", "EDDE", "LEEL"]),
    "up": (13, ["WDDE", "EDDE", "EEEE", "LEEL"]),
    "sad": (14, ["WDDE", "EDDE", "EEEE", "LEEL"]),
}
IRIS_COLORS = {"D": "eye_dark", "E": "eye", "L": "eye_light", "W": "white"}

# Руки: (плечо, локоть, запястье) для левой и правой руки в координатах стоящей фигуры
_L_DOWN = ((17, 26), (16, 31), (15, 34))
_R_DOWN = ((30, 26), (31, 31), (32, 34))
_L_UP = ((17, 26), (14, 22), (13, 17))
_R_UP = ((30, 26), (33, 22), (34, 17))
_L_LAP = ((17, 26), (17, 31), (20, 34))
ARMS = {
    "down": (_L_DOWN, _R_DOWN),
    "wave1": (_L_DOWN, ((30, 26), (34, 24), (36, 19))),
    "wave2": (_L_DOWN, ((30, 26), (35, 25), (38, 21))),
    "ear": (_L_DOWN, ((30, 26), (34, 23), (34, 18))),
    "chin": (((17, 26), (18, 31), (24, 31)), ((30, 26), (31, 30), (27, 24))),
    "up": (_L_UP, _R_UP),
    "lap": (_L_LAP, ((30, 26), (30, 31), (27, 34))),
    "eat_bite": (_L_LAP, ((30, 26), (31, 29), (28, 24))),
    "eat_hold": (_L_LAP, ((30, 26), (31, 31), (30, 28))),
    "book": (((17, 26), (17, 31), (19, 31)), ((30, 26), (30, 31), (28, 31))),
    "pan": (((17, 26), (14, 30), (16, 34)), ((30, 26), (33, 29), (36, 29))),
    "dance1": (_L_UP, _R_DOWN),
    "dance2": (_L_DOWN, _R_UP),
}


@dataclass(frozen=True)
class Pose:
    body: str = "stand"    # stand, walk1, walk2, sit, lie
    arms: str = "down"     # см. ARMS
    eyes: str = "open"     # open, blink, happy, big, closed, down, up, sad
    mouth: str = "smile"   # smile, open, flat, o
    look: int = 0          # куда смотрят зрачки: -1, 0, 1
    dy: int = 0            # покачивание верхней части тела (дыхание, прыжок)
    dx: int = 0            # сдвиг всей фигуры (танец)
    flip: bool = False     # смотрит влево
    headphones: bool = False
    prop: int = 0          # стадия предмета: укусы онигири, перелистывание, подброс яичницы
    steam: int = -1        # кадр пара над сковородкой (-1 — нет)
    effect: str = ""       # значок над головой
    effect_dy: int = 0


class Grid:
    """Холст из больших пикселей. None — прозрачный пиксель."""

    def __init__(self, w=SIZE, h=SIZE):
        self.w, self.h = w, h
        self.p = [[None] * w for _ in range(h)]

    def set(self, x, y, color):
        x, y = int(x), int(y)
        if 0 <= x < self.w and 0 <= y < self.h:
            self.p[y][x] = C.get(color, color)

    def get(self, x, y):
        return self.p[y][x] if 0 <= x < self.w and 0 <= y < self.h else None

    def tint(self, x, y, color, alpha):
        """Подмешивает цвет к уже нарисованному пикселю (для тонированных стёкол)."""
        base = self.get(x, y)
        if base is None:
            return
        mix = [round(int(base[i:i + 2], 16) * (1 - alpha) + int(color[i:i + 2], 16) * alpha) for i in (1, 3, 5)]
        self.set(x, y, "#%02x%02x%02x" % tuple(mix))

    def rect(self, x0, y0, x1, y1, color):
        for y in range(int(y0), int(y1) + 1):
            for x in range(int(x0), int(x1) + 1):
                self.set(x, y, color)

    def ellipse(self, cx, cy, rx, ry, color):
        for y in range(int(cy - ry) - 1, int(cy + ry) + 2):
            for x in range(int(cx - rx) - 1, int(cx + rx) + 2):
                if ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1:
                    self.set(x, y, color)

    def line(self, x0, y0, x1, y1, color, width=1):
        """Линия квадратной кистью ширины width."""
        n = max(abs(x1 - x0), abs(y1 - y0), 1)
        lo, hi = -((width - 1) // 2), width // 2
        for i in range(n + 1):
            x = round(x0 + (x1 - x0) * i / n)
            y = round(y0 + (y1 - y0) * i / n)
            self.rect(x + lo, y + lo, x + hi, y + hi, color)

    def outline(self, color):
        """Обводит фигуру: прозрачные пиксели рядом с закрашенными становятся контуром."""
        edge = [
            (x, y) for y in range(self.h) for x in range(self.w)
            if self.p[y][x] is None and any(
                self.get(x + dx, y + dy) is not None for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))
        ]
        for x, y in edge:
            self.set(x, y, color)

    def flipped(self):
        g = Grid(self.w, self.h)
        g.p = [row[::-1] for row in self.p]
        return g

    def shifted(self, dx):
        g = Grid(self.w, self.h)
        for y in range(self.h):
            for x in range(self.w):
                g.p[y][x] = self.get(x - dx, y)
        return g

    def merge(self, other):
        """Накладывает непрозрачные пиксели другого холста поверх этого."""
        for y in range(self.h):
            for x in range(self.w):
                if other.p[y][x] is not None:
                    self.p[y][x] = other.p[y][x]


# --- Сборка кадра -------------------------------------------------------------

def render(p: Pose) -> Grid:
    g = Grid()
    if p.body == "lie":
        _sleeping(g, p)
        top = 21
    else:
        top = p.dy + (SIT_DY if p.body == "sit" else 0)
        _back_hair(g, top)
        _legs(g, p.body)
        _torso(g, top)
        _head(g, 0, top, p)
        _arms(g, top, p.arms)
        _props(g, top, p)
    g.outline("outline")
    if p.flip:
        g = g.flipped()
    if p.dx:
        g = g.shifted(p.dx)
    _effects(g, p, top)
    return g


# --- Части тела ---------------------------------------------------------------

def _back_hair(g, top):
    """Длинные прямые волосы за спиной (рисуются первыми, тело их перекрывает)."""
    g.ellipse(CX, 13 + top, 12, 11, "hair_back")
    for y in range(14 + top, 43 + top):
        half = 12 - (y - 14 - top) * 0.06
        for x in range(int(CX - half), int(CX + half) + 1):
            if y <= 40 + top + (0, 2, 1, 2, 0, 1)[x % 6]:  # неровные кончики
                g.set(x, y, "hair_back")


def _legs(g, body):
    """Шорты с ремнём, ноги, носки и туфли (не качаются при дыхании)."""
    if body == "sit":
        _belt(g, 15, 32, 40)
        g.rect(14, 41, 33, 43, "denim")
        for x in range(14, 34, 2):
            g.set(x, 43, "denim_light")  # бахрома
        g.rect(23, 41, 24, 42, "denim_shade")
        for cx in (19.5, 27.5):  # колени
            g.ellipse(cx, 44.6, 2.8, 2.1, "skin")
            g.set(cx + 1.5 if cx < CX else cx - 1.5, 45, "skin_shade")
        g.rect(12, 45, 14, 45, "sock")
        g.rect(33, 45, 35, 45, "sock")
        g.rect(11, 46, 14, 46, "shoe")
        g.rect(33, 46, 36, 46, "shoe")
        return

    _belt(g, 17, 30, 34)
    g.rect(17, 35, 30, 36, "denim")
    g.rect(17, 37, 22, 38, "denim")
    g.rect(25, 37, 30, 38, "denim")
    g.rect(23, 35, 24, 36, "denim_shade")  # шов посередине
    g.set(18, 35, "denim_light")
    g.set(29, 35, "denim_light")
    for x in list(range(17, 23)) + list(range(25, 31)):
        if x % 2:
            g.set(x, 38, "denim_light")  # потёртый край
    for leg_x, lifted in ((18, body == "walk1"), (26, body == "walk2")):
        lift = 1 if lifted else 0
        inner = leg_x + 3 if leg_x < 24 else leg_x
        g.rect(leg_x, 39 - lift, leg_x + 3, 41 - lift, "skin")
        g.rect(inner, 39 - lift, inner, 41 - lift, "skin_shade")
        g.rect(leg_x, 42 - lift, leg_x + 3, 44 - lift, "sock")
        g.rect(leg_x, 42 - lift, leg_x + 3, 42 - lift, "sock_shade")
        toe = -1 if leg_x < 24 else 1
        g.rect(leg_x, 45 - lift, leg_x + 3, 45 - lift, "shoe")
        g.rect(leg_x + min(toe, 0), 46 - lift, leg_x + 3 + max(toe, 0), 46 - lift, "shoe_dark")


def _belt(g, x0, x1, y):
    """Красный ремень с металлическими люверсами."""
    g.rect(x0, y, x1, y, "belt")
    for x in range(x0 + 2, x1, 3):
        g.set(x, y, "metal")


def _torso(g, top):
    """Красный кроп-топ, открытый живот."""
    g.rect(22, 22 + top, 25, 23 + top, "skin")
    g.rect(22, 22 + top, 25, 22 + top, "skin_shade")  # тень от подбородка
    for y in range(24, 32):
        x0, x1 = (19, 28) if y == 24 else (18, 29) if y == 25 else (17, 30)
        g.rect(x0, y + top, x1, y + top, "top")
        g.set(x0, y + top, "top_shade")
        g.set(x1, y + top, "top_shade")
    g.rect(21, 24 + top, 26, 24 + top, "skin")  # вырез
    g.rect(22, 25 + top, 25, 25 + top, "skin")
    g.rect(20, 26 + top, 20, 29 + top, "top_light")  # блик на ткани
    g.rect(17, 31 + top, 30, 31 + top, "top_shade")  # низ топа
    # живот
    g.rect(18, 32 + top, 29, 33 + top, "skin")
    g.set(18, 32 + top, "skin_shade")
    g.set(29, 32 + top, "skin_shade")
    g.set(24, 33 + top, "skin_shade")


def _head(g, ox, oy, p, cap=True, glasses=True):
    face = lambda x, y: (((x - CX - ox) / 8.5) ** 2 + ((y - 15 - oy) / 8) ** 2 <= 1
                         or ((x - CX - ox) / 6) ** 2 + ((y - 19 - oy) / 4.5) ** 2 <= 1)
    g.ellipse(CX + ox, 15 + oy, 8.5, 8, "skin")
    g.ellipse(CX + ox, 19 + oy, 6, 4.5, "skin")

    if cap:
        _cap(g, ox, oy, face)
    else:
        _bangs(g, ox, oy, face)

    # длинные пряди по бокам лица, с бликом
    for y in range(10, 37):
        width = 4 if y < 31 else 3 if y < 34 else 2
        for i in range(width):
            g.set(12 + (4 - width) + i + ox, y + oy, "hair")
            g.set(35 - (4 - width) - i + ox, y + oy, "hair")
        if width == 4:
            g.set(15 + ox, y + oy, "hair_shade")
            g.set(32 + ox, y + oy, "hair_shade")
        if 14 <= y <= 22:
            g.set(13 + ox, y + oy, "hair_light")
            g.set(34 + ox, y + oy, "hair_light")

    if p.headphones:
        for x in range(10, 38):
            t = (x + 0.5 - CX) / 13.5
            if abs(t) <= 1:
                g.set(x + ox, round(12 - 12 * math.sqrt(1 - t * t)) + oy, "phones_band")
        g.rect(9 + ox, 11 + oy, 11 + ox, 17 + oy, "phones")
        g.rect(36 + ox, 11 + oy, 38 + ox, 17 + oy, "phones")
        g.set(10 + ox, 13 + oy, "phones_light")
        g.set(37 + ox, 13 + oy, "phones_light")

    _eyes(g, ox, oy, p)
    if glasses:
        _glasses(g, ox, oy)
    g.set(24 + ox, 18 + oy, "skin_shade")  # носик
    for x in (16, 17, 31, 30):
        g.set(x + ox, 18 + oy, "blush")
    _mouth(g, ox, oy, p.mouth)
    g.set(27 + ox, 21 + oy, "mole")  # родинка у губ


def _cap(g, ox, oy, face):
    """Красная кепка-восьмиклинка, чуть сдвинутая набок, со звёздочками-значками."""
    # Плоская макушка, сдвинута вправо и нависает над козырьком
    halves = {3: 8, 4: 11, 5: 12.5, 6: 13.5, 7: 14, 8: 14, 9: 13.5}
    cx = CX + 1.5
    for y, half in halves.items():
        for x in range(int(cx - half), int(cx + half) + 1):
            color = "cap"
            if y <= 4 and x < cx:
                color = "cap_light"
            elif y >= 8:
                color = "cap_shade"
            elif x % 3 == 0 and y >= 5:
                color = "cap_shade"  # рубчик ткани
            g.set(x + ox, y + oy, color)
    g.set(25 + ox, 3 + oy, "cap_shade")  # пуговка сверху
    g.rect(13 + ox, 10 + oy, 37 + ox, 10 + oy, "cap_dark")  # козырёк
    g.rect(15 + ox, 11 + oy, 34 + ox, 11 + oy, "cap_dark")
    for sx, sy in ((30, 6), (34, 7)):  # звёздочки
        for dx, dy in ((0, -1), (-1, 0), (1, 0), (0, 1)):
            g.set(sx + dx + ox, sy + dy + oy, "pin")
        g.set(sx + ox, sy + oy, "pin_shade")
    for x in range(15, 33):  # тень от козырька на лбу
        if face(x + ox, 12 + oy):
            g.set(x + ox, 12 + oy, "skin_shade")
    # выбившиеся пряди у висков
    for x, y in ((15, 12), (16, 12), (15, 13), (32, 12), (31, 12), (32, 13)):
        g.set(x + ox, y + oy, "hair")


def _bangs(g, ox, oy, face):
    """Волосы на макушке и чёлка — когда кепка снята (во сне)."""
    for y in range(oy, 14 + oy):
        for x in range(int(CX + ox - 12), int(CX + ox + 13)):
            if ((x - CX - ox) / 11) ** 2 + ((y - 12 - oy) / 10) ** 2 > 1:
                continue
            col = x - ox - 15
            if not 0 <= col < len(BANGS) or y - oy <= BANGS[col]:
                g.set(x, y, "hair")
    for col, bottom in enumerate(BANGS):
        x = col + 15 + ox
        g.set(x, bottom + oy, "hair_shade")
        if face(x, bottom + 1 + oy):
            g.set(x, bottom + 1 + oy, "skin_shade")
    for x in (18, 19, 20, 27, 28, 29):
        g.set(x + ox, 5 + oy, "hair_light")


def _eyes(g, ox, oy, p):
    for x0 in (17, 27):
        x = x0 + ox
        if p.eyes in IRIS:
            first_row, rows = IRIS[p.eyes]
            lash = first_row - 1
            g.rect(x - 1, lash + oy, x + 4, lash + oy, "lash")
            g.set(x - 2 if x0 == 17 else x + 5, lash + 1 + oy, "lash")  # стрелка
            for ry, row in enumerate(rows):
                for rx, ch in enumerate(row):
                    g.set(x + rx + p.look, first_row + ry + oy, IRIS_COLORS[ch])
        elif p.eyes == "blink":
            g.rect(x - 1, 16 + oy, x + 4, 16 + oy, "lash")
        elif p.eyes == "happy":  # глаза-дужки ^ ^
            for dx, dy in ((1, 14), (2, 14), (0, 15), (3, 15), (-1, 16), (4, 16)):
                g.set(x + dx, dy + oy, "lash")
        elif p.eyes == "closed":  # спящие глаза ‿ ‿
            for dx, dy in ((-1, 15), (4, 15), (0, 16), (3, 16), (1, 16), (2, 16)):
                g.set(x + dx, dy + oy, "lash")


def _glasses(g, ox, oy):
    """Очки без оправы: стёкла подмешивают оттенок к тому, что под ними."""
    for a in (15, 26):
        for row in range(6):
            y = 12 + row + oy
            cut = 1 if row in (0, 5) else 0  # скруглённые углы
            for x in range(a + cut, a + 7 - cut):
                g.tint(x + ox, y, LENS_TINT[row], 0.28)
        g.set(a + 1 + ox, 13 + oy, "white")  # блик
    g.rect(22 + ox, 13 + oy, 25 + ox, 13 + oy, "glass_rim")  # перемычка
    g.rect(13 + ox, 13 + oy, 14 + ox, 13 + oy, "glass_rim")  # дужки
    g.rect(33 + ox, 13 + oy, 34 + ox, 13 + oy, "glass_rim")


def _mouth(g, ox, oy, mouth):
    """Красные губы: верхняя темнее, нижняя светлее."""
    if mouth == "smile":
        g.set(22 + ox, 19 + oy, "lips_dark")
        g.set(25 + ox, 19 + oy, "lips_dark")
        g.rect(23 + ox, 20 + oy, 24 + ox, 20 + oy, "lips_dark")
        g.rect(23 + ox, 21 + oy, 24 + ox, 21 + oy, "lips")
    elif mouth == "open":
        g.rect(22 + ox, 20 + oy, 25 + ox, 20 + oy, "lips_dark")
        g.rect(22 + ox, 21 + oy, 25 + ox, 21 + oy, "mouth_in")
        g.rect(23 + ox, 22 + oy, 24 + ox, 22 + oy, "lips")
    elif mouth == "o":
        g.rect(23 + ox, 20 + oy, 24 + ox, 20 + oy, "lips_dark")
        g.rect(23 + ox, 21 + oy, 24 + ox, 21 + oy, "mouth_in")
        g.rect(23 + ox, 22 + oy, 24 + ox, 22 + oy, "lips")
    else:
        g.rect(22 + ox, 20 + oy, 25 + ox, 20 + oy, "lips_dark")
        g.rect(23 + ox, 21 + oy, 24 + ox, 21 + oy, "lips")


def _arms(g, top, arms):
    """Рукава — толстая линия с собственным контуром и вышивкой-колоском, кисти — квадратиком."""
    for points in ARMS[arms]:
        pts = [(x, y + top) for x, y in points]
        (ex, ey), (wx, wy) = pts[-2], pts[-1]
        length = math.hypot(wx - ex, wy - ey) or 1
        hand = (round(wx + (wx - ex) / length * 2), round(wy + (wy - ey) / length * 2))
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            g.line(x0, y0, x1, y1, "outline", 5)
        g.rect(hand[0] - 2, hand[1] - 2, hand[0] + 2, hand[1] + 2, "outline")
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            g.line(x0, y0, x1, y1, "top", 3)
        for t in (0.3, 0.6):  # вышивка на предплечье
            g.set(round(ex + (wx - ex) * t), round(ey + (wy - ey) * t), "stitch")
        g.rect(hand[0] - 1, hand[1] - 1, hand[0] + 1, hand[1] + 1, "skin")


# --- Предметы -----------------------------------------------------------------

def _props(g, top, p):
    if p.arms in ("eat_bite", "eat_hold"):
        x, y = (21, 17) if p.arms == "eat_bite" else (27, 22)
        _onigiri(g, x, y + top, p.prop)
    elif p.arms == "book":
        _book(g, top, p.prop)
    elif p.arms == "pan":
        _pan(g, top, p.prop)


def _onigiri(g, x, y, stage):
    """Рисовый треугольник с нори. stage: 0 — целый, 1 — надкушен, 2 — последний кусочек."""
    rows = [(3, 3), (2, 4), (1, 5), (0, 6), (0, 6), (0, 6)]
    for dy, (a, b) in enumerate(rows):
        for dx in range(a, b + 1):
            if stage >= 2 and dy < 3:
                continue
            if stage == 1 and dx >= 4 and dy <= 2:
                continue  # откушенный уголок
            nori = dy >= 4 and 2 <= dx <= 4
            g.set(x + dx, y + dy, "nori" if nori else "rice_shade" if dy == 5 else "rice")


def _book(g, top, flipping):
    y0 = 27 + top
    g.rect(17, y0, 30, y0 + 7, "book")
    g.rect(18, y0, 23, y0 + 6, "page")
    g.rect(24, y0, 29, y0 + 6, "page")
    g.rect(23, y0, 24, y0 + 6, "page_line")
    for ly in (y0 + 2, y0 + 4):
        g.rect(19, ly, 22, ly, "page_line")
        g.rect(25, ly, 28, ly, "page_line")
    if flipping:  # переворачиваемая страница выгибается вверх
        for dx, dy in ((24, -1), (25, -2), (26, -2), (27, -2), (28, -1)):
            g.set(dx, y0 + dy, "page")
    # пальцы держат книгу по краям
    g.rect(17, y0 + 3, 18, y0 + 4, "skin")
    g.rect(29, y0 + 3, 30, y0 + 4, "skin")


def _pan(g, top, flipping):
    y = 29 + top
    g.rect(37, y, 39, y + 1, "pan_dark")
    g.ellipse(42.5, y + 0.5, 3.5, 1.6, "pan")
    g.rect(39, y + 1, 46, y + 1, "pan_dark")
    ey = y - 4 if flipping else y - 0.5
    g.ellipse(42.5, ey, 2.4, 1, "egg")
    g.rect(42, round(ey), 43, round(ey), "yolk")


def _sleeping(g, p):
    """Спит на подушке под одеялом. Кепка и очки сняты — кепка лежит на одеяле."""
    g.ellipse(13.5, 42.5, 11, 4, "pillow")
    g.rect(4, 45, 23, 45, "pillow_shade")
    g.ellipse(14, 37, 12, 9, "hair_back")  # волосы рассыпались по подушке
    _head(g, -9, 21, Pose(eyes="closed", mouth="flat", headphones=p.headphones), cap=False, glasses=False)
    breathe = p.dy
    g.ellipse(33.5, 37 + breathe, 12.5, 4.5, "blanket")
    g.rect(21, 37 + breathe, 46, 46, "blanket")
    for y in range(37 + breathe, 46):
        for x in range(22, 46):
            if (x + 2 * y) % 7 == 0 and x % 2 == 0:
                g.set(x, y, "blanket_dot")
    g.rect(21, 46, 46, 46, "blanket_shade")
    g.line(22, 38 + breathe, 23, 45, "blanket_shade")
    # кепка на одеяле
    g.ellipse(39.5, 33 + breathe, 4.5, 2, "cap")
    g.rect(35, 35 + breathe, 44, 35 + breathe, "cap_dark")
    g.set(38, 32 + breathe, "pin")


# --- Значки и пар (поверх контура) --------------------------------------------

def _glyph(text, x, y, color):
    """Рисует пиксельные значки на отдельном холсте с собственным контуром."""
    layer = Grid()
    for ch in text:
        rows = GLYPHS.get(ch)
        if not rows:
            continue
        for ry, row in enumerate(rows):
            for rx, bit in enumerate(row):
                if bit == "1":
                    layer.set(x + rx, y + ry, color)
        x += len(rows[0]) + 1
    layer.outline("outline")
    return layer


def _effects(g, p, top):
    if p.steam >= 0:
        side = -1 if p.flip else 1
        base_x = 42.5 if not p.flip else SIZE - 43.5
        layer = Grid()
        for i in range(4):
            y = 25 + top - i
            wiggle = (0, 1, 0, -1)[(i + p.steam) % 4]
            layer.set(base_x - 1 * side + wiggle, y, "steam")
            layer.set(base_x + 2 * side + wiggle, y - 2, "steam")
        g.merge(layer)
    if p.effect:
        color = GLYPH_COLORS.get(p.effect[0], "glyph")
        if p.body == "lie":
            x, y = 27, 20 + p.effect_dy
        else:
            x, y = 38, 1 + top + p.effect_dy
        g.merge(_glyph(p.effect, x, y, color))
