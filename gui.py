"""Окно с пиксельной героиней Люсей.

Она живёт внизу экрана поверх всех окон и сама чем-то занимается:
гуляет, ест онигири, читает, готовит, спит, танцует под музыку.
Если позвать её по имени («Люся», «Люська»), она услышит, звякнет и выполнит команду.

Мышь:
  клик              — поле для текстовой команды (запасной способ);
  перетаскивание    — взять на руки и переставить (отпустишь — упадёт вниз);
  правая кнопка     — меню.
"""

import ctypes
import queue
import random
import time
import tkinter as tk

from dialogue import IGNORED, DialogueManager
from events import HEARD, LISTENING, NOTICE, THINKING, TIMEOUT, TYPED, Reply, Utterance
from listener import VoiceListener
from sprites import SIZE, Pose, render

TRANSPARENT = "#ff00fe"  # этот цвет Windows делает прозрачным
FRAME_MS = 100           # длительность одного кадра анимации
FONT = ("Segoe UI", 10)
NAME_FONT = ("Segoe UI Semibold", 9)
BUBBLE = {"bg": "#1d1220", "shade": "#2c1a2e", "border": "#b81f30", "text": "#f7e9ee",
          "name": "#ffffff", "star": "#ffd34d"}
TYPE_SPEED = 2  # сколько букв появляется за кадр

# Чем она занимается сама: (вес при случайном выборе, длительность в секундах).
# Это только анимации: сама по себе она ничего не запускает и не закрывает —
# команды выполняются лишь после обращения по имени.
# Сон и чтение долгие, поэтому занимают больше половины всего времени.
ACTIVITIES = {
    "sleep": (2, (40, 90)),
    "read": (2, (30, 60)),
    "walk": (3, None),       # гуляет, пока не дойдёт до выбранной точки
    "idle": (2, (4, 8)),
    "sit": (1, (8, 14)),
    "eat": (1, (10, 14)),
    "cook": (1, (10, 16)),
}
MUSIC_ACTIVITIES = {"dance": (5, (8, 14)), "idle": (2, (4, 8)), "read": (1, (20, 40))}

# Значок над головой после успешной команды
EFFECT_GLYPHS = {"vol_up": "+", "vol_down": "-", "mute": "x", "music_on": "♪", "music_launch": "♪"}


def enable_dpi_awareness():
    """Чтобы на экранах с масштабом 125–150% пиксели были чёткими, а не размытыми."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass


def work_area() -> tuple[int, int, int, int]:
    """Область экрана без панели задач: (left, top, right, bottom)."""
    rect = (ctypes.c_long * 4)()
    ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(rect), 0)  # SPI_GETWORKAREA
    return tuple(rect)


class PetApp:
    def __init__(self, config: dict, dialogue: DialogueManager | None = None):
        enable_dpi_awareness()
        self.config = config
        self.name = config.get("assistant_name", "Люся")
        # Вся логика команд и диалога — в ядре; окно только показывает его ответы
        self.dialogue = dialogue or DialogueManager(config)

        self.root = tk.Tk()
        self.root.title(self.name)
        self.root.overrideredirect(True)          # без рамки и заголовка
        self.root.attributes("-topmost", True)    # поверх всех окон
        self.root.attributes("-transparentcolor", TRANSPARENT)
        self.root.config(bg=TRANSPARENT)

        # Размер «большого пикселя»: sprite_scale из конфига × масштаб экрана
        self.u = self.root.winfo_fpixels("1i") / 96
        s = self.s = max(1, round(config.get("sprite_scale", 2.4) * self.u))
        self.top = int(135 * self.u)         # место над головой под облачко
        self.w = max(SIZE * s, int(260 * self.u))
        self.h = self.top + SIZE * s
        self.left, _, self.right, bottom = work_area()
        self.ground = bottom - self.h        # y окна, когда она стоит на панели задач
        self.x, self.y = self.right - self.w - 20 * s, self.ground
        self.vy = 0.0
        self._place()

        self.canvas = tk.Canvas(self.root, width=self.w, height=self.h, bg=TRANSPARENT, highlightthickness=0)
        self.canvas.pack()
        self.sprite = self.canvas.create_image((self.w - SIZE * s) // 2, self.top, anchor="nw")
        self.images: dict[Pose, tk.PhotoImage] = {}

        self.entry = tk.Entry(
            self.root, font=FONT, relief="flat", justify="center",
            bg="#2b1d3a", fg="#f3edff", insertbackground="#72e8f4",
            highlightthickness=2, highlightbackground="#2b1d3a", highlightcolor="#72e8f4",
        )
        self.entry_visible = False

        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="Помощь", command=lambda: self.run_text("помощь"))
        self.menu.add_command(label="Выключить", command=lambda: self.run_text("выключи ассистента"))

        # Состояние героини
        self.tick = 0
        self.state = "idle"
        self.state_tick = 0
        self.state_start = time.monotonic()
        self.state_until = float("inf")
        self.facing_left = False
        self.walk_target = self.x
        self.effect_glyph = ""
        self.music_on = False
        self.listener: VoiceListener | None = None
        self.bubble_text = ""
        self.bubble_chars = 0     # сколько букв уже «напечатано»
        self.bubble_until = 0.0
        self._press = None
        self._dragged = False

        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Button-3>", self._on_menu)
        self.entry.bind("<Return>", lambda e: self.run_text(self.entry.get()))
        self.entry.bind("<Escape>", lambda e: self._hide_entry())

    def run(self):
        self.listener = VoiceListener(self.config, self.dialogue.voice_sink)
        self.dialogue.on_followup = self.listener.listen_again
        self.listener.start()
        self.root.protocol("WM_DELETE_WINDOW", self.shutdown)
        self.set_state("wave", 3)
        self.say(f"Привет! Я {self.name}. Позови меня по имени и скажи, что сделать.")
        self._animate()
        try:
            self.root.mainloop()
        finally:
            self._stop_background()

    def shutdown(self):
        """Штатное выключение: останавливаем фоновые потоки и закрываем окно."""
        self._stop_background()
        self.root.destroy()

    def _stop_background(self):
        if self.listener is not None:
            self.listener.stop()  # закрывает аудиопоток и освобождает микрофон
            self.listener = None
        if self.dialogue is not None:
            self.dialogue.shutdown()
            self.dialogue = None

    # --- Состояние и реплики ------------------------------------------------

    def set_state(self, state: str, duration: float | None = None):
        self.state = state
        self.state_tick = self.tick
        self.state_start = time.monotonic()
        self.state_until = self.state_start + duration if duration else float("inf")

    def say(self, text: str, instant: bool = False):
        """Показывает реплику. instant — сразу целиком (для живого текста речи).
        На этапе 3 здесь же будет озвучка."""
        self.bubble_text = text
        self.bubble_chars = len(text) if instant else 0
        self.bubble_until = time.monotonic() + 3.5 + len(text) / 12

    def _pick_activity(self):
        """Выбирает, чем заняться дальше, когда никто не зовёт."""
        options = MUSIC_ACTIVITIES if self.music_on else ACTIVITIES
        if self.state != "idle":  # между занятиями немного постоять
            options = {"idle": (1, (2, 5))}
        name = random.choices(list(options), weights=[w for w, _ in options.values()])[0]
        duration = options[name][1]
        if name == "walk":
            # Недалеко, чтобы не бегать по всему экрану и не мешать
            lo, hi = self.left - 10 * self.s, self.right - self.w + 10 * self.s
            distance = random.uniform(80, 300) * self.u * random.choice((-1, 1))
            self.walk_target = min(hi, max(lo, self.x + distance))
            self.facing_left = self.walk_target < self.x
            self.set_state("walk", 30)
        else:
            self.set_state(name, random.uniform(*duration))

    # --- Связь с ядром --------------------------------------------------------

    def run_text(self, text: str):
        """Напечатанная команда (из поля ввода или меню)."""
        self.entry.delete(0, "end")
        self.dialogue.submit(Utterance(text, source=TYPED))

    def _handle_core(self):
        """Забирает из ядра ответы и состояния и показывает их."""
        while True:
            try:
                item = self.dialogue.outbox.get_nowait()
            except queue.Empty:
                return
            if isinstance(item, Reply):
                self._show_reply(item)
            elif item.state == LISTENING:
                self.set_state("listen", 12)
                if not item.text:  # при ответе на вопрос сам вопрос остаётся на экране
                    self.say("Да?")
            elif item.state == HEARD and self.state == "listen":
                self.say(item.text + "…", instant=True)
            elif item.state == THINKING:
                self.set_state("think")
            elif item.state == TIMEOUT and self.state == "listen":
                self.set_state("idle", 3)
                self.say("Не расслышала…")
            elif item.state == NOTICE:
                self.say(item.text)

    def _show_reply(self, reply: Reply):
        if reply.effect == IGNORED:  # фраза пропущена — просто возвращаемся к своим делам
            self.set_state("idle", 2)
            return
        self.say(reply.text)
        if reply.effect in ("music_on", "music_launch"):
            self.music_on = True
        elif reply.effect in ("music_off", "music_close"):
            self.music_on = False

        if not reply.keep_running:
            self._hide_entry()
            self.set_state("wave")
            self.root.after(2000, self.shutdown)
        elif reply.ok:
            self.effect_glyph = EFFECT_GLYPHS.get(reply.effect, "♥")
            self.set_state("happy", 1.8)
        else:
            self.set_state("confused", 2.5)

    # --- Мышь и поле ввода --------------------------------------------------

    def _on_press(self, e):
        self._press = (e.x_root, e.y_root, self.x, self.y)
        self._dragged = False

    def _on_drag(self, e):
        x0, y0, wx, wy = self._press
        dx, dy = e.x_root - x0, e.y_root - y0
        if not self._dragged and abs(dx) + abs(dy) > 4:
            self._dragged = True
            self.set_state("drag")
        if self._dragged:
            self.x, self.y = wx + dx, wy + dy
            self._place()

    def _on_release(self, e):
        if self._dragged:
            self.vy = 0.0
            self.set_state("fall")
        elif self.entry_visible:
            self._hide_entry()
        else:
            self._show_entry()

    def _on_menu(self, e):
        self.menu.tk_popup(e.x_root, e.y_root)

    def _show_entry(self):
        s = self.s
        self.entry.place(x=6 * s, y=self.top - 9 * s, width=self.w - 12 * s, height=8 * s)
        self.entry_visible = True
        self.root.focus_force()
        self.entry.focus_set()

    def _hide_entry(self):
        self.entry.place_forget()
        self.entry_visible = False

    # --- Движение и анимация ------------------------------------------------

    def _place(self):
        self.root.geometry(f"{self.w}x{self.h}+{int(self.x)}+{int(self.y)}")

    def _move(self):
        """Ходьба по экрану и падение после перетаскивания."""
        if self.state == "walk":
            step = 1.2 * self.s
            if abs(self.walk_target - self.x) <= step:
                self.set_state("idle", random.uniform(2, 5))
            else:
                self.x += -step if self.facing_left else step
                self._place()
        elif self.state == "fall":
            self.vy += 0.9 * self.s
            self.y = min(self.ground, self.y + self.vy)
            self._place()
            if self.y >= self.ground:
                self.set_state("confused", 1.2)  # приземлилась, немного ошарашена

    def _animate(self):
        self.tick += 1
        self.bubble_chars = min(len(self.bubble_text), self.bubble_chars + TYPE_SPEED)
        if self.dialogue is not None:
            self._handle_core()
        if time.monotonic() >= self.state_until:
            self._pick_activity()
        self._move()

        self.canvas.itemconfig(self.sprite, image=self._image(self._pose()))
        self._draw_bubble()
        self.root.after(FRAME_MS, self._animate)

    def _image(self, pose: Pose) -> tk.PhotoImage:
        """Превращает позу в картинку (с кэшем, чтобы не рисовать одно и то же дважды)."""
        img = self.images.get(pose)
        if img is None:
            grid = render(pose)
            base = tk.PhotoImage(width=SIZE, height=SIZE)
            base.put(" ".join("{" + " ".join(c or TRANSPARENT for c in row) + "}" for row in grid.p))
            img = self.images[pose] = base.zoom(self.s)
        return img

    def _pose(self) -> Pose:
        """Собирает позу для текущего кадра. k — сколько кадров длится текущее состояние."""
        t, k, state = self.tick, self.tick - self.state_tick, self.state
        base = {"headphones": self.music_on, "flip": self.facing_left}
        eyes = "blink" if t % 43 in (0, 1) else "open"
        bob = -((k // 4) % 3)  # значок над головой плавно всплывает

        if state == "walk":
            body = ("walk1", "stand", "walk2", "stand")[(k // 3) % 4]
            return Pose(body=body, dy=(k // 3) % 2, eyes=eyes, look=1, **base)
        if state == "sit":
            return Pose(body="sit", arms="lap", eyes=eyes, dy=(t // 10) % 2, **base)
        if state == "eat":
            progress = (time.monotonic() - self.state_start) / max(self.state_until - self.state_start, 1)
            if progress > 0.85:  # доела — довольна
                return Pose(body="sit", arms="lap", eyes="happy", effect="♥", effect_dy=bob, **base)
            biting = k % 24 < 6
            return Pose(
                body="sit", arms="eat_bite" if biting else "eat_hold",
                eyes="happy" if biting else eyes,
                mouth="o" if biting else ("flat" if (k // 3) % 2 else "smile"),
                prop=min(2, int(progress * 3)), **base,
            )
        if state == "read":
            return Pose(body="sit", arms="book", eyes="blink" if t % 43 == 0 else "down",
                        mouth="flat", prop=1 if k % 50 >= 45 else 0, **base)
        if state == "cook":
            flipping = k % 30 >= 24
            return Pose(arms="pan", prop=1 if flipping else 0, steam=(k // 2) % 4,
                        eyes="happy" if flipping else eyes, mouth="open" if flipping else "smile",
                        effect="♪" if (k // 40) % 3 == 1 else "", effect_dy=bob, **base)
        if state == "sleep":
            return Pose(body="lie", dy=(t // 12) % 2, effect="Z", effect_dy=-((t // 5) % 4), **base)
        if state == "dance":
            return Pose(arms="dance1" if (k // 4) % 2 else "dance2", eyes="happy", mouth="open",
                        dx=(-1, 0, 1, 0)[(k // 2) % 4], dy=(k // 2) % 2, effect="♪", effect_dy=bob, **base)
        if state == "listen":
            return Pose(arms="ear", eyes="big", mouth="o", effect="!", headphones=self.music_on)
        if state == "think":
            return Pose(arms="chin", eyes="up", look=1, mouth="flat",
                        effect="." * ((k // 3) % 3 + 1), headphones=self.music_on)
        if state == "happy":
            return Pose(arms="up", eyes="happy", mouth="open", dy=-2 if k < 12 and (k // 3) % 2 == 0 else 0,
                        effect=self.effect_glyph, effect_dy=bob, headphones=self.music_on)
        if state == "confused":
            return Pose(eyes="sad", mouth="flat", effect="?", **base)
        if state == "wave":
            return Pose(arms="wave1" if (k // 3) % 2 else "wave2", eyes="happy", mouth="open", **base)
        if state in ("drag", "fall"):
            return Pose(arms="up", eyes="big", mouth="o", **base)
        # idle: дышит, моргает, оглядывается
        return Pose(eyes=eyes, dy=(t // 8) % 2, look={1: 1, 3: -1}.get((t // 40) % 4, 0), **base)

    def _pixel_box(self, x1, y1, x2, y2, color):
        """Прямоугольник со «срезанными» пиксельными углами."""
        p = self.s
        self.canvas.create_rectangle(x1 + p, y1, x2 - p, y2, fill=color, outline="", tags="bubble")
        self.canvas.create_rectangle(x1, y1 + p, x2, y2 - p, fill=color, outline="", tags="bubble")

    def _draw_bubble(self):
        """Реплика в стиле диалогового окна из визуальной новеллы, но пиксельная:
        тёмная плашка с красной рамкой, табличка с именем, текст печатается по буквам,
        а когда фраза договорена — в углу мерцает звёздочка, как значки на её кепке."""
        c, p = self.canvas, self.s
        c.delete("bubble")
        if not self.bubble_text or time.monotonic() > self.bubble_until:
            return
        pad = 4 * p
        wrap = self.w - 14 * p
        # Размер плашки считаем по полному тексту, чтобы она не прыгала, пока текст печатается
        probe = c.create_text(0, 0, text=self.bubble_text, anchor="nw", width=wrap, font=FONT)
        _, _, text_w, text_h = c.bbox(probe)
        c.delete(probe)
        name_w = len(self.name) * 8 * self.u + 6 * p
        box_w = max(text_w, name_w) + 2 * pad
        bottom = self.top - 4 * p - (10 * p if self.entry_visible else 0)
        x1 = (self.w - box_w) // 2
        x2, y2 = x1 + box_w, bottom
        y1 = y2 - text_h - 2 * pad

        self._pixel_box(x1 - p, y1 - p, x2 + p, y2 + p, BUBBLE["border"])
        self._pixel_box(x1, y1, x2, y2, BUBBLE["bg"])
        c.create_rectangle(x1 + 2 * p, y2 - p, x2 - 2 * p, y2, fill=BUBBLE["shade"], outline="", tags="bubble")

        # хвостик-лесенка, указывающий на героиню
        tx = self.w // 2 + 2 * p
        for i in range(3):
            c.create_rectangle(tx + i * p, y2 + p + i * p, tx + 3 * p, y2 + 2 * p + i * p,
                               fill=BUBBLE["border"], outline="", tags="bubble")

        # табличка с именем
        name_id = c.create_text(x1 + 4 * p, y1 - p, text=self.name, anchor="w", font=NAME_FONT,
                                fill=BUBBLE["name"], tags="bubble")
        nx1, ny1, nx2, ny2 = c.bbox(name_id)
        self._pixel_box(nx1 - 2 * p, ny1 - p // 2, nx2 + 2 * p, ny2 + p // 2, BUBBLE["border"])
        c.tag_raise(name_id)

        shown = self.bubble_text[:self.bubble_chars]
        c.create_text(x1 + pad, y1 + pad, text=shown, anchor="nw", width=wrap, font=FONT,
                      fill=BUBBLE["text"], tags="bubble")

        if len(shown) == len(self.bubble_text) and self.tick % 10 < 6:
            sx, sy = x2 - 3 * p, y2 - 3 * p  # мерцающая звёздочка
            for dx, dy in ((0, 0), (-1, 0), (1, 0), (0, -1), (0, 1)):
                c.create_rectangle(sx + dx * p, sy + dy * p, sx + (dx + 1) * p, sy + (dy + 1) * p,
                                   fill=BUBBLE["star"], outline="", tags="bubble")
