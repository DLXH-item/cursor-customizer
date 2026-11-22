# -*- coding: utf-8 -*-
"""鼠标光标设置器 · GUI
拖入 / 上传图片、GIF、动图 -> 裁剪 / 选帧 -> 设置 / 恢复 / 历史样式
"""
import os
import sys

from PIL import Image
from PySide6.QtCore import Qt, Signal, QRect, QPoint
from PySide6.QtGui import QPixmap, QImage, QPainter, QColor, QFont, QPen, QIcon
from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QSlider,
    QFileDialog, QHBoxLayout, QVBoxLayout, QFrame,
    QScrollArea, QCheckBox, QGraphicsDropShadowEffect,
)

import cursor_core as core

SUPPORTED = "图片/GIF (*.png *.jpg *.jpeg *.bmp *.webp *.ico *.gif)"


def pil_to_pixmap(img):
    img = img.convert("RGBA")
    data = img.tobytes("raw", "RGBA")
    qimg = QImage(data, img.width, img.height, img.width * 4, QImage.Format_RGBA8888)
    return QPixmap.fromImage(qimg.copy())


def _fit_image(img, box=240):
    w, h = img.size
    sc = min(box / w, box / h)
    return img.resize((max(1, round(w * sc)), max(1, round(h * sc))), Image.LANCZOS)


def _shadow(widget, blur=18, dy=4, alpha=150):
    eff = QGraphicsDropShadowEffect(widget)
    eff.setBlurRadius(blur)
    eff.setOffset(0, dy)
    eff.setColor(QColor(190, 206, 228, alpha))
    widget.setGraphicsEffect(eff)


class CropPreview(QLabel):
    """棋盘格透明预览 + 可移动、四角/四边拖拽缩放的裁剪框"""

    cropChanged = Signal()
    MIN_SIDE = 8

    def __init__(self):
        super().__init__()
        self.setAlignment(Qt.AlignCenter)
        self.setFixedSize(280, 280)
        self._pix = None
        self._orig_size = None
        self._rect = None      # 原图坐标 QRect
        self._mode = None
        self._drag_off = None

    def set_image(self, img, keep_rect=False):
        self._orig_size = img.size
        self._pix = pil_to_pixmap(_fit_image(img, 240))
        self.setPixmap(self._pix)
        if not keep_rect:
            self._init_rect()

    def _init_rect(self):
        if not self._orig_size:
            return
        w, h = self._orig_size
        self._rect = QRect(0, 0, w, h)

    def clear(self):
        self._pix = None
        self._orig_size = None
        self._rect = None
        self.setPixmap(QPixmap())

    def _scale_off(self):
        pw, ph = self._pix.width(), self._pix.height()
        ox = (self.width() - pw) // 2
        oy = (self.height() - ph) // 2
        ow, oh = self._orig_size
        return pw / ow, ph / oh, ox, oy

    def _orig_to_ctrl(self, r):
        sx, sy, ox, oy = self._scale_off()
        return QRect(round(ox + r.left() * sx), round(oy + r.top() * sy),
                      round(r.width() * sx), round(r.height() * sy))

    def _ctrl_to_orig(self, pt):
        sx, sy, ox, oy = self._scale_off()
        return (pt.x() - ox) / sx, (pt.y() - oy) / sy

    def _hit(self, pt):
        rc = self._orig_to_ctrl(self._rect)
        H = 7
        left = abs(pt.x() - rc.left()) <= H
        right = abs(pt.x() - rc.right()) <= H
        top = abs(pt.y() - rc.top()) <= H
        bottom = abs(pt.y() - rc.bottom()) <= H
        if top and left:
            return "lt"
        if top and right:
            return "rt"
        if bottom and left:
            return "lb"
        if bottom and right:
            return "rb"
        if left:
            return "l"
        if right:
            return "r"
        if top:
            return "t"
        if bottom:
            return "b"
        if rc.contains(pt):
            return "move"
        return None

    def _set_shape(self, mode):
        shapes = {
            "lt": Qt.SizeFDiagCursor, "rb": Qt.SizeFDiagCursor,
            "rt": Qt.SizeBDiagCursor, "lb": Qt.SizeBDiagCursor,
            "l": Qt.SizeHorCursor, "r": Qt.SizeHorCursor,
            "t": Qt.SizeVerCursor, "b": Qt.SizeVerCursor,
            "move": Qt.SizeAllCursor,
        }
        self.setCursor(shapes.get(mode, Qt.ArrowCursor))

    def mousePressEvent(self, e):
        if not self._pix or not self._rect:
            return
        mode = self._hit(e.position().toPoint())
        if mode is None:
            return
        self._mode = mode
        r = self._rect
        # 按压瞬间锁定四条边的初始位置；缩放时对侧边始终取这里的锚点，绝不联动
        self._anchor = {"l": r.left(), "t": r.top(), "r": r.right(), "b": r.bottom()}
        x, y = self._ctrl_to_orig(e.position().toPoint())
        if mode == "move":
            self._drag_off = (x - r.left(), y - r.top())

    def mouseMoveEvent(self, e):
        if self._mode is None:
            if self._pix and self._rect:
                self._set_shape(self._hit(e.position().toPoint()))
            return
        x, y = self._ctrl_to_orig(e.position().toPoint())
        ow, oh = self._orig_size
        a = self._anchor
        if self._mode == "move":
            r = self._rect
            l = max(0, min(ow - r.width(), round(x - self._drag_off[0])))
            t = max(0, min(oh - r.height(), round(y - self._drag_off[1])))
            rr, b = l + r.width(), t + r.height()
        else:
            # 对侧边保持按压时的锚点位置，只有被拖动的边跟随鼠标
            l, t, rr, b = a["l"], a["t"], a["r"], a["b"]
            if "l" in self._mode:
                l = max(0, min(round(x), rr - self.MIN_SIDE))
            if "r" in self._mode:
                rr = min(ow, max(round(x), l + self.MIN_SIDE))
            if "t" in self._mode:
                t = max(0, min(round(y), b - self.MIN_SIDE))
            if "b" in self._mode:
                b = min(oh, max(round(y), t + self.MIN_SIDE))
        self._rect = QRect(l, t, rr - l, b - t)
        self.update()

    def mouseReleaseEvent(self, e):
        self._mode = None
        self.cropChanged.emit()

    def crop_rect_orig(self):
        if not self._rect:
            return None
        r = self._rect
        return (r.left(), r.top(), r.left() + r.width(), r.top() + r.height())

    def reset_rect(self):
        self._init_rect()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#F4F7FB"))
        s = 16
        for y in range(0, self.height(), s):
            for x in range(0, self.width(), s):
                if (x // s + y // s) % 2 == 0:
                    painter.fillRect(x, y, s, s, QColor("#E7EEF6"))
        super().paintEvent(event)
        if self._rect and self._pix:
            rc = self._orig_to_ctrl(self._rect)
            dim = QColor(40, 55, 80, 60)
            painter.fillRect(0, 0, self.width(), rc.top(), dim)
            painter.fillRect(0, rc.bottom(), self.width(), self.height() - rc.bottom(), dim)
            painter.fillRect(0, rc.top(), rc.left(), rc.height(), dim)
            painter.fillRect(rc.right(), rc.top(), self.width() - rc.right(), rc.height(), dim)
            painter.setPen(QPen(QColor("#5B8DEF"), 2))
            painter.drawRect(rc)
            # 八个手柄
            painter.setBrush(QColor("#5B8DEF"))
            painter.setPen(QPen(QColor("#FFFFFF"), 1))
            pts = [rc.topLeft(), rc.topRight(), rc.bottomLeft(), rc.bottomRight(),
                   QPoint(rc.center().x(), rc.top()), QPoint(rc.center().x(), rc.bottom()),
                   QPoint(rc.left(), rc.center().y()), QPoint(rc.right(), rc.center().y())]
            for p in pts:
                painter.drawRect(p.x() - 3, p.y() - 3, 6, 6)


class DropZone(QFrame):
    fileDropped = Signal(str)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setObjectName("dropzone")
        self.setFixedHeight(120)
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignCenter)
        self.icon = QLabel("⤓")
        self.icon.setAlignment(Qt.AlignCenter)
        self.icon.setStyleSheet("font-size:30px; color:#5B8DEF;")
        self.text = QLabel("拖入图片 / GIF，或点击选择文件")
        self.text.setAlignment(Qt.AlignCenter)
        self.text.setObjectName("dropText")
        lay.addWidget(self.icon)
        lay.addWidget(self.text)

    def mousePressEvent(self, e):
        path, _ = QFileDialog.getOpenFileName(self, "选择光标素材", "", SUPPORTED)
        if path:
            self.fileDropped.emit(path)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self.setProperty("hover", True)
            self.style().polish(self)

    def dragLeaveEvent(self, e):
        self.setProperty("hover", False)
        self.style().polish(self)

    def dropEvent(self, e):
        self.setProperty("hover", False)
        self.style().polish(self)
        url = e.mimeData().urls()[0].toLocalFile()
        if url:
            self.fileDropped.emit(url)


class HistoryItem(QWidget):
    applyRequested = Signal(str)
    deleteRequested = Signal(str)
    checkToggled = Signal(str, bool)

    def __init__(self, item, parent=None):
        super().__init__(parent)
        self.item_id = item["id"]
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 6, 8, 6)
        row.setSpacing(10)

        self.check = QCheckBox()
        self.check.toggled.connect(lambda v: self.checkToggled.emit(self.item_id, v))

        self.thumb = QLabel()
        self.thumb.setFixedSize(52, 52)
        self.thumb.setAlignment(Qt.AlignCenter)
        self.thumb.setObjectName("thumbBox")
        if os.path.exists(item.get("thumb", "")):
            self.thumb.setPixmap(QPixmap(item["thumb"]))

        info = QVBoxLayout()
        info.setSpacing(2)
        name = QLabel(item["source"])
        name.setObjectName("histName")
        meta = QLabel(f"{'动态' if item.get('mode') == 'dynamic' else '静态'} · {item.get('time', '')}")
        meta.setObjectName("histMeta")
        info.addWidget(name)
        info.addWidget(meta)

        self.btn_apply = QPushButton("设为此")
        self.btn_apply.setObjectName("miniBtn")
        self.btn_apply.clicked.connect(lambda: self.applyRequested.emit(self.item_id))
        self.btn_del = QPushButton("删除")
        self.btn_del.setObjectName("miniGhost")
        self.btn_del.clicked.connect(lambda: self.deleteRequested.emit(self.item_id))

        row.addWidget(self.check)
        row.addWidget(self.thumb)
        row.addLayout(info, 1)
        row.addWidget(self.btn_apply)
        row.addWidget(self.btn_del)


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.frames = []
        self.original_frames = []
        self.durations = []
        self.static_index = 0
        self.current_path = None
        self.checked_ids = set()

        self.setWindowTitle("鼠标光标设置器")
        self.resize(940, 760)
        self._build_ui()
        self._apply_style()
        self._reload_history()
        self._load_current_preview()

    # ------------------------------------------------------------ UI
    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 22)
        root.setSpacing(20)

        # ---------------- 左：主操作区
        left = QVBoxLayout()
        left.setSpacing(16)

        head = QHBoxLayout()
        badge = QLabel("◈")
        badge.setFixedSize(40, 40)
        badge.setAlignment(Qt.AlignCenter)
        badge.setObjectName("badge")
        title = QLabel("鼠标光标设置器")
        title.setObjectName("title")
        head.addWidget(badge)
        head.addSpacing(10)
        head.addWidget(title)
        head.addStretch()
        left.addLayout(head)

        card = QFrame()
        card.setObjectName("card")
        _shadow(card)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(20, 20, 20, 20)
        cl.setSpacing(16)

        self.dropzone = DropZone()
        self.dropzone.fileDropped.connect(self.load_file)
        cl.addWidget(self.dropzone)

        body = QHBoxLayout()
        body.setSpacing(16)

        self.preview = CropPreview()
        body.addWidget(self.preview)

        right = QVBoxLayout()
        right.setSpacing(12)

        mode_label = QLabel("播放模式")
        mode_label.setObjectName("sectionLabel")
        right.addWidget(mode_label)

        self.rb_dynamic = QCheckBox("动态（完整动图）")
        self.rb_static = QCheckBox("静态（指定一帧）")
        self.rb_dynamic.setChecked(True)
        self.rb_dynamic.toggled.connect(lambda v: self._on_check_mode("dynamic", v))
        self.rb_static.toggled.connect(lambda v: self._on_check_mode("static", v))
        right.addWidget(self.rb_dynamic)
        right.addWidget(self.rb_static)

        self.frame_row = QWidget()
        fr = QHBoxLayout(self.frame_row)
        fr.setContentsMargins(0, 0, 0, 0)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.valueChanged.connect(self._on_slider)
        self.frame_label = QLabel("帧 1 / 1")
        self.frame_label.setObjectName("frameLabel")
        fr.addWidget(self.slider, 1)
        fr.addWidget(self.frame_label)
        right.addWidget(self.frame_row)

        # 裁剪操作
        crop_row = QHBoxLayout()
        self.btn_crop = QPushButton("应用裁剪")
        self.btn_crop.setObjectName("miniBtn")
        self.btn_crop.clicked.connect(self.apply_crop)
        self.btn_crop_reset = QPushButton("重置裁剪")
        self.btn_crop_reset.setObjectName("miniGhost")
        self.btn_crop_reset.clicked.connect(self.reset_crop)
        crop_row.addWidget(self.btn_crop)
        crop_row.addWidget(self.btn_crop_reset)
        right.addLayout(crop_row)

        right.addStretch()
        self.info = QLabel("尚未选择素材")
        self.info.setObjectName("info")
        self.info.setWordWrap(True)
        right.addWidget(self.info)

        body.addLayout(right, 1)
        cl.addLayout(body)

        # 帧缩略条
        self.thumbs = QHBoxLayout()
        self.thumbs.setSpacing(8)
        thumb_wrap = QScrollArea()
        thumb_wrap.setWidgetResizable(True)
        thumb_wrap.setFixedHeight(72)
        inner = QWidget()
        inner.setLayout(self.thumbs)
        thumb_wrap.setWidget(inner)
        cl.addWidget(thumb_wrap)

        btns = QHBoxLayout()
        self.btn_apply = QPushButton("设置鼠标")
        self.btn_apply.setObjectName("primaryBtn")
        self.btn_apply.setFixedHeight(44)
        self.btn_apply.clicked.connect(self.apply_cursor)
        self.btn_restore = QPushButton("恢复默认光标")
        self.btn_restore.setObjectName("ghostBtn")
        self.btn_restore.setFixedHeight(44)
        self.btn_restore.clicked.connect(self.restore)
        btns.addWidget(self.btn_apply, 2)
        btns.addWidget(self.btn_restore, 1)
        cl.addLayout(btns)

        left.addWidget(card)
        root.addLayout(left, 3)

        # ---------------- 右：当前样式 + 历史
        side = QVBoxLayout()
        side.setSpacing(16)

        cur_card = QFrame()
        cur_card.setObjectName("sideCard")
        _shadow(cur_card, blur=14, dy=3)
        ccl = QVBoxLayout(cur_card)
        ccl.setContentsMargins(16, 16, 16, 16)
        ccl.setSpacing(10)
        cur_title = QLabel("当前样式")
        cur_title.setObjectName("sectionLabel")
        cur_row = QHBoxLayout()
        self.cur_preview = QLabel()
        self.cur_preview.setFixedSize(72, 72)
        self.cur_preview.setAlignment(Qt.AlignCenter)
        self.cur_preview.setObjectName("thumbBox")
        self.cur_name = QLabel("系统默认")
        self.cur_name.setObjectName("histMeta")
        self.cur_name.setWordWrap(True)
        cur_row.addWidget(self.cur_preview)
        cur_row.addWidget(self.cur_name, 1)
        ccl.addWidget(cur_title)
        ccl.addLayout(cur_row)
        side.addWidget(cur_card)

        hist_card = QFrame()
        hist_card.setObjectName("sideCard")
        _shadow(hist_card, blur=14, dy=3)
        hcl = QVBoxLayout(hist_card)
        hcl.setContentsMargins(16, 16, 16, 16)
        hcl.setSpacing(10)

        hist_head = QHBoxLayout()
        hist_title = QLabel("历史样式")
        hist_title.setObjectName("sectionLabel")
        self.check_all = QCheckBox("全选")
        self.check_all.toggled.connect(self._toggle_all)
        self.btn_del_sel = QPushButton("批量删除")
        self.btn_del_sel.setObjectName("miniGhost")
        self.btn_del_sel.clicked.connect(self.delete_selected)
        hist_head.addWidget(hist_title)
        hist_head.addStretch()
        hist_head.addWidget(self.check_all)
        hist_head.addWidget(self.btn_del_sel)
        hcl.addLayout(hist_head)

        self.hist_scroll = QScrollArea()
        self.hist_scroll.setWidgetResizable(True)
        self.hist_inner = QWidget()
        self.hist_layout = QVBoxLayout(self.hist_inner)
        self.hist_layout.setSpacing(6)
        self.hist_layout.setContentsMargins(0, 0, 0, 0)
        self.hist_layout.addStretch()
        self.hist_scroll.setWidget(self.hist_inner)
        hcl.addWidget(self.hist_scroll)

        side.addWidget(hist_card, 1)
        root.addLayout(side, 2)

        self.status = QLabel("")
        self.status.setObjectName("status")
        left.addWidget(self.status)

        self._set_mode_enabled(False)

    def _apply_style(self):
        self.setStyleSheet("""
            QWidget { background:#EDF2F8; color:#2B3445; font-family:"Microsoft YaHei"; }
            QLabel { background:transparent; }
            #title { font-size:20px; font-weight:700; letter-spacing:1px; }
            #badge { background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #5B8DEF,stop:1 #7C6FF0);
                     color:white; border-radius:4px; font-size:20px; }
            #card, #sideCard { background:#FFFFFF; border:1px solid #E2EAF3; border-radius:4px; }
            #dropzone { border:2px dashed #B9CBE6; border-radius:4px; background:transparent; }
            #dropzone[hover="true"] { border:2px dashed #5B8DEF; background:#F2F7FF; }
            #dropText { color:#6B7686; font-size:13px; }
            #sectionLabel { font-size:13px; font-weight:700; color:#4A5568; }
            QCheckBox, QRadioButton { background:transparent; font-size:13px; spacing:8px; }
            QCheckBox:disabled, QRadioButton:disabled { color:#A9B4C4; }
            #frameLabel { color:#6B7686; font-size:12px; min-width:64px; }
            #info { color:#6B7686; font-size:12px; }
            #status { font-size:13px; padding-left:2px; }
            #primaryBtn { background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #5B8DEF,stop:1 #7C6FF0);
                          color:white; border:none; border-radius:3px; font-size:15px; font-weight:700; }
            #primaryBtn:hover { background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #4A7DE0,stop:1 #6A5FDD); }
            #ghostBtn { background:#FFFFFF; color:#5B6B82; border:1px solid #C9D6E6;
                        border-radius:2px; font-size:14px; font-weight:600; }
            #ghostBtn:hover { border:1px solid #5B8DEF; color:#5B8DEF; }
            #miniBtn { background:#5B8DEF; color:white; border:none; border-radius:2px;
                       font-size:12px; padding:5px 10px; }
            #miniBtn:hover { background:#4A7DE0; }
            #miniGhost { background:#FFFFFF; color:#5B6B82; border:1px solid #C9D6E6;
                         border-radius:2px; font-size:12px; padding:5px 10px; }
            #miniGhost:hover { border:1px solid #D9534F; color:#D9534F; }
            #thumbBox { border:1px solid #DCE5F0; border-radius:2px; background:#F4F7FB; }
            #histName { font-size:13px; color:#2B3445; }
            #histMeta { font-size:11px; color:#8A97A8; }
            QSlider::groove:horizontal { height:6px; background:#E4ECF6; border-radius:3px; }
            QSlider::handle:horizontal { width:16px; height:16px; background:#5B8DEF; border-radius:8px; margin:-5px 0; }
            QScrollArea { border:none; background:transparent; }
        """)

    # ------------------------------------------------------------ 素材载入
    def load_file(self, path):
        self.current_path = path
        ext = os.path.splitext(path)[1].lower()
        if ext in core.VIDEO_EXTS:
            self._set_status("暂不支持视频，请先将视频转为 GIF 后再导入", "err")
            return
        try:
            loaded = core.load_frames(path)
            self.original_frames = [img.copy() for img, _ in loaded]
            self.frames = [img for img, _ in loaded]
            self.durations = [dur for _, dur in loaded]
            self.static_index = 0
            self.slider.setRange(0, len(self.frames) - 1)
            self.slider.setValue(0)
            self._build_thumbs()

            multi = len(self.frames) > 1
            self._set_mode_enabled(multi)
            if multi:
                self.rb_dynamic.setChecked(True)
            else:
                self.rb_static.setChecked(True)
            self._on_mode_changed()
            self.info.setText(f"已载入：{os.path.basename(path)}\n共 {len(self.frames)} 帧")
            self._set_status("素材就绪，可裁剪或直接设置", "ok")
        except Exception as ex:
            self._set_status(f"载入失败：{ex}", "err")

    def _set_mode_enabled(self, enabled):
        self.rb_dynamic.setEnabled(enabled)
        self.rb_static.setEnabled(enabled)

    def _build_thumbs(self):
        while self.thumbs.count():
            w = self.thumbs.takeAt(0).widget()
            if w:
                w.deleteLater()
        for i, img in enumerate(self.frames):
            lbl = QLabel()
            lbl.setFixedSize(56, 56)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setObjectName("thumbBox")
            lbl.setPixmap(pil_to_pixmap(core.normalize(img, 64)))
            lbl.mousePressEvent = lambda e, idx=i: self._thumb_click(idx)
            self.thumbs.addWidget(lbl)

    def _thumb_click(self, idx):
        if not self.rb_static.isEnabled():
            return
        self.static_index = idx
        self.slider.setValue(idx)
        self.rb_static.setChecked(True)
        self._refresh_preview()

    def _on_check_mode(self, which, checked):
        if which == "dynamic":
            if checked:
                self.rb_static.setChecked(False)
            elif not self.rb_static.isChecked():
                self.rb_dynamic.blockSignals(True)
                self.rb_dynamic.setChecked(True)
                self.rb_dynamic.blockSignals(False)
        else:
            if checked:
                self.rb_dynamic.setChecked(False)
            elif not self.rb_dynamic.isChecked():
                self.rb_static.blockSignals(True)
                self.rb_static.setChecked(True)
                self.rb_static.blockSignals(False)
        self._on_mode_changed()

    def _on_mode_changed(self):
        self.frame_row.setVisible(self.rb_static.isChecked())
        self._refresh_preview()

    def _on_slider(self, v):
        self.static_index = v
        self.frame_label.setText(f"帧 {v + 1} / {len(self.frames)}")
        self._refresh_preview()

    def _refresh_preview(self):
        if not self.frames:
            self.preview.clear()
            return
        if self.rb_static.isChecked():
            idx = min(self.static_index, len(self.frames) - 1)
            self.preview.set_image(self.frames[idx])
        else:
            self.preview.set_image(self.frames[0])

    # ------------------------------------------------------------ 裁剪
    def apply_crop(self):
        if not self.frames:
            return
        rect = self.preview.crop_rect_orig()
        if not rect:
            self._set_status("暂无可用裁剪框", "err")
            return
        self.frames = [core.crop_image(f, rect) for f in self.original_frames]
        self._build_thumbs()
        self._refresh_preview()
        self._set_status("已按框选区域裁剪", "ok")

    def reset_crop(self):
        if not self.original_frames:
            return
        self.frames = [f.copy() for f in self.original_frames]
        self.static_index = 0
        self.slider.setValue(0)
        self._build_thumbs()
        self.preview.reset_rect()
        self._refresh_preview()
        self._set_status("已重置为原始素材", "ok")

    # ------------------------------------------------------------ 应用 / 恢复
    def apply_cursor(self):
        if not self.frames:
            self._set_status("请先拖入或选择素材", "err")
            return
        try:
            if self.rb_static.isChecked() or not self.rb_static.isEnabled():
                img = self.frames[self.static_index]
                out = core.save_static_cur(img, core.active_cursor_path(128, ".cur"))
                mode = "static"
                mode_text = "静态"
                thumb = img
            else:
                out = core.frames_to_ani(self.frames, self.durations, core.active_cursor_path(128, ".ani"))
                mode = "dynamic"
                mode_text = f"动态（{len(self.frames)} 帧）"
                thumb = self.frames[0]
            core.apply_cursor(out)
            source_name = os.path.basename(self.current_path) if self.current_path else "未命名"
            core.add_history(out, source_name, mode, thumb)
            core.save_current_meta(source_name, mode, thumb)
            self._reload_history()
            self._set_current(thumb, source_name)
            self._set_status(f"已应用为{mode_text}光标，移动鼠标查看效果", "ok")
        except Exception as ex:
            self._set_status(f"设置失败：{ex}", "err")

    def restore(self):
        try:
            core.restore_default()
            core.clear_current_meta()
            self._load_current_preview()
            self._set_status("已恢复系统默认光标", "ok")
        except Exception as ex:
            self._set_status(f"恢复失败：{ex}", "err")

    # ------------------------------------------------------------ 当前样式
    def _set_current(self, img, name):
        self.cur_preview.setPixmap(pil_to_pixmap(core.normalize(img, 64)))
        self.cur_preview.setText("")
        self.cur_name.setText(name)

    def _load_current_preview(self):
        meta = core.load_current_meta()
        if meta and core.current_custom():
            if meta.get("thumb") and os.path.exists(meta["thumb"]):
                self.cur_preview.setPixmap(QPixmap(meta["thumb"]))
                self.cur_preview.setText("")
                self.cur_name.setText(meta.get("source", "自定义光标"))
                return
            p = core.current_arrow_path()
            if p and os.path.exists(p):
                icon = QIcon(p)
                if not icon.isNull():
                    pm = icon.pixmap(72, 72)
                    if not pm.isNull():
                        self.cur_preview.setPixmap(pm)
                        self.cur_preview.setText("")
                        self.cur_name.setText(meta.get("source", "自定义光标"))
                        return
        self.cur_preview.setPixmap(QPixmap())
        self.cur_preview.setText("➤")
        self.cur_preview.setStyleSheet("font-size:30px; color:#A9B4C4;")
        self.cur_name.setText("系统默认")

    # ------------------------------------------------------------ 历史
    def _reload_history(self):
        while self.hist_layout.count():
            item = self.hist_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self.checked_ids.clear()
        self.check_all.blockSignals(True)
        self.check_all.setChecked(False)
        self.check_all.blockSignals(False)

        items = core.list_history()
        if not items:
            empty = QLabel("暂无历史样式")
            empty.setObjectName("histMeta")
            self.hist_layout.addWidget(empty)
            self.hist_layout.addStretch()
            return

        for it in items:
            hi = HistoryItem(it)
            hi.applyRequested.connect(self.apply_history)
            hi.deleteRequested.connect(self.delete_one)
            hi.checkToggled.connect(self._on_check)
            self.hist_layout.addWidget(hi)
        self.hist_layout.addStretch()

    def _on_check(self, hid, checked):
        if checked:
            self.checked_ids.add(hid)
        else:
            self.checked_ids.discard(hid)

    def _toggle_all(self, checked):
        for i in range(self.hist_layout.count()):
            w = self.hist_layout.itemAt(i).widget()
            if isinstance(w, HistoryItem):
                w.check.blockSignals(True)
                w.check.setChecked(checked)
                w.check.blockSignals(False)
                if checked:
                    self.checked_ids.add(w.item_id)
                else:
                    self.checked_ids.discard(w.item_id)

    def apply_history(self, hid):
        try:
            path, _ = core.history_to_current(hid)
            core.apply_cursor(path)
            for it in core.list_history():
                if it.get("id") == hid:
                    core.save_current_meta(it.get("source", "历史样式"), it.get("mode"),
                                           thumb_path=it.get("thumb"))
                    if os.path.exists(it.get("thumb", "")):
                        self.cur_preview.setPixmap(QPixmap(it["thumb"]))
                        self.cur_preview.setText("")
                    self.cur_name.setText(it.get("source", "历史样式"))
                    break
            self._set_status("已应用所选历史样式", "ok")
        except Exception as ex:
            self._set_status(f"应用失败：{ex}", "err")

    def delete_one(self, hid):
        core.delete_history([hid])
        self.checked_ids.discard(hid)
        self._reload_history()
        self._set_status("已删除该历史样式", "ok")

    def delete_selected(self):
        if not self.checked_ids:
            self._set_status("请先勾选要删除的样式", "err")
            return
        core.delete_history(list(self.checked_ids))
        self._reload_history()
        self._set_status("已批量删除所选样式", "ok")

    # ------------------------------------------------------------ 状态
    def _set_status(self, text, kind):
        self.status.setText(text)
        color = "#2FA36B" if kind == "ok" else "#D9534F"
        self.status.setStyleSheet(f"color:{color}; font-size:13px; background:transparent;")


def _resource(name):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def main():
    app = QApplication(sys.argv)
    app.setFont(QFont("Microsoft YaHei", 10))
    icon_path = _resource("app.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
