#!/usr/bin/env python3
"""Apple TV Remote для macOS — стриманий темний інтерфейс (pyatv + tkinter + Pillow)."""
import asyncio
import io
import json
import math
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import simpledialog, messagebox

import pyatv
from pyatv.const import Protocol

try:
    from PIL import Image, ImageChops, ImageColor, ImageDraw, ImageTk
except ImportError:
    Image = None

W, H = 320, 680
HAND = "pointinghand" if sys.platform == "darwin" else "hand2"
STORE = Path.home() / ".appletv_remote.json"

# ---- палітра: майже монохромна, один світлий акцент ----
BG = "#0d0d0f"
SURFACE = "#151518"
BORDER = "#2a2a30"
TEXT = "#ededf0"
SUB = "#85858e"
FAINT = "#4c4c54"
OK_DOT = "#5cb87a"

ACTIONS = {
    "up": lambda a: a.remote_control.up(),
    "down": lambda a: a.remote_control.down(),
    "left": lambda a: a.remote_control.left(),
    "right": lambda a: a.remote_control.right(),
    "select": lambda a: a.remote_control.select(),
    "menu": lambda a: a.remote_control.menu(),
    "home": lambda a: a.remote_control.home(),
    "play_pause": lambda a: a.remote_control.play_pause(),
    "play": lambda a: a.remote_control.play(),
    "pause": lambda a: a.remote_control.pause(),
    "prev": lambda a: a.remote_control.previous(),
    "next": lambda a: a.remote_control.next(),
    "vol_up": lambda a: a.audio.volume_up(),
    "vol_down": lambda a: a.audio.volume_down(),
    "power_on": lambda a: a.power.turn_on(),
    "power_off": lambda a: a.power.turn_off(),
}

_fonts = {}


def F(size, bold=False):
    key = (size, bold)
    if key not in _fonts:
        f = tkfont.nametofont("TkDefaultFont").copy()
        f.configure(size=size, weight="bold" if bold else "normal")
        _fonts[key] = f
    return _fonts[key]


def fit(text, font, maxw):
    if font.measure(text) <= maxw:
        return text
    while text and font.measure(text + "…") > maxw:
        text = text[:-1]
    return text + "…"


def fmt_time(sec):
    sec = max(0, int(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


# =====================================================================
#   Спрайти: плоскі форми з тонкою (1 px) рамкою, згладжені суперсемплінгом
# =====================================================================
SS = 4
COVER = 64
_cache = {}


def _rgb(c):
    return ImageColor.getrgb(c)


def shape_img(w, h, r, fill, border):
    key = ("shape", w, h, r, fill, border)
    if key not in _cache:
        k = SS
        im = Image.new("RGBA", (w * k, h * k), _rgb(border) + (0,))
        d = ImageDraw.Draw(im)
        d.rounded_rectangle((0, 0, w * k - 1, h * k - 1), radius=int(r * k), fill=border)
        d.rounded_rectangle((k, k, w * k - 1 - k, h * k - 1 - k), radius=int(max(0, r - 1) * k), fill=fill)
        _cache[key] = ImageTk.PhotoImage(im.resize((w, h), Image.LANCZOS))
    return _cache[key]


# стани кнопки: (заливка, рамка) — звичайний, наведення, натиснуто
VARIANTS = {
    "flat": [(SURFACE, BORDER), ("#1c1c20", "#3a3a41"), ("#26262b", "#46464e")],
    "inset": [("#0f0f12", BORDER), ("#1c1c20", "#3a3a41"), ("#26262b", "#46464e")],
    "primary": [(TEXT, TEXT), ("#ffffff", "#ffffff"), ("#c6c6cc", "#c6c6cc")],
}


def btn_img(w, h, r, variant, state):
    fill, border = VARIANTS[variant][state]
    return shape_img(w, h, r, fill, border)


def sector_img(R, r_in, name, state):
    key = ("sec", R, r_in, name, state)
    if key not in _cache:
        k = SS
        S = 2 * R
        c = S * k / 2
        wedge = Image.new("L", (S * k, S * k), 0)
        d = ImageDraw.Draw(wedge)
        for a0, a1 in WEDGES[name]:
            d.pieslice((0, 0, S * k - 1, S * k - 1), a0, a1, fill=255)
        hole = Image.new("L", (S * k, S * k), 0)
        ImageDraw.Draw(hole).ellipse((c - r_in * k, c - r_in * k, c + r_in * k, c + r_in * k), fill=255)
        outer = Image.new("L", (S * k, S * k), 0)
        ImageDraw.Draw(outer).ellipse((k * 1.5, k * 1.5, S * k - k * 1.5, S * k - k * 1.5), fill=255)
        mask = ImageChops.multiply(ImageChops.multiply(wedge, outer), ImageChops.invert(hole))
        mask = mask.resize((S, S), Image.LANCZOS)
        alpha = 15 if state == 1 else 30
        im = Image.new("RGBA", (S, S), (255, 255, 255, 0))
        im.putalpha(mask.point(lambda v: v * alpha // 255))
        _cache[key] = ImageTk.PhotoImage(im)
    return _cache[key]


WEDGES = {"up": [(225, 315)], "left": [(135, 225)], "down": [(45, 135)], "right": [(315, 360), (0, 45)]}


def icon_img(name, color, size=28):
    """Тонкі лінійні іконки, намальовані з суперсемплінгом."""
    key = ("icon", name, color, size)
    if key in _cache:
        return _cache[key]
    k = SS
    S = 28 * k
    im = Image.new("RGBA", (S, S), _rgb(color) + (0,))
    d = ImageDraw.Draw(im)

    def P(pts):
        return [(x * k, y * k) for x, y in pts]

    def line(pts, w=2.0):
        d.line(P(pts), fill=color, width=int(w * k), joint="curve")
        for x, y in (pts[0], pts[-1]):
            rr = w * k / 2
            d.ellipse((x * k - rr, y * k - rr, x * k + rr, y * k + rr), fill=color)

    def poly(pts):
        d.polygon(P(pts), fill=color)

    def rect(x0, y0, x1, y1):
        d.rectangle((x0 * k, y0 * k, x1 * k, y1 * k), fill=color)

    def speaker(dx=0):
        poly([(4 + dx, 11), (8.5 + dx, 11), (14 + dx, 6.5), (14 + dx, 21.5), (8.5 + dx, 17), (4 + dx, 17)])

    if name == "back":
        line([(17, 6), (9, 14), (17, 22)])
    elif name == "tv":
        d.rounded_rectangle((5 * k, 7 * k, 23 * k, 19 * k), radius=3 * k, outline=color, width=int(2 * k))
        line([(10, 23), (18, 23)])
    elif name == "play_pause":
        poly([(4, 6), (4, 22), (13, 14)])
        rect(16, 7, 18.6, 21)
        rect(21.4, 7, 24, 21)
    elif name == "prev":
        rect(6, 7, 8.6, 21)
        poly([(22, 6), (22, 22), (10.5, 14)])
    elif name == "next":
        rect(19.4, 7, 22, 21)
        poly([(6, 6), (6, 22), (17.5, 14)])
    elif name == "vol_down":
        speaker(-1)
        line([(17.5, 14), (23.5, 14)])
    elif name == "vol_up":
        speaker(-2)
        line([(16.5, 14), (22.5, 14)])
        line([(19.5, 11), (19.5, 17)])
    elif name == "power":
        d.arc((7 * k, 7 * k, 21 * k, 21 * k), start=300, end=240, fill=color, width=int(2 * k))
        line([(14, 5.5), (14, 13)])
    elif name == "send":
        line([(14, 22), (14, 7)])
        line([(8, 13), (14, 7), (20, 13)])
    elif name == "chev_down":
        line([(9, 11), (14, 16), (19, 11)], 1.8)
    elif name == "up":
        line([(8, 17), (14, 11), (20, 17)], 2.2)
    elif name == "down":
        line([(8, 11), (14, 17), (20, 11)], 2.2)
    elif name == "left":
        line([(17, 8), (11, 14), (17, 20)], 2.2)
    elif name == "right":
        line([(11, 8), (17, 14), (11, 20)], 2.2)
    _cache[key] = ImageTk.PhotoImage(im.resize((size, size), Image.LANCZOS))
    return _cache[key]


def make_cover(data):
    im = Image.open(io.BytesIO(data)).convert("RGB")
    side = min(im.size)
    left, top = (im.width - side) // 2, (im.height - side) // 2
    im = im.crop((left, top, left + side, top + side)).resize((COVER, COVER), Image.LANCZOS)
    k = 4
    mask = Image.new("L", (COVER * k, COVER * k), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, COVER * k - 1, COVER * k - 1), radius=8 * k, fill=255)
    out = im.convert("RGBA")
    out.putalpha(mask.resize((COVER, COVER), Image.LANCZOS))
    return out


# =====================================================================
#   Віджети на одному полотні
# =====================================================================
class Button:
    def __init__(self, cv, x, y, w, h, command, icon=None, text=None, variant="flat", r=12,
                 font=None, shape="rect", label_anchor="center", label_dx=0):
        self.cv, self.x, self.y, self.w, self.h = cv, x, y, w, h
        self.command, self.variant, self.shape = command, variant, shape
        self.r = w / 2 if shape == "circle" else r
        for s in range(3):  # прогріваємо спрайти, щоб наведення не гальмувало
            btn_img(w, h, self.r, variant, s)
        self.img = cv.create_image(x, y, anchor="nw", image=btn_img(w, h, self.r, variant, 0))
        cx, cy = x + w / 2, y + h / 2
        if icon:
            col = BG if variant == "primary" else TEXT
            cv.create_image(cx, cy, image=icon_img(icon, col))
        self.txt = None
        if text:
            anchor_x = x + label_dx if label_anchor == "w" else cx + label_dx
            self.txt = cv.create_text(anchor_x, cy, text=text, fill=TEXT, anchor=label_anchor,
                                      font=font or F(13, True))

    def set_text(self, text):
        self.cv.itemconfigure(self.txt, text=text)

    def hit(self, px, py):
        if self.shape == "circle":
            return math.hypot(px - (self.x + self.w / 2), py - (self.y + self.h / 2)) <= self.w / 2
        return self.x <= px <= self.x + self.w and self.y <= py <= self.y + self.h

    def _st(self, s):
        self.cv.itemconfigure(self.img, image=btn_img(self.w, self.h, self.r, self.variant, s))

    def move(self, px, py):
        self._st(1)

    def leave(self):
        self._st(0)

    def press(self, px, py):
        self._st(2)

    def release(self, px, py, inside):
        self._st(1 if inside else 0)
        if inside:
            self.command()


class DeviceButton(Button):
    """Рядок вибору пристрою: індикатор, назва зліва і стрілка справа."""

    def __init__(self, cv, x, y, w, h, command):
        super().__init__(cv, x, y, w, h, command, text="Пошук…", label_anchor="w", label_dx=38,
                         font=F(13, True))
        cy = y + h / 2
        self.dot = cv.create_oval(x + 17, cy - 3, x + 23, cy + 3, fill=FAINT, outline="")
        cv.create_image(x + w - 22, cy, image=icon_img("chev_down", SUB, 20))

    def set_dot(self, on):
        self.cv.itemconfigure(self.dot, fill=OK_DOT if on else FAINT)


class Ring:
    """Кругле поле зі стрілками (як на Siri Remote), без зайвих прикрас."""

    def __init__(self, cv, cx, cy, R, r_in, command):
        self.cv, self.cx, self.cy, self.R, self.r_in, self.command = cv, cx, cy, R, r_in, command
        cv.create_image(cx - R, cy - R, anchor="nw", image=shape_img(2 * R, 2 * R, R, SURFACE, BORDER))
        self.sec = {n: cv.create_image(cx - R, cy - R, anchor="nw", state="hidden",
                                       image=sector_img(R, r_in, n, 1)) for n in WEDGES}
        for n in WEDGES:
            sector_img(R, r_in, n, 2)
        d = 77
        pos = {"up": (cx, cy - d), "down": (cx, cy + d), "left": (cx - d, cy), "right": (cx + d, cy)}
        self.arrows = {n: cv.create_image(x, y, image=icon_img(n, SUB)) for n, (x, y) in pos.items()}
        self.cur = None

    def hit(self, px, py):
        return self.r_in - 4 <= math.hypot(px - self.cx, py - self.cy) <= self.R

    def sector(self, px, py):
        a = math.degrees(math.atan2(self.cy - py, px - self.cx)) % 360
        if 45 <= a < 135:
            return "up"
        if 135 <= a < 225:
            return "left"
        if 225 <= a < 315:
            return "down"
        return "right"

    def _show(self, name, state):
        if name:
            self.cv.itemconfigure(self.sec[name], state="normal",
                                  image=sector_img(self.R, self.r_in, name, state))
            self.cv.itemconfigure(self.arrows[name], image=icon_img(name, TEXT))

    def _hide(self, name):
        if name:
            self.cv.itemconfigure(self.sec[name], state="hidden")
            self.cv.itemconfigure(self.arrows[name], image=icon_img(name, SUB))

    def move(self, px, py):
        n = self.sector(px, py)
        if n != self.cur:
            self._hide(self.cur)
            self.cur = n
            self._show(n, 1)

    def leave(self):
        self._hide(self.cur)
        self.cur = None

    def press(self, px, py):
        self.cur = self.sector(px, py)
        self._show(self.cur, 2)

    def release(self, px, py, inside):
        if inside:
            self._show(self.cur, 1)
            self.command(self.cur)
        else:
            self._hide(self.cur)

    def flash(self, name):
        self._show(name, 2)
        self.cv.after(140, lambda: self._hide(name) if name != self.cur else self._show(name, 1))


class Card:
    """Картка «Зараз грає»: обкладинка, назва, стан і тонка шкала часу."""
    CW, CH = 272, 96

    def __init__(self, cv, x, y):
        self.cv = cv
        cv.create_image(x, y, anchor="nw", image=shape_img(self.CW, self.CH, 16, SURFACE, BORDER))
        cx0, cy0 = x + 16, y + 16
        self.ph = [
            cv.create_image(cx0, cy0, anchor="nw", image=shape_img(COVER, COVER, 8, "#1c1c20", BORDER)),
            cv.create_text(cx0 + COVER / 2, cy0 + COVER / 2, text="♪", fill=FAINT, font=F(24, True)),
        ]
        self.img = cv.create_image(cx0, cy0, anchor="nw", state="hidden")
        self._photo = None
        tx = cx0 + COVER + 14
        self.tx = tx
        self.maxw = x + self.CW - 16 - tx
        self.t1 = cv.create_text(tx, y + 28, anchor="w", text="Не підключено", fill=TEXT, font=F(13, True))
        self.t2 = cv.create_text(tx, y + 47, anchor="w", text="Виберіть Apple TV", fill=SUB, font=F(11))
        ty = y + 64
        self.track = cv.create_rectangle(tx, ty, tx + self.maxw, ty + 2, fill=BORDER, outline="", state="hidden")
        self.fill = cv.create_rectangle(tx, ty, tx, ty + 2, fill=TEXT, outline="", state="hidden")
        self.ty = ty
        self.tl = cv.create_text(tx, y + 80, anchor="w", text="", fill=SUB, font=F(10))
        self.tr = cv.create_text(tx + self.maxw, y + 80, anchor="e", text="", fill=SUB, font=F(10))

    def set(self, title, sub):
        self.cv.itemconfigure(self.t1, text=fit(title, F(13, True), self.maxw))
        self.cv.itemconfigure(self.t2, text=fit(sub, F(11), self.maxw))

    def set_cover(self, pil_img):
        if pil_img is None:
            self._photo = None
            self.cv.itemconfigure(self.img, state="hidden")
            for i in self.ph:
                self.cv.itemconfigure(i, state="normal")
        else:
            self._photo = ImageTk.PhotoImage(pil_img)
            self.cv.itemconfigure(self.img, image=self._photo, state="normal")
            for i in self.ph:
                self.cv.itemconfigure(i, state="hidden")

    def set_progress(self, pos, total):
        c = self.cv
        if not total or total <= 0:
            for i in (self.track, self.fill):
                c.itemconfigure(i, state="hidden")
            c.itemconfigure(self.tl, text="")
            c.itemconfigure(self.tr, text="")
            return
        pos = min(max(pos or 0, 0), total)
        c.coords(self.fill, self.tx, self.ty, self.tx + self.maxw * pos / total, self.ty + 2)
        c.itemconfigure(self.track, state="normal")
        c.itemconfigure(self.fill, state="normal")
        c.itemconfigure(self.tl, text=fmt_time(pos))
        c.itemconfigure(self.tr, text="−" + fmt_time(total - pos))


class MacNowPlaying:
    """Показує Apple TV у «Зараз грає» в Центрі керування macOS і приймає звідти кнопки.
    Потрібен pyobjc-framework-MediaPlayer; без нього просто вимкнено."""

    def __init__(self, send, seek=None):
        self.ok = False
        self.art = None
        self._keep = []
        if sys.platform != "darwin":
            return
        try:
            import MediaPlayer as MP
            import AppKit
            import Foundation
            self.MP, self.AppKit, self.Foundation = MP, AppKit, Foundation
            self.center = MP.MPNowPlayingInfoCenter.defaultCenter()
            cc = MP.MPRemoteCommandCenter.sharedCommandCenter()

            def bind(cmd, action):
                def handler(event):
                    try:
                        send(action)
                    except Exception:  # noqa: BLE001
                        pass
                    return MP.MPRemoteCommandHandlerStatusSuccess
                cmd.setEnabled_(True)
                cmd.addTargetWithHandler_(handler)
                self._keep.append(handler)

            bind(cc.playCommand(), "play")
            bind(cc.pauseCommand(), "pause")
            bind(cc.togglePlayPauseCommand(), "play_pause")
            bind(cc.nextTrackCommand(), "next")
            bind(cc.previousTrackCommand(), "prev")

            if seek is not None:
                def on_seek(event):
                    try:
                        seek(float(event.positionTime()))
                    except Exception:  # noqa: BLE001
                        pass
                    return MP.MPRemoteCommandHandlerStatusSuccess
                scrub = cc.changePlaybackPositionCommand()
                scrub.setEnabled_(True)
                scrub.addTargetWithHandler_(on_seek)
                self._keep.append(on_seek)
            self.ok = True
        except Exception:  # noqa: BLE001
            self.ok = False

    def _make_art(self, data):
        if not data:
            return None
        try:
            nsdata = self.Foundation.NSData.dataWithBytes_length_(data, len(data))
            img = self.AppKit.NSImage.alloc().initWithData_(nsdata)
            if img is None:
                return None
            return self.MP.MPMediaItemArtwork.alloc().initWithBoundsSize_requestHandler_(
                img.size(), lambda size: img)
        except Exception:  # noqa: BLE001
            return None

    def update(self, p, app, art_bytes=None, art_changed=False):
        if not self.ok:
            return
        MP = self.MP
        try:
            state = p.device_state.name if p.device_state else "Idle"
            if art_changed:
                self.art = self._make_art(art_bytes)
            if state in ("Idle", "Stopped") and not p.title:
                self.center.setNowPlayingInfo_(None)
                self.center.setPlaybackState_(MP.MPNowPlayingPlaybackStateStopped)
                return
            playing = state in ("Playing", "Loading", "Seeking")
            info = {
                MP.MPMediaItemPropertyTitle: p.title or app or "Apple TV",
                MP.MPNowPlayingInfoPropertyPlaybackRate: 1.0 if playing else 0.0,
                MP.MPNowPlayingInfoPropertyDefaultPlaybackRate: 1.0,
            }
            if p.artist:
                info[MP.MPMediaItemPropertyArtist] = p.artist
            if app:
                info[MP.MPMediaItemPropertyAlbumTitle] = app
            if p.total_time:
                info[MP.MPMediaItemPropertyPlaybackDuration] = float(p.total_time)
                info[MP.MPNowPlayingInfoPropertyElapsedPlaybackTime] = float(p.position or 0)
            if self.art is not None:
                info[MP.MPMediaItemPropertyArtwork] = self.art
            self.center.setNowPlayingInfo_(info)
            self.center.setPlaybackState_(
                MP.MPNowPlayingPlaybackStatePlaying if playing
                else MP.MPNowPlayingPlaybackStatePaused)
        except Exception:  # noqa: BLE001
            pass

    def clear(self):
        if not self.ok:
            return
        try:
            self.center.setNowPlayingInfo_(None)
            self.center.setPlaybackState_(self.MP.MPNowPlayingPlaybackStateStopped)
        except Exception:  # noqa: BLE001
            pass


class AsyncRunner:
    def __init__(self):
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()

    def submit(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop)


class App:
    def __init__(self, root):
        self.root = root
        root.title("Apple TV")
        root.configure(bg=BG)
        root.resizable(False, False)
        self.runner = AsyncRunner()
        self.store = self.load_store()
        self.configs = []
        self.atv = None
        self.current = None
        self.pairing = None
        self.polling = False
        self.auto_connect = True
        self.cover_key = None
        self.position = 0
        self.prog = None
        self.mac = MacNowPlaying(self.send, self.seek)
        self.build_ui()
        self.scan()
        self.root.after(3000, self.poll)
        self.root.after(500, self.tick)

    # ---------- сховище ----------
    def load_store(self):
        try:
            return json.loads(STORE.read_text())
        except Exception:
            return {"devices": {}, "last": None}

    def save_store(self):
        STORE.write_text(json.dumps(self.store, indent=2))
        try:
            STORE.chmod(0o600)
        except Exception:
            pass

    # ---------- UI ----------
    def build_ui(self):
        cv = self.cv = tk.Canvas(self.root, width=W, height=H, highlightthickness=0, bd=0, bg=BG)
        cv.pack()
        self.objs = []
        add = self.objs.append

        # шапка: вибір пристрою + живлення
        self.dev_btn = DeviceButton(cv, 24, 24, 216, 44, self.show_devices)
        self.power_btn = Button(cv, 252, 24, 44, 44, self.show_power, icon="power")
        # зараз грає
        self.card = Card(cv, 24, 84)
        # кругле поле керування
        cx, cy = W / 2, 312
        self.ring = Ring(cv, cx, cy, 108, 44, self.send)
        center = Button(cv, cx - 38, cy - 38, 76, 76, lambda: self.send("select"), text="OK",
                        variant="inset", shape="circle", font=F(13, True))
        for o in (self.dev_btn, self.power_btn, center, self.ring):
            add(o)

        for icon, act, var, px in (("back", "menu", "flat", 24), ("tv", "home", "flat", 119),
                                   ("play_pause", "play_pause", "primary", 214)):
            add(Button(cv, px, 444, 82, 56, lambda a=act: self.send(a), icon=icon, variant=var, r=14))
        for icon, act, px in (("prev", "prev", 24), ("vol_down", "vol_down", 94),
                              ("vol_up", "vol_up", 164), ("next", "next", 234)):
            add(Button(cv, px, 516, 62, 48, lambda a=act: self.send(a), icon=icon))

        # поле вводу тексту
        cv.create_image(24, 588, anchor="nw", image=shape_img(216, 44, 12, SURFACE, BORDER))
        self.entry = tk.Entry(self.root, bg=SURFACE, fg=TEXT, insertbackground=TEXT, relief="flat",
                              font=F(13), highlightthickness=0, bd=0)
        self.entry.bind("<Return>", lambda e: self.send_text())
        cv.create_window(24 + 16, 588 + 22, anchor="w", window=self.entry, width=216 - 32)
        add(Button(cv, 252, 588, 44, 44, self.send_text, icon="send"))

        self.status_id = cv.create_text(W / 2, 656, text="", fill=SUB, font=F(10), width=272)

        self.hot = None
        self.down = None
        cv.bind("<Motion>", self._motion)
        cv.bind("<Leave>", lambda e: self._leave())
        cv.bind("<ButtonPress-1>", self._press)
        cv.bind("<ButtonRelease-1>", self._release)

        keys = {"<Up>": "up", "<Down>": "down", "<Left>": "left", "<Right>": "right",
                "<Return>": "select", "<Escape>": "menu", "<space>": "play_pause"}
        for key, action in keys.items():
            self.root.bind(key, lambda e, a=action: self.key_press(a))

    # ---------- мишка ----------
    def _find(self, x, y):
        for o in self.objs:
            if o.hit(x, y):
                return o
        return None

    def _motion(self, e):
        o = self._find(e.x, e.y)
        if o is not self.hot:
            if self.hot:
                self.hot.leave()
            self.hot = o
            self.cv.configure(cursor=HAND if o else "")
        if o:
            o.move(e.x, e.y)

    def _leave(self):
        if self.hot:
            self.hot.leave()
            self.hot = None
        self.cv.configure(cursor="")

    def _press(self, e):
        self.down = self._find(e.x, e.y)
        if self.down:
            self.down.press(e.x, e.y)

    def _release(self, e):
        o, self.down = self.down, None
        if o:
            o.release(e.x, e.y, self._find(e.x, e.y) is o)

    def status(self, text):
        self.cv.itemconfigure(self.status_id, text=text)

    def key_press(self, action):
        w = self.root.focus_get()
        if w is not None and w.winfo_class() in ("Entry", "TEntry"):
            return
        if action in ("up", "down", "left", "right"):
            self.ring.flash(action)
        self.send(action)

    # ---------- меню ----------
    def show_devices(self):
        m = tk.Menu(self.root, tearoff=0)
        if not self.configs:
            m.add_command(label="Пристроїв не знайдено", state="disabled")
        for c in self.configs:
            paired = c.identifier in self.store["devices"]
            m.add_command(label=("✓  " if paired else "+  ") + c.name, command=lambda c=c: self.choose(c))
        m.add_separator()
        m.add_command(label="Знайти знову", command=self.scan)
        if self.current:
            m.add_command(label=f"Спарувати «{self.current.name}» заново…",
                          command=lambda: self.pair(self.current))
        m.tk_popup(self.cv.winfo_rootx() + 24, self.cv.winfo_rooty() + 24 + 44 + 4)

    def show_power(self):
        m = tk.Menu(self.root, tearoff=0)
        m.add_command(label="Увімкнути Apple TV", command=lambda: self.send("power_on"))
        m.add_command(label="Вимкнути Apple TV", command=lambda: self.send("power_off"))
        m.tk_popup(self.cv.winfo_rootx() + 252, self.cv.winfo_rooty() + 24 + 44 + 4)

    def choose(self, conf):
        if conf.identifier in self.store["devices"]:
            self.connect_conf(conf)
        else:
            self.pair(conf)

    # ---------- async ----------
    def run(self, coro, on_done=None, on_error=None):
        fut = self.runner.submit(coro)

        def done(f):
            try:
                res = f.result()
            except Exception as e:  # noqa: BLE001
                self.root.after(0, lambda e=e: (on_error or self.on_error)(e))
                return
            if on_done:
                self.root.after(0, lambda: on_done(res))

        fut.add_done_callback(done)

    def on_error(self, e):
        self.status(f"Помилка: {e}")

    # ---------- пошук ----------
    async def _scan(self):
        return await pyatv.scan(asyncio.get_running_loop(), timeout=5)

    def scan(self):
        self.status("Шукаю Apple TV у мережі…")
        if not self.atv:
            self.dev_btn.set_text("Пошук…")
        self.run(self._scan(), self.scan_done)

    def scan_done(self, configs):
        self.configs = sorted(configs, key=lambda c: c.name)
        if not self.atv:
            self.dev_btn.set_text("Виберіть Apple TV  ▾")
        if not self.configs:
            self.status("Пристроїв не знайдено. Mac і Apple TV мають бути в одній мережі.")
            return
        self.status(f"Знайдено пристроїв: {len(self.configs)}")
        last = self.store.get("last")
        conf = next((c for c in self.configs if c.identifier == last), None)
        if conf and self.auto_connect and not self.atv:
            self.auto_connect = False
            self.connect_conf(conf)

    # ---------- спарювання ----------
    async def _pair_begin(self, conf, proto):
        p = await pyatv.pair(conf, proto, asyncio.get_running_loop())
        await p.begin()
        self.pairing = p

    async def _pair_finish(self, pin):
        p = self.pairing
        p.pin(pin)
        await p.finish()
        creds = p.service.credentials if p.has_paired else None
        await p.close()
        self.pairing = None
        return creds

    async def _cancel_pairing(self):
        if self.pairing:
            await self.pairing.close()
            self.pairing = None

    def pair(self, conf):
        if conf.get_service(Protocol.Companion):
            protos = [Protocol.Companion, Protocol.AirPlay]
        else:
            protos = [Protocol.MRP, Protocol.AirPlay]
        protos = [p for p in protos if conf.get_service(p)]
        creds = {}
        for proto in protos:
            try:
                self.status(f"Спарювання ({proto.name}): дивіться PIN на екрані ТВ…")
                self.root.update_idletasks()
                self.runner.submit(self._pair_begin(conf, proto)).result(30)
                pin = simpledialog.askstring(
                    "PIN", f"Введіть PIN-код, який показує Apple TV ({proto.name}):", parent=self.root)
                if not pin:
                    self.runner.submit(self._cancel_pairing()).result(10)
                    continue
                c = self.runner.submit(self._pair_finish(pin.strip())).result(30)
                if c:
                    creds[proto.name] = c
            except Exception as e:  # noqa: BLE001
                messagebox.showwarning("Спарювання", f"{proto.name}: {e}")
        if not creds:
            self.status("Спарювання не вдалося.")
            return
        self.store["devices"][conf.identifier] = {"name": conf.name, "creds": creds}
        self.store["last"] = conf.identifier
        self.save_store()
        self.status("Спарено! Підключаюсь…")
        self.connect_conf(conf)

    # ---------- підключення ----------
    async def _connect(self, conf, creds):
        if self.atv:
            self.atv.close()
            self.atv = None
        for name, c in creds.items():
            conf.set_credentials(Protocol[name], c)
        return await pyatv.connect(conf, asyncio.get_running_loop())

    def connect_conf(self, conf):
        entry = self.store["devices"].get(conf.identifier)
        if not entry:
            self.pair(conf)
            return
        self.status(f"Підключаюсь до {conf.name}…")
        self.dev_btn.set_text(f"{conf.name}  ▾")
        self.dev_btn.set_dot(False)

        def ok(atv):
            self.atv = atv
            self.current = conf
            self.store["last"] = conf.identifier
            self.save_store()
            self.dev_btn.set_text(f"{conf.name}  ▾")
            self.dev_btn.set_dot(True)
            self.card.set(conf.name, "Підключено")
            self.card.set_cover(None)
            self.card.set_progress(0, 0)
            self.prog = None
            self.cover_key = None
            self.status("")

        self.run(self._connect(conf, entry["creds"]), ok)

    # ---------- команди ----------
    def send(self, name):
        if not self.atv:
            self.status("Спочатку виберіть і підключіть Apple TV.")
            return
        self.run(ACTIONS[name](self.atv), on_done=lambda _: self.status(""))

    def send_text(self):
        text = self.entry.get()
        if not self.atv or not text:
            return
        self.run(self.atv.keyboard.text_set(text), on_done=lambda _: self.status("Текст надіслано"))

    # ---------- перемотка (з Центру керування) ----------
    async def _seek(self, pos, cur):
        rc = self.atv.remote_control
        try:
            await rc.set_position(int(pos))
        except Exception:  # noqa: BLE001
            delta = pos - cur
            if abs(delta) < 1:
                return
            if delta > 0:
                await rc.skip_forward(abs(delta))
            else:
                await rc.skip_backward(abs(delta))

    def seek(self, pos):
        if not self.atv:
            return
        self.run(self._seek(pos, self.position),
                 on_done=lambda _: self.root.after(700, self.refresh),
                 on_error=lambda e: self.status("Перемотка недоступна у цьому застосунку"))

    # ---------- що зараз грає ----------
    async def _playing(self):
        md = self.atv.metadata
        p = await md.playing()
        app = None
        try:
            app = md.app.name
        except Exception:  # noqa: BLE001
            pass
        try:
            key = md.artwork_id or (p.title, p.artist)
        except Exception:  # noqa: BLE001
            key = (p.title, p.artist)
        fetched, cover, raw = False, None, None
        if key != self.cover_key:
            fetched = True
            try:
                art = await md.artwork(width=300, height=300)
                if art and art.bytes:
                    raw = art.bytes
                    cover = make_cover(art.bytes)
            except Exception:  # noqa: BLE001
                cover, raw = None, None
        return p, app, key, fetched, cover, raw

    def poll(self):
        self.root.after(3000, self.poll)
        self.refresh()

    def refresh(self):
        if not self.atv or self.polling:
            return
        self.polling = True

        def done(res):
            self.polling = False
            p, app, key, fetched, cover, raw = res
            self.position = p.position or 0
            if fetched:
                self.cover_key = key
                self.card.set_cover(cover)
            state = p.device_state.name if p.device_state else ""
            names = {"Playing": "Грає", "Paused": "Пауза", "Idle": "Очікування",
                     "Stopped": "Зупинено", "Loading": "Завантаження", "Seeking": "Перемотування"}
            sub = " · ".join(x for x in (p.artist, app, names.get(state, state)) if x)
            self.card.set(p.title or (app or self.current.name), sub or "—")
            playing = state in ("Playing", "Loading", "Seeking")
            self.prog = (p.position or 0, p.total_time or 0, playing, time.time())
            self.card.set_progress(p.position or 0, p.total_time or 0)
            self.mac.update(p, app, raw, fetched)

        def err(e):
            self.polling = False

        self.run(self._playing(), done, err)

    def tick(self):
        """Плавний рух шкали часу між опитуваннями."""
        self.root.after(500, self.tick)
        if self.prog and self.prog[2] and self.prog[1]:
            pos, total, _, t0 = self.prog
            self.card.set_progress(min(total, pos + (time.time() - t0)), total)


def main():
    if Image is None:
        r = tk.Tk()
        r.withdraw()
        messagebox.showerror("Apple TV", "Потрібен пакет Pillow:\npip install pillow")
        return
    root = tk.Tk()
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    icon = base / "icon.png"
    if icon.exists():
        try:
            root._icon = tk.PhotoImage(file=str(icon))
            root.iconphoto(True, root._icon)
        except Exception:  # noqa: BLE001
            pass
    App(root)
    if sys.platform == "darwin":
        def show(*_):
            root.deiconify()
            root.lift()
        root.protocol("WM_DELETE_WINDOW", root.withdraw)  # червона кнопка лише ховає вікно
        root.createcommand("tk::mac::ReopenApplication", show)  # клік по іконці в Dock повертає його
    root.mainloop()


if __name__ == "__main__":
    main()
