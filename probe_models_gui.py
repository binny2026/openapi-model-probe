"""探测当前 API 凭证可访问的模型列表（PySide6 跨平台 GUI 版）。

功能：
- 管理多个 API 配置（名称 + Base URL + API Key），API Key 加密存储到本地 SQLite
- 左栏 API 配置列表，右栏模型列表
- 配置行内探测，右键复制 / 查看编辑 / 删除
- 纯 PySide6 内置控件 + 自定义 QSS 深色主题

本文件自包含核心探测逻辑，不依赖、也不改动 probe_models.py。
"""

import os
import shutil
import sqlite3
import sys
from pathlib import Path

from cryptography.fernet import Fernet
from openai import OpenAI
from PySide6.QtCore import QSize, QStandardPaths, QThread, Qt, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

# 脚本目录（用于定位源码资源，如 icon.png）
SCRIPT_DIR = Path(__file__).resolve().parent
ICON_PATH = SCRIPT_DIR / "icon.png"
APP_NAME = "ai-model-prober"
APP_DISPLAY_NAME = "AI 模型探测工具"
CONFIG_ROW_HEIGHT = 44


def _data_dir():
    """返回跨平台用户数据目录，并迁移旧版脚本目录下的数据。"""
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    data_dir = Path(base)
    data_dir.mkdir(parents=True, exist_ok=True)

    # 迁移旧版数据（脚本目录 → 用户数据目录）
    for name in ("probe_models.db", "probe_models.key"):
        legacy = SCRIPT_DIR / name
        target = data_dir / name
        if legacy.exists() and not target.exists():
            shutil.copy2(legacy, target)
    return data_dir


def _db_path():
    return _data_dir() / "probe_models.db"


def _key_path():
    return _data_dir() / "probe_models.key"

# 全局现代化深色主题样式（纯 QSS，无第三方依赖）
STYLE_SHEET = """
* {
    font-family: "PingFang SC", "Microsoft YaHei", "Segoe UI", sans-serif;
    font-size: 13px;
}

QMainWindow, QWidget {
    background-color: #1e1f24;
    color: #e8e8ea;
}

QFrame#card {
    background-color: #26272d;
    border: 1px solid #34353c;
    border-radius: 10px;
}

QLabel#cardTitle {
    font-size: 15px;
    font-weight: 600;
    color: #e8e8ea;
}

QPushButton {
    background-color: #2e3038;
    color: #e8e8ea;
    border: 1px solid #3c3e47;
    border-radius: 6px;
    padding: 5px 14px;
}

QPushButton:hover {
    background-color: #373943;
    border-color: #4a4c57;
}

QPushButton:pressed {
    background-color: #26282f;
}

QPushButton:disabled {
    background-color: #26272d;
    color: #6b6c73;
    border-color: #2f3038;
}

QPushButton#primaryButton {
    background-color: #4f8cff;
    color: #ffffff;
    border: none;
}

QPushButton#primaryButton:hover {
    background-color: #6a9dff;
}

QPushButton#primaryButton:pressed {
    background-color: #3f79e6;
}

QPushButton#primaryButton:disabled {
    background-color: #3a4a63;
    color: #8a93a8;
}

QPushButton#rowProbeBtn {
    background-color: #4f8cff;
    color: #ffffff;
    border: none;
    border-radius: 4px;
    padding: 2px 10px;
}

QPushButton#rowProbeBtn:hover {
    background-color: #6a9dff;
}

QPushButton#copyButton {
    background-color: #3a4a63;
    color: #ffffff;
    border: none;
    border-radius: 4px;
    padding: 3px 8px;
}

QPushButton#copyButton:hover {
    background-color: #4f8cff;
}

QLineEdit {
    background-color: #1b1c21;
    color: #e8e8ea;
    border: 1px solid #3c3e47;
    border-radius: 6px;
    padding: 6px 10px;
    selection-background-color: #4f8cff;
}

QLineEdit:focus {
    border-color: #4f8cff;
}

QListWidget {
    background-color: #1b1c21;
    border: 1px solid #34353c;
    border-radius: 6px;
    outline: none;
}

QListWidget::item {
    color: #d4d5da;
}

QListWidget::item:hover {
    background-color: #2e3038;
}

QListWidget::item:selected {
    background-color: #3a4a63;
    color: #ffffff;
}

QListWidget QWidget {
    background: transparent;
}

QTableWidget {
    background-color: #1b1c21;
    border: 1px solid #34353c;
    border-radius: 6px;
    gridline-color: #2e3038;
    alternate-background-color: #222329;
}

QHeaderView::section {
    background-color: #2e3038;
    color: #b9bac2;
    border: none;
    border-right: 1px solid #34353c;
    border-bottom: 1px solid #34353c;
    padding: 6px 8px;
    font-weight: 600;
}

QTableWidget::item {
    padding: 6px 8px;
}

QTableWidget::item:selected {
    background-color: #3a4a63;
    color: #ffffff;
}

QMenu {
    background-color: #26272d;
    border: 1px solid #34353c;
    border-radius: 6px;
    padding: 4px;
}

QMenu::item {
    padding: 6px 20px;
    border-radius: 4px;
}

QMenu::item:selected {
    background-color: #4f8cff;
    color: #ffffff;
}

QMenu::separator {
    height: 1px;
    background: #34353c;
    margin: 4px 8px;
}

QDialog, QMessageBox {
    background-color: #26272d;
}

QStatusBar {
    background-color: #26272d;
    color: #9a9ba0;
    border-top: 1px solid #34353c;
}

QProgressBar#loadingBar {
    background-color: #2e3038;
    border: none;
    border-radius: 2px;
}

QProgressBar#loadingBar::chunk {
    background-color: #4f8cff;
    border-radius: 2px;
}

QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 0;
}

QScrollBar::handle:vertical {
    background: #3c3e47;
    border-radius: 5px;
    min-height: 30px;
}

QScrollBar::handle:vertical:hover {
    background: #4a4c57;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}

QScrollBar:horizontal {
    background: transparent;
    height: 10px;
    margin: 0;
}

QScrollBar::handle:horizontal {
    background: #3c3e47;
    border-radius: 5px;
    min-width: 30px;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
}
"""


def show_message_box(title, content, parent):
    """单按钮（确定）警告消息框。"""
    QMessageBox.warning(parent, title, content)


def confirm_message_box(title, content, parent):
    """确定 / 取消 二选一消息框，返回是否确定。"""
    ret = QMessageBox.question(
        parent,
        title,
        content,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
    )
    return ret == QMessageBox.StandardButton.Yes


def _make_eye_icon(revealed):
    """生成小眼睛图标：revealed=True 表示密钥已明文显示（画斜线），否则睁眼。"""
    pm = QPixmap(18, 18)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor("#9a9ba0"))
    pen.setWidthF(1.6)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(2, 5, 14, 7)
    if revealed:
        painter.drawLine(1, 16, 16, 1)
    else:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#9a9ba0"))
        painter.drawEllipse(7, 7, 3, 3)
    painter.end()
    return QIcon(pm)


def _load_or_create_key():
    """加载本机密钥；不存在则生成并写入 0600 权限的密钥文件。"""
    key_path = _key_path()
    if key_path.exists():
        return key_path.read_bytes().strip()
    key = Fernet.generate_key()
    key_path.write_bytes(key)
    try:
        os.chmod(key_path, 0o600)
    except OSError:
        pass  # 某些平台不支持 chmod，忽略即可
    return key


def _connect():
    return sqlite3.connect(_db_path())


def _init_db():
    """初始化 SQLite，确保 api_config 表存在并补齐历史版本缺的列。"""
    conn = _connect()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS api_config (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL DEFAULT '',
                base_url TEXT NOT NULL DEFAULT '',
                api_key_encrypted TEXT NOT NULL DEFAULT '',
                create_time TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                update_time TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            )
            """
        )
        cols = [row[1] for row in conn.execute("PRAGMA table_info(api_config)").fetchall()]
        if "name" not in cols:
            conn.execute("ALTER TABLE api_config ADD COLUMN name TEXT NOT NULL DEFAULT ''")
        conn.commit()
    finally:
        conn.close()


def _encrypt(api_key):
    return Fernet(_load_or_create_key()).encrypt(api_key.encode("utf-8")).decode("utf-8")


def _decrypt(token):
    try:
        return Fernet(_load_or_create_key()).decrypt(token.encode("utf-8")).decode("utf-8")
    except Exception:
        return ""


def list_configs():
    """返回配置列表 [{id, name, base_url}]（不解密 api_key）。"""
    _init_db()
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT id, name, base_url FROM api_config ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    return [{"id": r[0], "name": r[1], "base_url": r[2]} for r in rows]


def get_api_key(config_id):
    """按 id 返回解密后的 api_key；不存在返回空串。"""
    _init_db()
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT api_key_encrypted FROM api_config WHERE id = ?", (config_id,)
        ).fetchone()
    finally:
        conn.close()
    return _decrypt(row[0]) if row else ""


def add_config(name, base_url, api_key):
    _init_db()
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO api_config (name, base_url, api_key_encrypted) VALUES (?, ?, ?)",
            (name, base_url, _encrypt(api_key)),
        )
        conn.commit()
    finally:
        conn.close()


def update_config(config_id, name, base_url, api_key):
    _init_db()
    conn = _connect()
    try:
        conn.execute(
            """
            UPDATE api_config
            SET name = ?, base_url = ?, api_key_encrypted = ?,
                update_time = datetime('now', 'localtime')
            WHERE id = ?
            """,
            (name, base_url, _encrypt(api_key), config_id),
        )
        conn.commit()
    finally:
        conn.close()


def delete_config(config_id):
    _init_db()
    conn = _connect()
    try:
        conn.execute("DELETE FROM api_config WHERE id = ?", (config_id,))
        conn.commit()
    finally:
        conn.close()


class ModelProbeWorker(QThread):
    """后台线程执行模型探测，避免网络请求阻塞 UI。"""

    models_ready = Signal(list)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, base_url, api_key, parent=None):
        super().__init__(parent)
        self.base_url = base_url
        self.api_key = api_key

    def run(self):
        client_options = {
            "api_key": self.api_key,
            "timeout": 10.0,
            "max_retries": 0,
        }
        if self.base_url:
            client_options["base_url"] = self.base_url

        try:
            client = OpenAI(**client_options)
            if self.isInterruptionRequested():
                self.cancelled.emit()
                return
            models = list(client.models.list().data)
        except Exception as exc:
            if self.isInterruptionRequested():
                self.cancelled.emit()
            else:
                self.failed.emit(str(exc))
            return

        if self.isInterruptionRequested():
            self.cancelled.emit()
            return

        models.sort(key=lambda model: model.id)
        self.models_ready.emit(models)


class ConfigDialog(QDialog):
    """新增 / 编辑 API 配置的对话框。"""

    def __init__(self, parent=None, name="", base_url="", api_key=""):
        super().__init__(parent)
        self.setWindowTitle("API 配置")
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self.name_edit = QLineEdit(name)
        self.name_edit.setMinimumHeight(36)
        self.name_edit.setPlaceholderText("例如：OpenAI / 本地 Ollama")

        self.base_url_edit = QLineEdit(base_url)
        self.base_url_edit.setMinimumHeight(36)
        self.base_url_edit.setPlaceholderText("留空使用默认 https://api.openai.com/v1")

        self.api_key_edit = QLineEdit(api_key)
        self.api_key_edit.setMinimumHeight(36)
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText("sk-...")
        self._key_revealed = False
        self._eye_action = self.api_key_edit.addAction(
            _make_eye_icon(False), QLineEdit.ActionPosition.TrailingPosition
        )
        self._eye_action.triggered.connect(self._toggle_key_visibility)

        form.addRow("名称", self.name_edit)
        form.addRow("Base URL", self.base_url_edit)
        form.addRow("API Key", self.api_key_edit)
        layout.addLayout(form)

        btn_row = QHBoxLayout()
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("保存")
        save_btn.setObjectName("primaryButton")
        save_btn.clicked.connect(self._on_accept)
        btn_row.addStretch(1)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

    def _toggle_key_visibility(self):
        self._key_revealed = not self._key_revealed
        self.api_key_edit.setEchoMode(
            QLineEdit.EchoMode.Normal if self._key_revealed else QLineEdit.EchoMode.Password
        )
        self._eye_action.setIcon(_make_eye_icon(self._key_revealed))

    def _on_accept(self):
        if not self.name_edit.text().strip():
            show_message_box("缺少名称", "请填写配置名称。", self)
            return
        if not self.api_key_edit.text().strip():
            show_message_box("缺少 API Key", "请填写 API Key。", self)
            return
        self.accept()

    def values(self):
        return (
            self.name_edit.text().strip(),
            self.base_url_edit.text().strip(),
            self.api_key_edit.text().strip(),
        )


class ElideLabel(QLabel):
    """根据自身宽度自动省略文本（尾部加省略号）的标签。"""

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self._full_text = text
        super().setText(text)
        self.setMinimumWidth(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide()

    def _elide(self):
        metrics = self.fontMetrics()
        elided = metrics.elidedText(
            self._full_text, Qt.TextElideMode.ElideRight, self.width()
        )
        if self.text() != elided:
            super().setText(elided)


class ConfigRowWidget(QWidget):
    """API 配置列表单行控件：名称（固定 25%）+ base_url + 探测按钮。"""

    def __init__(self, name, base_url, on_probe, parent=None):
        super().__init__(parent)
        self.setFixedHeight(CONFIG_ROW_HEIGHT)
        self.full_name = name
        self._on_probe = on_probe

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(8)

        self.name_label = QLabel()
        self.url_label = ElideLabel(base_url)

        # 名字与 URL 共用父容器，选中时背景色不会穿透到按钮
        text_container = QWidget()
        text_layout = QHBoxLayout(text_container)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(8)
        text_layout.addWidget(self.name_label, 0)
        text_layout.addWidget(self.url_label, 1)

        self.probe_btn = QPushButton("探测")
        self.probe_btn.setObjectName("rowProbeBtn")
        self.probe_btn.setFixedHeight(28)
        self.probe_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.probe_btn.clicked.connect(on_probe)

        layout.addWidget(text_container, 1)
        layout.addWidget(self.probe_btn, 0)

    def set_name_width(self, width):
        metrics = self.name_label.fontMetrics()
        self.name_label.setText(
            metrics.elidedText(self.full_name, Qt.TextElideMode.ElideRight, width)
        )
        self.name_label.setFixedWidth(width)

    def mouseDoubleClickEvent(self, event):
        # 双击按钮区域交给按钮处理，双击其他区域触发探测
        if not self.probe_btn.geometry().contains(event.position().toPoint()):
            self._on_probe()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)


class ConfigListWidget(QListWidget):
    """名称列宽固定为列表宽度的 25%。"""

    NAME_RATIO = 0.25

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_name_widths()

    def update_name_widths(self):
        width = int(self.viewport().width() * self.NAME_RATIO)
        for i in range(self.count()):
            widget = self.itemWidget(self.item(i))
            if isinstance(widget, ConfigRowWidget):
                widget.set_name_width(width)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AI 模型探测工具")
        self.setMinimumSize(860, 500)
        self.resize(1000, 580)

        self.worker = None
        self.configs = []
        self._copy_btn = None
        self._copy_btn_row = -1
        self._build_ui()
        self._reload_configs()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # 左右分栏（左栏固定宽度）
        body = QHBoxLayout()
        body.setSpacing(12)

        # 左栏：API 配置卡片
        left_card = QFrame()
        left_card.setObjectName("card")
        left_card.setFixedWidth(380)
        left_layout = QVBoxLayout(left_card)
        left_layout.setContentsMargins(16, 16, 16, 16)
        left_layout.setSpacing(12)

        left_header = QHBoxLayout()
        left_title = QLabel("API 配置")
        left_title.setObjectName("cardTitle")
        left_header.addWidget(left_title)
        left_header.addStretch(1)
        add_btn = QPushButton("新增")
        add_btn.setObjectName("primaryButton")
        add_btn.clicked.connect(self._on_add)
        left_header.addWidget(add_btn)
        left_layout.addLayout(left_header)

        self.api_list = ConfigListWidget()
        self.api_list.setSpacing(8)
        self.api_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.api_list.customContextMenuRequested.connect(self._on_api_list_menu)
        left_layout.addWidget(self.api_list, 1)

        body.addWidget(left_card)

        # 右栏：模型列表卡片
        right_card = QFrame()
        right_card.setObjectName("card")
        right_layout = QVBoxLayout(right_card)
        right_layout.setContentsMargins(16, 16, 16, 16)
        right_layout.setSpacing(12)

        right_header = QHBoxLayout()
        right_title = QLabel("模型列表")
        right_title.setObjectName("cardTitle")
        right_header.addWidget(right_title)
        right_header.addStretch(1)
        right_layout.addLayout(right_header)

        self.loading_bar = QProgressBar()
        self.loading_bar.setRange(0, 0)
        self.loading_bar.setTextVisible(False)
        self.loading_bar.setObjectName("loadingBar")
        self.loading_bar.setFixedHeight(4)
        self.loading_bar.hide()
        right_layout.addWidget(self.loading_bar)

        self.model_table = QTableWidget(0, 3)
        self.model_table.setHorizontalHeaderLabels(["模型 ID", "Owner", ""])
        self.model_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.model_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.model_table.setAlternatingRowColors(True)
        header = self.model_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.model_table.setColumnWidth(2, 72)
        self.model_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.model_table.customContextMenuRequested.connect(self._on_model_menu)
        self.model_table.itemSelectionChanged.connect(self._on_model_selection_changed)
        right_layout.addWidget(self.model_table, 1)

        body.addWidget(right_card, 1)
        root.addLayout(body, 1)

        self.statusBar().showMessage("就绪")

    def _reload_configs(self):
        self.configs = list_configs()
        self.api_list.clear()
        for config in self.configs:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, config["id"])
            row = ConfigRowWidget(
                config["name"] or "未命名配置",
                config["base_url"],
                on_probe=lambda checked=False, c=config: self._probe_config(c),
            )
            item.setSizeHint(QSize(0, CONFIG_ROW_HEIGHT))
            self.api_list.addItem(item)
            self.api_list.setItemWidget(item, row)
        self.api_list.update_name_widths()

    @staticmethod
    def _config_label(config):
        name = config["name"]
        base_url = config["base_url"]
        if name and base_url:
            return f"{name}  ·  {base_url}"
        return name or base_url or "未命名配置"

    def _config_by_id(self, config_id):
        for config in self.configs:
            if config["id"] == config_id:
                return config
        return None

    def _copy_text(self, text):
        QApplication.clipboard().setText(text)
        self.statusBar().showMessage("已复制到剪贴板")

    def _format_config(self, config):
        api_key = get_api_key(config["id"])
        parts = []
        if config["name"]:
            parts.append(f"名称: {config['name']}")
        if config["base_url"]:
            parts.append(f"Base URL: {config['base_url']}")
        parts.append(f"API Key: {api_key}")
        return "\n".join(parts)

    # --- API 配置列表操作 ---

    def _on_api_list_menu(self, pos):
        item = self.api_list.itemAt(pos)
        if item is None:
            return
        config_id = item.data(Qt.ItemDataRole.UserRole)
        config = self._config_by_id(config_id)
        if config is None:
            return

        menu = QMenu(self)
        probe_act = QAction("探测此配置", self)
        probe_act.triggered.connect(lambda: self._probe_config(config))
        menu.addAction(probe_act)
        menu.addSeparator()

        copy_key = QAction("复制 API Key", self)
        copy_key.triggered.connect(lambda: self._copy_text(get_api_key(config_id)))
        menu.addAction(copy_key)

        copy_url = QAction("复制 base_url", self)
        copy_url.triggered.connect(lambda: self._copy_text(config["base_url"]))
        menu.addAction(copy_url)

        copy_full = QAction("复制完整配置", self)
        copy_full.triggered.connect(lambda: self._copy_text(self._format_config(config)))
        menu.addAction(copy_full)
        menu.addSeparator()

        edit_act = QAction("查看/编辑", self)
        edit_act.triggered.connect(lambda: self._edit_config(config))
        menu.addAction(edit_act)

        del_act = QAction("删除", self)
        del_act.triggered.connect(lambda: self._delete_config(config))
        menu.addAction(del_act)

        menu.exec(self.api_list.viewport().mapToGlobal(pos))

    def _on_add(self):
        dialog = ConfigDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            name, base_url, api_key = dialog.values()
            add_config(name, base_url, api_key)
            self._reload_configs()
            self.statusBar().showMessage("已新增配置")

    def _edit_config(self, config):
        dialog = ConfigDialog(
            self,
            name=config["name"],
            base_url=config["base_url"],
            api_key=get_api_key(config["id"]),
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            name, base_url, api_key = dialog.values()
            update_config(config["id"], name, base_url, api_key)
            self._reload_configs()
            self.statusBar().showMessage("已更新配置")

    def _delete_config(self, config):
        label = self._config_label(config)
        if confirm_message_box("确认删除", f"确定删除配置「{label}」吗？", self):
            delete_config(config["id"])
            self._reload_configs()
            self.statusBar().showMessage("已删除配置")

    # --- 探测 ---

    def _probe_config(self, config):
        api_key = get_api_key(config["id"])
        if not api_key:
            show_message_box("缺少 API Key", "该配置的 API Key 为空。", self)
            return

        self._set_running(True)
        self.model_table.setRowCount(0)
        self.statusBar().showMessage(f"正在探测：{self._config_label(config)}…")

        self.worker = ModelProbeWorker(config["base_url"], api_key, self)
        self.worker.models_ready.connect(self._on_models_ready)
        self.worker.failed.connect(self._on_failed)
        self.worker.cancelled.connect(self._on_cancelled)
        self.worker.finished.connect(self._on_finished)
        self.worker.start()

    def _on_models_ready(self, models):
        self._clear_copy_button()
        self.model_table.setRowCount(len(models))
        for row, model in enumerate(models):
            self.model_table.setItem(row, 0, QTableWidgetItem(model.id))
            self.model_table.setItem(row, 1, QTableWidgetItem(getattr(model, "owned_by", "")))
        self.statusBar().showMessage(f"共发现 {len(models)} 个模型")

    def _on_failed(self, message):
        self.statusBar().showMessage("探测失败")
        QMessageBox.critical(self, "探测失败", f"无法获取模型列表：\n{message}")

    def _on_cancelled(self):
        self.statusBar().showMessage("已取消")

    def _on_finished(self):
        self._set_running(False)

    # --- 模型列表复制 ---

    def _on_model_menu(self, pos):
        item = self.model_table.itemAt(pos)
        if item is None:
            return
        self.model_table.selectRow(item.row())
        model_id = self.model_table.item(item.row(), 0).text()

        menu = QMenu(self)
        copy_act = QAction("复制模型 ID", self)
        copy_act.triggered.connect(lambda: self._copy_text(model_id))
        menu.addAction(copy_act)
        menu.exec(self.model_table.viewport().mapToGlobal(pos))

    def _on_model_selection_changed(self):
        row = self.model_table.currentRow()
        if row < 0:
            self._clear_copy_button()
            return
        self._place_copy_button(row)

    def _place_copy_button(self, row):
        if self._copy_btn_row == row:
            return
        self._clear_copy_button()
        btn = QPushButton("复制")
        btn.setObjectName("copyButton")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(lambda checked=False, r=row: self._copy_model_id(r))
        self.model_table.setCellWidget(row, 2, btn)
        self._copy_btn = btn
        self._copy_btn_row = row

    def _clear_copy_button(self):
        if self._copy_btn is not None and self._copy_btn_row >= 0:
            self.model_table.removeCellWidget(self._copy_btn_row, 2)
            self._copy_btn.deleteLater()
        self._copy_btn = None
        self._copy_btn_row = -1

    def _copy_model_id(self, row):
        item = self.model_table.item(row, 0)
        if item:
            self._copy_text(item.text())

    def _set_running(self, running):
        self.api_list.setEnabled(not running)
        self.loading_bar.setVisible(running)

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.worker.requestInterruption()
            self.worker.wait()
        super().closeEvent(event)


def _apply_macos_menu_name():
    """macOS 未打包运行时，让菜单栏显示应用名而不是 Python。"""
    if sys.platform != "darwin":
        return
    try:
        from Foundation import NSProcessInfo
        NSProcessInfo.processInfo().setProcessName_(APP_DISPLAY_NAME)
    except Exception:
        pass
    try:
        from AppKit import NSApp
        main_menu = NSApp.mainMenu()
        if main_menu is not None and main_menu.numberOfItems() > 0:
            app_item = main_menu.itemAtIndex_(0)
            if app_item is not None:
                app_item.setTitle_(APP_DISPLAY_NAME)
    except Exception:
        pass


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_DISPLAY_NAME)
    _apply_macos_menu_name()
    app.setStyleSheet(STYLE_SHEET)
    if ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(ICON_PATH)))
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
