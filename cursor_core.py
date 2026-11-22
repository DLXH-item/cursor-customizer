# -*- coding: utf-8 -*-
"""鼠标光标设置器 · 核心逻辑
媒体抽帧 -> CUR / ANI -> 写入系统鼠标样式 / 恢复默认 / 历史记录
"""
import os
import sys
import io
import json
import shutil
import struct
import tempfile
import time
import ctypes
from ctypes import wintypes

from PIL import Image

# ---------------------------------------------------------------- 常量
SPI_SETCURSORS = 0x0057
SPIF_UPDATEINIFILE = 0x01
SPIF_SENDCHANGE = 0x02

CURSOR_REG = r"Control Panel\Cursors"

# 数据目录多级兜底：优先 AppData\Local，其次用户目录，最后系统临时目录，
# 保证 exe 在只读目录 / 受限账户下仍可写缓存与备份
def _writable(d):
    try:
        os.makedirs(os.path.join(d, "cursors"), exist_ok=True)
        os.makedirs(os.path.join(d, "history"), exist_ok=True)
        t = os.path.join(d, ".wtest")
        with open(t, "w") as f:
            f.write("x")
        os.remove(t)
        return True
    except OSError:
        return False


def _pick_data_dir():
    candidates = [
        os.path.join(os.environ.get("LOCALAPPDATA") or "", "CursorCustomizer"),
        os.path.join(os.path.expanduser("~"), ".CursorCustomizer"),
        os.path.join(tempfile.gettempdir(), "CursorCustomizer"),
    ]
    for c in candidates:
        if _writable(c):
            return c
    return candidates[-1]


APP_DATA_DIR = _pick_data_dir()
ASSETS_DIR = os.path.join(APP_DATA_DIR, "cursors")
HISTORY_DIR = os.path.join(APP_DATA_DIR, "history")
BACKUP_FILE = os.path.join(APP_DATA_DIR, "cursor_backup.json")
HISTORY_FILE = os.path.join(HISTORY_DIR, "history.json")
CURRENT_META = os.path.join(APP_DATA_DIR, "current.json")
CURRENT_THUMB = os.path.join(ASSETS_DIR, "current_thumb.png")
CUR_OUT = os.path.join(ASSETS_DIR, "custom_arrow.cur")
ANI_OUT = os.path.join(ASSETS_DIR, "custom_arrow.ani")

MAX_CURSOR_SIZE = 128  # 光标边长上限（px）


def active_cursor_path(size, ext):
    """生成带尺寸与时间戳的唯一活动光标文件名。
    每次应用都指向新文件，避免 Windows 对同一路径覆盖文件的光标缓存，
    保证换尺寸/换样式后系统真正重新加载。"""
    _ensure_dirs()
    stamp = time.strftime("%Y%m%d-%H%M%S") + "-" + str(time.time_ns() % 100000)
    return os.path.join(ASSETS_DIR, f"arrow_{size}_{stamp}{ext}")


def cleanup_old_active(keep_path=None):
    """清理旧的活动光标文件，保留当前正在使用的那个。"""
    try:
        keep = os.path.normpath(keep_path).lower() if keep_path else None
        for fn in os.listdir(ASSETS_DIR):
            if not (fn.lower().endswith(".cur") or fn.lower().endswith(".ani")):
                continue
            p = os.path.join(ASSETS_DIR, fn)
            if keep and os.path.normpath(p).lower() == keep:
                continue
            try:
                os.remove(p)
            except OSError:
                pass
    except OSError:
        pass

# 常见系统光标项，备份/恢复时整体处理
CURSOR_NAMES = [
    "Arrow", "HelpWait", "AppStarting", "Wait", "IBeam",
    "SizeNS", "SizeWE", "SizeNWSE", "SizeNESW", "SizeAll",
    "No", "Hand", "Crosshair", "UpArrow", "Pin",
]

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".ico", ".cur"}
GIF_EXTS = {".gif", ".webp"}
VIDEO_EXTS = {".mp4", ".avi", ".mov", ".mkv", ".webm"}


def _ensure_dirs():
    os.makedirs(ASSETS_DIR, exist_ok=True)
    os.makedirs(HISTORY_DIR, exist_ok=True)


_ensure_dirs()


# ---------------------------------------------------------------- 抽帧
def load_frames(path):
    """读取媒体，返回 [(PIL.Image(RGBA), duration_ms), ...]"""
    ext = os.path.splitext(path)[1].lower()

    if ext in VIDEO_EXTS:
        try:
            import imageio.v2 as imageio
        except Exception:
            raise ValueError("未检测到视频解码组件，暂不支持视频；请先将视频转为 GIF 后再导入")
        reader = imageio.get_reader(path)
        meta = reader.get_meta_data()
        fps = meta.get("fps") or 25
        try:
            total = reader.count_frames()
        except Exception:
            total = 0
        if not total:
            total = int(meta.get("nframes") or 1)
        n = min(24, max(1, total))
        idxs = [int(k * (total - 1) / (n - 1)) for k in range(n)] if n > 1 else [0]
        frames = []
        for idx in idxs:
            try:
                frame = reader.get_data(idx)
            except Exception:
                continue
            frames.append((Image.fromarray(frame).convert("RGBA"), int(1000 / fps)))
        reader.close()
        if not frames:
            raise ValueError("视频中未读取到有效帧")
        return frames

    im = Image.open(path)
    # 多帧动图：GIF 全部逐帧；WebP 仅当为动画（n_frames>1）时逐帧，静态 WebP 按单图处理
    multi_webp = ext == ".webp" and getattr(im, "n_frames", 1) > 1
    if ext == ".gif" or multi_webp:
        frames = []
        i = 0
        while True:
            im.seek(i)
            dur = im.info.get("duration", 120) or 120
            frames.append((im.convert("RGBA").copy(), int(dur)))
            i += 1
            try:
                im.seek(i)
            except EOFError:
                break
        return frames

    # 单张静态图
    return [(im.convert("RGBA").copy(), 0)]


def normalize(img, size=MAX_CURSOR_SIZE):
    """等比缩放到透明正方形画布内"""
    img = img.convert("RGBA")
    w, h = img.size
    scale = min(size / w, size / h)
    nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
    img = img.resize((nw, nh), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(img, ((size - nw) // 2, (size - nh) // 2), img)
    return canvas


def crop_image(img, rect):
    """按 (left, top, right, bottom) 裁剪，边界自动收敛"""
    l, t, r, b = rect
    l = max(0, int(l)); t = max(0, int(t))
    r = min(img.width, int(r)); b = min(img.height, int(b))
    if r - l < 2 or b - t < 2:
        return img.copy()
    return img.crop((l, t, r, b))


# ---------------------------------------------------------------- CUR
def image_to_cur_bytes(img, hotspot=None, size=MAX_CURSOR_SIZE):
    """PIL 图 -> CUR 文件字节（type=2，热点默认中心）"""
    img = normalize(img, size)
    if hotspot is None:
        hotspot = (img.size[0] // 2, img.size[1] // 2)
    buf = io.BytesIO()
    img.save(buf, format="ICO", sizes=[img.size])
    data = bytearray(buf.getvalue())
    data[2] = 2  # type: CUR = 2
    data[3] = 0
    hx, hy = hotspot
    data[6 + 4] = hx & 0xFF
    data[6 + 5] = (hx >> 8) & 0xFF
    data[6 + 6] = hy & 0xFF
    data[6 + 7] = (hy >> 8) & 0xFF
    return bytes(data)


def save_static_cur(img, path=CUR_OUT, hotspot=None, size=MAX_CURSOR_SIZE):
    _ensure_dirs()
    with open(path, "wb") as f:
        f.write(image_to_cur_bytes(img, hotspot, size))
    return path


# ---------------------------------------------------------------- ANI
def _riff_chunk(tag, payload):
    pad = b"\x00" if len(payload) % 2 else b""
    return tag + struct.pack("<I", len(payload)) + payload + pad


def _riff_list(list_type, chunks):
    body = list_type + b"".join(chunks)
    return b"LIST" + struct.pack("<I", len(body)) + body


def frames_to_ani(frames, durations_ms, path=ANI_OUT, jiffy=None, size=MAX_CURSOR_SIZE):
    """帧序列 -> ANI 动画光标。jiffy = 1/60 秒帧间隔。"""
    _ensure_dirs()
    cur_blobs = [image_to_cur_bytes(normalize(f, size)) for f in frames]
    n = len(cur_blobs)

    if jiffy is None:
        valid = [d for d in durations_ms if d > 0]
        if valid:
            avg = sum(valid) / len(valid)
            jiffy = max(1, round(avg / 16.667))
        else:
            jiffy = 6

    # fFlags: AF_ICON(0x1) 必须置位，帧才按完整 CUR 解析，否则只会显示第一帧
    # 宽高写 0，由各帧图标自身尺寸决定（与系统自带 ANI 一致）
    anih = struct.pack("<IIIIIIIII", 36, n, n, 0, 0, 32, 1, jiffy, 1)
    name_b = "Cursor".encode("ascii", "ignore") + b"\x00"
    info_list = _riff_list(b"INFO", [_riff_chunk(b"INAM", name_b)])
    fram_chunks = [_riff_chunk(b"icon", blob) for blob in cur_blobs]
    fram_list = _riff_list(b"fram", fram_chunks)

    body = _riff_chunk(b"anih", anih) + info_list + fram_list
    riff = b"RIFF" + struct.pack("<I", len(body) + 4) + b"ACON" + body

    with open(path, "wb") as f:
        f.write(riff)
    return path


# ---------------------------------------------------------------- 系统光标
def _reg_open(mode):
    import winreg
    return winreg.OpenKey(winreg.HKEY_CURRENT_USER, CURSOR_REG, 0, mode)


def _reg_get(name):
    import winreg
    try:
        key = _reg_open(winreg.KEY_READ)
        value, _ = winreg.QueryValueEx(key, name)
        winreg.CloseKey(key)
        return value
    except FileNotFoundError:
        return None
    except OSError:
        return None


def _reg_set(name, value):
    import winreg
    key = _reg_open(winreg.KEY_SET_VALUE)
    if value is None:
        try:
            winreg.DeleteValue(key, name)
        except FileNotFoundError:
            pass
    else:
        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
    winreg.CloseKey(key)


def _refresh_system():
    spi = ctypes.windll.user32.SystemParametersInfoW
    spi.restype = wintypes.BOOL
    spi(SPI_SETCURSORS, 0, None, SPIF_UPDATEINIFILE | SPIF_SENDCHANGE)


def _default_arrow():
    """系统自带默认箭头光标兜底路径"""
    root = os.environ.get("SystemRoot", r"C:\Windows")
    for name in ("aero_arrow.cur", "arrow.cur", "aero_arrow_1.cur"):
        p = os.path.join(root, "Cursors", name)
        if os.path.exists(p):
            return p
    return None


def backup_current():
    """仅在尚未备份时保存当前系统光标原值；写入失败不阻断设置"""
    if os.path.exists(BACKUP_FILE):
        return
    try:
        _ensure_dirs()
        data = {n: _reg_get(n) for n in CURSOR_NAMES}
        with open(BACKUP_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def apply_cursor(cursor_path, names=("Arrow",)):
    backup_current()
    for n in names:
        _reg_set(n, cursor_path)
    _refresh_system()
    cleanup_old_active(cursor_path)


def restore_default():
    """按备份恢复；备份缺失时回退系统默认光标，保证任何机器都能还原"""
    if os.path.exists(BACKUP_FILE):
        try:
            with open(BACKUP_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            for n, v in data.items():
                _reg_set(n, v)
        except Exception:
            data = {}
        try:
            os.remove(BACKUP_FILE)
        except OSError:
            pass
    else:
        default = _default_arrow()
        for n in CURSOR_NAMES:
            _reg_set(n, default if n == "Arrow" else None)
    _refresh_system()


def current_arrow_path():
    return _reg_get("Arrow")


def current_custom():
    v = _reg_get("Arrow")
    if not v:
        return False
    np = os.path.normpath(v).lower()
    base = os.path.basename(np)
    in_assets = np.startswith(os.path.normpath(ASSETS_DIR).lower())
    return in_assets and (base.startswith("arrow_") or base in (
        os.path.basename(CUR_OUT), os.path.basename(ANI_OUT)))


# ---------------------------------------------------------------- 当前样式元数据
def save_current_meta(source, mode, thumb_img=None, thumb_path=None):
    """持久化当前应用样式的缩略图与名称，供重启后直接展示。"""
    try:
        _ensure_dirs()
        thumb_ok = False
        if thumb_path and os.path.exists(thumb_path):
            shutil.copy2(thumb_path, CURRENT_THUMB)
            thumb_ok = True
        elif thumb_img is not None:
            normalize(thumb_img, 64).save(CURRENT_THUMB)
            thumb_ok = True
        data = {"source": source or "自定义光标", "mode": mode,
                "thumb": CURRENT_THUMB if thumb_ok else None}
        with open(CURRENT_META, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except OSError:
        pass


def load_current_meta():
    if not os.path.exists(CURRENT_META):
        return None
    try:
        with open(CURRENT_META, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("thumb") and not os.path.exists(data["thumb"]):
            data["thumb"] = None
        return data
    except Exception:
        return None


def clear_current_meta():
    for p in (CURRENT_META, CURRENT_THUMB):
        try:
            if os.path.exists(p):
                os.remove(p)
        except OSError:
            pass


# ---------------------------------------------------------------- 历史记录
def _read_history():
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _write_history(data):
    _ensure_dirs()
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def add_history(cursor_path, source_name, mode, thumb_img):
    """把当前已应用的光标存入历史，返回记录项"""
    _ensure_dirs()
    seq = len(_read_history()) + 1
    hid = time.strftime("%Y%m%d-%H%M%S") + "-" + str(seq).zfill(3)
    ext = os.path.splitext(cursor_path)[1].lower()
    dest = os.path.join(HISTORY_DIR, hid + ext)
    shutil.copy2(cursor_path, dest)
    thumb = os.path.join(HISTORY_DIR, hid + ".png")
    normalize(thumb_img, 64).save(thumb)
    item = {
        "id": hid,
        "file": dest,
        "source": source_name or "未命名",
        "mode": mode,
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "thumb": thumb,
    }
    data = _read_history()
    data.insert(0, item)
    _write_history(data)
    return item


def list_history():
    data = _read_history()
    valid = [x for x in data if os.path.exists(x.get("file", ""))]
    if len(valid) != len(data):
        _write_history(valid)
    return valid


def delete_history(ids):
    ids = set(ids)
    keep = []
    for x in _read_history():
        if x.get("id") in ids:
            for p in (x.get("file"), x.get("thumb")):
                if p and os.path.exists(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass
        else:
            keep.append(x)
    _write_history(keep)


def history_to_current(item_id):
    """将历史样式复制为当前活动光标文件（唯一文件名，避免缓存），返回 (路径, 模式)"""
    for x in _read_history():
        if x.get("id") == item_id and os.path.exists(x.get("file", "")):
            _ensure_dirs()
            ext = ".ani" if x["file"].lower().endswith(".ani") else ".cur"
            dest = active_cursor_path(64, ext)
            shutil.copy2(x["file"], dest)
            return dest, x.get("mode", "static")
    raise FileNotFoundError("历史样式不存在或已被删除")
