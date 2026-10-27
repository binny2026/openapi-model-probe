# AI 模型探测工具

基于 PySide6 的跨平台桌面工具，用于管理多个 OpenAI 兼容 API 配置并探测可用模型列表。

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

配置保存在系统用户数据目录（`QStandardPaths.AppDataLocation`，如 macOS 的 `~/Library/Application Support/ai-model-prober`），API Key 使用 Fernet 加密。密钥文件（`probe_models.key`）与加密后的配置存放在同一目录，用于加解密；它不是硬件绑定，请勿对外泄露数据库与密钥文件。

## 打包

PyInstaller 不支持跨操作系统交叉构建，必须在目标平台上构建对应产物：

- macOS → 在 macOS 上构建 `.app`
- Windows → 在 Windows 上构建 `.exe`
- Linux → 在 Linux 上构建可执行文件

打包前先准备独立虚拟环境，避免本机无关依赖被带入产物。构建产物不含数据库、密钥文件或 `.env`；应用首次运行时会在用户数据目录新建这些文件。

### macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt pyinstaller

pyinstaller --windowed --onedir --clean \
  --name "AI 模型探测工具" \
  --icon icon.icns \
  --add-data "icon.png:." \
  --osx-bundle-identifier com.binny2026.ai-model-prober \
  probe_models_gui.py
```

- 构建的是 `.app` 应用包（`onedir` 模式），产物位于 `dist/`。
- `--target-arch` 默认跟随当前机器架构；如需显式指定，可在 Apple Silicon 上追加 `--target-arch arm64`，在 Intel 上追加 `--target-arch x86_64`。
- 该命令仅做 ad hoc 签名，未做 Apple Developer ID 签名与公证；本机运行可直接双击，对外分发需另行签名并公证。

### Windows

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt pyinstaller

pyinstaller --onefile --windowed --clean `
  --name "AI 模型探测工具" `
  --icon icon.ico `
  --add-data "icon.png;." `
  probe_models_gui.py
```

- `--onefile` 生成单个 `.exe`，产物位于 `dist/`。
- 需在 Windows 环境（实体机或虚拟机）执行，PowerShell 下的 `--add-data` 分隔符为 `;`。

### Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt pyinstaller

pyinstaller --onefile --windowed --clean \
  --name "ai-model-prober" \
  --icon icon.png \
  --add-data "icon.png:." \
  probe_models_gui.py
```

- 产物为单个可执行文件，位于 `dist/`。
- 建议在目标发行版或较旧的兼容发行版上构建；Qt 图形界面在部分无桌面环境（无 X/Wayland）的机器上无法启动，请在有图形环境的系统上运行。

### 说明

以上命令产出的是可执行文件或 `.app` 应用包，不是 DMG、安装向导（NSIS）或 AppImage 安装器。需要安装器时，需在本命令基础上额外封装。
