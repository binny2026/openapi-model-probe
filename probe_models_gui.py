"""探测当前 API 凭证可访问的模型列表（PySide6 + QFluentWidgets 跨平台 GUI 版）。

功能：
- 管理多个 API 配置（名称 + Base URL + API Key），API Key 加密存储到本地 SQLite
- 左栏 API 配置列表，右栏模型列表
- 配置行内探测 / 编辑 / 删除，右键复制
- 基于 QFluentWidgets 的 Fluent Design 深色主题

本文件自包含核心探测逻辑，不依赖、也不改动 probe_models.py。
"""

import os
import sqlite3
import sys
from pathlib import Path

from cryptography.fernet import Fernet
from openai import OpenAI
from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    CardWidget,
    IndeterminateProgressBar,
    LineEdit,
    MessageBox,
    PasswordLineEdit,
    PrimaryPushButton,
    PushButton,
    SubtitleLabel,
    Theme,
    setTheme,
    setThemeColor,
)

# 以脚本所在目录为准加载本地数据库，保证从任意路径启动行为一致
SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = SCRIPT_DIR / "probe_models.db"
KEY_PATH = SCRIPT_DIR / "probe_models.key"
ICON_PATH = SCRIPT_DIR / "icon.png"


def show_message_box(title, content, parent):
    """单按钮（确定）Fluent 消息框。"""
    box = MessageBox(title, content, parent)
    box.yesButton.setText("确定")
    box.cancelButton.hide()
    box.exec()


def confirm_message_box(title, content, parent):
    """确定 / 取消 二选一 Fluent 消息框，返回是否确定。"""
    box = MessageBox(title, content, parent)
    box.yesButton.setText("确定")
    box.cancelButton.setText("取消")
    return box.exec() == QDialog.DialogCode.Accepted


def _load_or_create_key():
    """加载本机密钥；不存在则生成并写入 0600 权限的密钥文件。"""
    if KEY_PATH.exists():
        return KEY_PATH.read_bytes().strip()
    key = Fernet.generate_key()
    KEY_PATH.write_bytes(key)
    try:
        os.chmod(KEY_PATH, 0o600)
    except OSError:
        pass  # 某些平台不支持 chmod，忽略即可
    return key


def _connect():
    return sqlite3.connect(DB_PATH)


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

    models_ready = Signal(list)  # 携带按 id 排序后的模型对象列表
    failed = Signal(str)         # 携带错误信息
    cancelled = Signal()         # 探测被用户取消

    def __init__(self, base_url, api_key, parent=None):
        super().__init__(parent)
        self.base_url = base_url
        self.api_key = api_key

    def run(self):
        client_options = {"api_key": self.api_key}
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
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.name_edit = LineEdit()
        self.name_edit.setText(name)
        self.name_edit.setPlaceholderText("例如：OpenAI / 本地 Ollama")

        self.base_url_edit = LineEdit()
        self.base_url_edit.setText(base_url)
        self.base_url_edit.setPlaceholderText("留空使用默认 https://api.openai.com/v1")

        self.api_key_edit = PasswordLineEdit()
        self.api_key_edit.setText(api_key)
        self.api_key_edit.setPlaceholderText("sk-...")

        form.addRow("名称", self.name_edit)
        form.addRow("Base URL", self.base_url_edit)
        form.addRow("API Key", self.api_key_edit)
        layout.addLayout(form)

        btn_row = QHBoxLayout()
        cancel_btn = PushButton()
        cancel_btn.setText("取消")
        cancel_btn.clicked.connect(self.reject)
        save_btn = PrimaryPushButton()
        save_btn.setText("保存")
        save_btn.clicked.connect(self._on_accept)
        btn_row.addStretch(1)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

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
        self.setFixedHeight(44)
        self.full_name = name

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

        self.probe_btn = PrimaryPushButton()
        self.probe_btn.setText("探测")
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

        # 顶部工具栏
        toolbar = QHBoxLayout()
        self.cancel_btn = PushButton()
        self.cancel_btn.setText("取消")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._on_cancel)
        toolbar.addWidget(self.cancel_btn)
        toolbar.addStretch(1)
        root.addLayout(toolbar)

        # 左右分栏（左栏固定宽度）
        body = QHBoxLayout()
        body.setSpacing(12)

        # 左栏：API 配置卡片
        left_card = CardWidget()
        left_card.setFixedWidth(380)
        left_layout = QVBoxLayout(left_card)
        left_layout.setContentsMargins(16, 16, 16, 16)
        left_layout.setSpacing(12)

        left_header = QHBoxLayout()
        left_title = SubtitleLabel("API 配置")
        left_header.addWidget(left_title)
        left_header.addStretch(1)
        add_btn = PrimaryPushButton()
        add_btn.setText("新增")
        add_btn.clicked.connect(self._on_add)
        left_header.addWidget(add_btn)
        left_layout.addLayout(left_header)

        self.api_list = ConfigListWidget()
        self.api_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.api_list.customContextMenuRequested.connect(self._on_api_list_menu)
        left_layout.addWidget(self.api_list, 1)

        body.addWidget(left_card)

        # 右栏：模型列表卡片
        right_card = CardWidget()
        right_layout = QVBoxLayout(right_card)
        right_layout.setContentsMargins(16, 16, 16, 16)
        right_layout.setSpacing(12)

        right_header = QHBoxLayout()
        right_title = SubtitleLabel("模型列表")
        right_header.addWidget(right_title)
        right_header.addStretch(1)
        self.loading_bar = IndeterminateProgressBar()
        self.loading_bar.setFixedSize(24, 24)
        self.loading_bar.hide()
        right_header.addWidget(self.loading_bar)
        right_layout.addLayout(right_header)

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
            item.setSizeHint(row.sizeHint())
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

    def _on_cancel(self):
        if self.worker and self.worker.isRunning():
            self.worker.requestInterruption()
            self.statusBar().showMessage("正在取消…")

    def _on_models_ready(self, models):
        self._clear_copy_button()
        self.model_table.setRowCount(len(models))
        for row, model in enumerate(models):
            self.model_table.setItem(row, 0, QTableWidgetItem(model.id))
            self.model_table.setItem(row, 1, QTableWidgetItem(getattr(model, "owned_by", "")))
        self.statusBar().showMessage(f"共发现 {len(models)} 个模型")

    def _on_failed(self, message):
        self.statusBar().showMessage("探测失败")
        show_message_box("探测失败", f"无法获取模型列表：\n{message}", self)

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
        btn = PushButton()
        btn.setText("复制")
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
        self.cancel_btn.setEnabled(running)
        self.api_list.setEnabled(not running)
        self.loading_bar.setVisible(running)

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.worker.requestInterruption()
            self.worker.wait()
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    if ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(ICON_PATH)))
    setTheme(Theme.DARK)
    setThemeColor("#4f8cff")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
