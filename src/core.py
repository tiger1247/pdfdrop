"""PDFDrop shared constants, settings and helpers."""
import json
import os
import tempfile

APP_NAME = "PDFDrop"
APP_ID = "PDFDrop"


def is_packaged():
    """True when running from the MSIX (Microsoft Store) package."""
    import ctypes
    length = ctypes.c_uint32(0)
    try:
        return ctypes.windll.kernel32.GetCurrentPackageFullName(ctypes.byref(length), None) != 15700
    except (AttributeError, OSError):
        return False


PACKAGED = is_packaged()
DIRECT = os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), "DIRECT_EDITION"))
APPDATA_DIR = os.environ.get("PD_DATA_DIR") or os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP_ID)
CONFIG_PATH = os.path.join(APPDATA_DIR, "config.json")
TEMP_DIR = os.path.join(tempfile.gettempdir(), APP_ID)

DEFAULTS = {"recent": [], "last_dir": "", "pen_color": "#d32f2f", "pen_width": 2.0,
            "text_color": "#111111", "text_size": 14, "signature": ""}


def load_settings():
    s = dict(DEFAULTS)
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            s.update({k: v for k, v in json.load(f).items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    return s


def save_settings(s):
    try:
        os.makedirs(APPDATA_DIR, exist_ok=True)
        tmp = CONFIG_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(s, f, indent=1)
        os.replace(tmp, CONFIG_PATH)
    except OSError:
        pass


def add_recent(s, path):
    path = os.path.abspath(path)
    s["recent"] = [path] + [p for p in s.get("recent", []) if os.path.normcase(p) != os.path.normcase(path)]
    s["recent"] = s["recent"][:8]
    s["last_dir"] = os.path.dirname(path)
    save_settings(s)


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024


def unique_path(path):
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    i = 2
    while os.path.exists(f"{base} ({i}){ext}"):
        i += 1
    return f"{base} ({i}){ext}"


def hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
