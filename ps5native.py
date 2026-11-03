"""Python side of native/ps5bridge.dll (chiaki-ng libchiaki + bridge.c).

NativeSession is one Remote Play session: controller input, PS5 keyboard
text, Home, rest mode, and the H.264 video, decoded with PyAV on a worker
thread that keeps only the newest frame.
"""
from __future__ import annotations

import base64
import ctypes as C
import io
import logging
import os
import queue
import threading
import time
from pathlib import Path

import av
from PIL import Image, ImageOps

log = logging.getLogger("ps5native")

DLL_PATH = Path(__file__).parent / "native" / "ps5bridge.dll"

VIDEO_CB = C.CFUNCTYPE(C.c_int, C.POINTER(C.c_uint8), C.c_size_t, C.c_int32, C.c_int, C.c_void_p)
EVENT_CB = C.CFUNCTYPE(None, C.c_int, C.c_int, C.c_char_p, C.c_void_p)
LOG_CB = C.CFUNCTYPE(None, C.c_int, C.c_char_p, C.c_void_p)

EV_CONNECTED, EV_LOGIN_PIN, EV_KB_OPEN, EV_KB_TEXT, EV_KB_CLOSE, EV_RUMBLE, EV_QUIT, EV_FEC = 0, 1, 5, 6, 7, 8, 9, 16
EV_CANT_DISPLAY = 100

BUTTONS = {
    "CROSS": 1 << 0, "CIRCLE": 1 << 1, "SQUARE": 1 << 2, "TRIANGLE": 1 << 3,
    "LEFT": 1 << 4, "RIGHT": 1 << 5, "UP": 1 << 6, "DOWN": 1 << 7,
    "L1": 1 << 8, "R1": 1 << 9, "L3": 1 << 10, "R3": 1 << 11,
    "OPTIONS": 1 << 12, "SHARE": 1 << 13, "TOUCHPAD": 1 << 14, "PS": 1 << 15,
}
TRIGGERS = {"L2", "R2"}
RESOLUTIONS = {"360p": 1, "540p": 2, "720p": 3, "1080p": 4}
LOG_MASK = int(os.environ.get("PS5_CHIAKI_LOG_MASK", str((1 << 0) | (1 << 1) | (1 << 2))))  # error, warning, info

_dll = None


def dll() -> C.CDLL:
    global _dll
    if _dll is None:
        d = C.CDLL(str(DLL_PATH))
        d.ps5_lib_init.restype = C.c_int
        d.ps5_error_string.restype = C.c_char_p
        d.ps5_error_string.argtypes = [C.c_int]
        d.ps5_start.restype = C.c_void_p
        d.ps5_start.argtypes = [
            C.c_char_p, C.c_char_p, C.c_char_p, C.c_char_p,
            C.c_int, C.c_int, C.c_int, C.c_int, C.c_int,
            VIDEO_CB, EVENT_CB, LOG_CB, C.c_int, C.c_void_p, C.POINTER(C.c_int),
        ]
        d.ps5_set_controller.restype = C.c_int
        d.ps5_set_controller.argtypes = [C.c_void_p, C.c_uint32, C.c_uint8, C.c_uint8,
                                         C.c_int16, C.c_int16, C.c_int16, C.c_int16]
        for name in ("ps5_keyboard_accept", "ps5_keyboard_reject", "ps5_go_home", "ps5_goto_bed"):
            getattr(d, name).restype = C.c_int
            getattr(d, name).argtypes = [C.c_void_p]
        for name in ("ps5_keyboard_set_text", "ps5_set_login_pin"):
            getattr(d, name).restype = C.c_int
            getattr(d, name).argtypes = [C.c_void_p, C.c_char_p]
        d.ps5_stop.restype = None
        d.ps5_stop.argtypes = [C.c_void_p]
        d.ps5_register.restype = C.c_int
        d.ps5_register.argtypes = [C.c_char_p, C.c_char_p, C.c_uint32, C.c_int,
                                   C.c_char_p, C.c_char_p, C.c_char_p, C.c_char_p,
                                   LOG_CB, C.c_int, C.c_void_p]
        err = d.ps5_lib_init()
        if err:
            raise RuntimeError(f"libchiaki init failed: {d.ps5_error_string(err).decode()}")
        _dll = d
    return _dll


def register(host: str, account_id: bytes, pin: str, timeout_s: float = 10.0) -> dict:
    """Link this computer to a PS5 with the 8-digit PIN from Link Device.

    Returns {"mac", "nickname", "regist_key", "rp_key"} (keys as bytes).
    """
    digits = "".join(ch for ch in pin if ch.isdigit())
    if len(digits) != 8:
        raise ValueError("The PIN has 8 digits.")
    regist_key = C.create_string_buffer(16)
    rp_key = C.create_string_buffer(16)
    nickname = C.create_string_buffer(32)
    mac = C.create_string_buffer(6)
    log_cb = LOG_CB(lambda level, msg, _u: log.info("regist: %s", msg.decode(errors="replace") if msg else ""))
    err = dll().ps5_register(host.encode(), account_id, int(digits), int(timeout_s * 1000),
                             regist_key, rp_key, nickname, mac, log_cb, LOG_MASK, None)
    if err:
        raise RuntimeError(f"Linking failed: {dll().ps5_error_string(err).decode()}. "
                           "Check the PIN (it expires after about 5 minutes) and try again.")
    return {
        "mac": mac.raw.hex().upper(),
        "nickname": nickname.value.decode(errors="replace"),
        "regist_key": regist_key.raw,
        "rp_key": rp_key.raw,
    }


class NativeSession:
    def __init__(self, host: str, regist_key: bytes, morning: bytes, account_id: bytes,
                 resolution: str = "720p", fps: int = 60, bitrate_kbps: int = 0):
        self.host = host
        self.handle = None
        self.connected = False
        self.stopped = False
        self.quit_reason = ""
        self.keyboard_open = False
        self.keyboard_text = ""
        self.cant_display = False
        self.frames = 0
        self.frame_time = 0.0
        self.samples = 0
        self.frames_lost = 0
        self._frame = None
        self._frame_lock = threading.Lock()
        self._buttons = 0
        self._l2 = self._r2 = 0
        self._sticks = [0, 0, 0, 0]
        self._input_lock = threading.Lock()
        self._connected_evt = threading.Event()
        self._q: queue.Queue[bytes | None] = queue.Queue(maxsize=120)
        self._decoder = av.CodecContext.create("h264", "r")
        self._decoder.thread_type = "AUTO"
        self._worker = threading.Thread(target=self._decode_loop, name="ps5-decode", daemon=True)
        self._worker.start()
        # Keep ctypes callback objects alive for the life of the session.
        self._video_cb = VIDEO_CB(self._on_video)
        self._event_cb = EVENT_CB(self._on_event)
        self._log_cb = LOG_CB(self._on_log)
        err = C.c_int(0)
        self.handle = dll().ps5_start(
            host.encode(), regist_key, morning, account_id,
            1, RESOLUTIONS.get(resolution, 3), fps, bitrate_kbps, 0,
            self._video_cb, self._event_cb, self._log_cb, LOG_MASK, None, C.byref(err),
        )
        if not self.handle:
            self.stopped = True
            self._q.put(None)
            raise RuntimeError(f"Remote Play start failed: {dll().ps5_error_string(err.value).decode()}")

    # ---------- callbacks (libchiaki threads) ----------
    def _on_video(self, buf, size, frames_lost, recovered, _user) -> int:
        self.samples += 1
        self.frames_lost += max(0, frames_lost)
        data = C.string_at(buf, size)
        try:
            self._q.put_nowait(data)
        except queue.Full:
            # Decoder fell behind. Drop the backlog and ask for a fresh keyframe.
            self._drain()
            return 0
        return 1

    def _on_event(self, etype, code, text, _user) -> None:
        msg = text.decode(errors="replace") if text else ""
        if etype == EV_CONNECTED:
            self.connected = True
            self._connected_evt.set()
            log.info("Remote Play connected")
        elif etype == EV_QUIT:
            self.connected = False
            self.stopped = True
            self.quit_reason = msg
            self._connected_evt.set()
            log.info("Remote Play ended: %s", msg)
        elif etype == EV_KB_OPEN:
            self.keyboard_open = True
            self.keyboard_text = msg
        elif etype == EV_KB_TEXT:
            self.keyboard_text = msg
        elif etype == EV_KB_CLOSE:
            self.keyboard_open = False
        elif etype == EV_CANT_DISPLAY:
            self.cant_display = bool(code)
            log.info("PS5 %s the picture", "is blanking" if code else "is showing")
        elif etype == EV_LOGIN_PIN:
            log.warning("PS5 asked for a login PIN (console has a login passcode). Not supported yet.")

    def _on_log(self, level, msg, _user) -> None:
        text = msg.decode(errors="replace") if msg else ""
        if level & 1:
            log.error("chiaki: %s", text)
        elif level & 2:
            log.warning("chiaki: %s", text)
        elif level & 4:
            log.info("chiaki: %s", text)
        else:
            log.debug("chiaki: %s", text)

    # ---------- video ----------
    def _drain(self) -> None:
        try:
            while True:
                self._q.get_nowait()
        except queue.Empty:
            pass

    def _decode_loop(self) -> None:
        while True:
            data = self._q.get()
            if data is None:
                return
            try:
                frames = self._decoder.decode(av.Packet(data))
            except av.error.InvalidDataError:
                continue
            if frames:
                with self._frame_lock:
                    self._frame = frames[-1]
                    self.frame_time = time.time()
                    self.frames += 1

    def jpeg(self, max_width: int = 1280, quality: int = 80, enhance: bool = False,
             crop: tuple[float, float, float, float] | None = None) -> bytes | None:
        """Newest frame as JPEG.

        crop: (x, y, w, h) as fractions of the frame, for zooming in on part
        of the screen. enhance: stretch contrast and lift shadows, which makes
        dark game scenes readable.
        """
        with self._frame_lock:
            frame = self._frame
        if frame is None:
            return None
        img = frame.to_image()
        if crop:
            x, y, w, h = (max(0.0, min(1.0, v)) for v in crop)
            box = (int(x * img.width), int(y * img.height),
                   int(min(1.0, x + w) * img.width), int(min(1.0, y + h) * img.height))
            if box[2] > box[0] + 8 and box[3] > box[1] + 8:
                img = img.crop(box)
        if enhance:
            img = ImageOps.autocontrast(img, cutoff=1)
            img = img.point(lambda v: int(255 * (v / 255) ** 0.6))
        if img.width != max_width and (crop or img.width > max_width):
            img = img.resize((max_width, round(img.height * max_width / img.width)), Image.LANCZOS)
        out = io.BytesIO()
        img.save(out, "JPEG", quality=quality)
        return out.getvalue()

    def stats(self) -> dict:
        with self._frame_lock:
            f = self._frame
        out = {"samples": self.samples, "frames": self.frames, "frames_lost": self.frames_lost,
               "queue": self._q.qsize(), "connected": self.connected, "quit": self.quit_reason,
               "cant_display": self.cant_display}
        if f is not None:
            img = f.to_image().convert("L").resize((64, 36))
            px = list(img.getdata())
            out.update(size=f"{f.width}x{f.height}", luma_mean=round(sum(px) / len(px), 1))
        return out

    # ---------- input ----------
    def wait_connected(self, timeout: float) -> bool:
        self._connected_evt.wait(timeout)
        return self.connected

    def _push(self) -> None:
        if self.handle and not self.stopped:
            lx, ly, rx, ry = self._sticks
            dll().ps5_set_controller(self.handle, self._buttons, self._l2, self._r2, lx, ly, rx, ry)

    def button(self, name: str, down: bool) -> None:
        name = name.upper()
        with self._input_lock:
            if name in TRIGGERS:
                if name == "L2":
                    self._l2 = 255 if down else 0
                else:
                    self._r2 = 255 if down else 0
            else:
                bit = BUTTONS[name]
                self._buttons = (self._buttons | bit) if down else (self._buttons & ~bit)
            self._push()

    def stick(self, which: str, x: float, y: float) -> None:
        sx = int(max(-1.0, min(1.0, x)) * 0x7FFF)
        sy = int(max(-1.0, min(1.0, y)) * 0x7FFF)
        with self._input_lock:
            if which == "left":
                self._sticks[0], self._sticks[1] = sx, sy
            else:
                self._sticks[2], self._sticks[3] = sx, sy
            self._push()

    def set_state(self, held: set[str], left: tuple[float, float] = (0.0, 0.0),
                  right: tuple[float, float] = (0.0, 0.0)) -> None:
        """Set the whole controller at once: these buttons down, everything else up."""
        def axis(v: float) -> int:
            return int(max(-1.0, min(1.0, v)) * 0x7FFF)
        with self._input_lock:
            self._buttons = 0
            for name in held:
                if name in BUTTONS:
                    self._buttons |= BUTTONS[name]
            self._l2 = 255 if "L2" in held else 0
            self._r2 = 255 if "R2" in held else 0
            self._sticks = [axis(left[0]), axis(left[1]), axis(right[0]), axis(right[1])]
            self._push()

    def keyboard_set_text(self, text: str) -> None:
        dll().ps5_keyboard_set_text(self.handle, text.encode("utf-8"))

    def keyboard_accept(self) -> None:
        dll().ps5_keyboard_accept(self.handle)
        self.keyboard_open = False

    def go_home(self) -> None:
        dll().ps5_go_home(self.handle)

    def goto_bed(self) -> None:
        dll().ps5_goto_bed(self.handle)

    def stop(self) -> None:
        if self.handle:
            h, self.handle = self.handle, None
            dll().ps5_stop(h)
        self.stopped = True
        self.connected = False
        self._q.put(None)
