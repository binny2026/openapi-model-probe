# AI 模型探测工具

基于 PySide6 + QFluentWidgets 的跨平台桌面工具，用于管理多个 OpenAI 兼容 API 配置并探测可用模型列表。

## 功能

- 管理多个 API 配置（名称 / Base URL / API Key），API Key 加密存储到本地 SQLite
- 探测 `/models` 接口，展示可用模型列表
- 支持复制模型 ID、复制配置信息、右键查看/编辑/删除

## 运行

```bash
pip install -r requirements.txt
python probe_models_gui.py
```

命令行版：`python probe_models.py --help`

## 数据存储

配置保存在系统用户数据目录（`QStandardPaths.AppDataLocation`，如 macOS 的 `~/Library/Application Support/ai-model-prober`），API Key 使用 Fernet 加密，密钥文件与本机绑定。
