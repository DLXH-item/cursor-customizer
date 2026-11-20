@echo off
chcp 65001 >nul
echo === 生成图标 app.ico ===
python make_icon.py
echo === 安装依赖 ===
pip install -r requirements.txt pyinstaller
echo === 按 spec 打包单文件 EXE（排除视频解码栈与冗余 Qt 模块）===
pyinstaller --noconfirm CursorCustomizer.spec
echo === 完成，产物在 dist 目录 ===
pause
