# 本地工具箱

纯本地运行的无广告私人工具箱（Windows），零云端上传、离线可用。

## 功能概览

- **视频工坊**：自动诊断编码，一键转 Win 全兼容 MP4（已是 H.264 自动无损秒换壳，HEVC/AV1/10-bit 优先启用 NVIDIA NVENC 硬编），支持压小体积、时间裁剪、画面旋转/翻转、提取音频、转高清 GIF、批量导出截图、多视频合并（支持无损秒合或兼容重编码合并）与字幕格式互转（SRT / VTT / ASS）。
- **图片工坊**：批量压缩、格式互转（JPG / PNG / WEBP / AVIF / ICO，支持读取手机 HEIC/HEIF）、宽高缩放限制、清除 EXIF 隐私信息、竖向/横向拼长图与宫格拼图、批量旋转/翻转、长图分割与九宫格切图（列表支持拖拽与箭头排序）。
- **PDF 工坊**：PDF ↔ Word (`.docx`) 互转、多 PDF 合并（支持排序）、按页提取/删页/旋转/拆分、PDF 转图片、多图合 PDF、PDF 压缩、AES-256 加密与已知密码解锁/去除打印复制限制，全模块支持文件拖放与内置阅读预览。
- **文本与杂项**：文本去重/排序/统计、JSON 格式化、纯离线二维码生成、随机强密码、双向时间戳与正则测试、本地文件夹批量重命名与后缀管理（带预览、补零位数与冲突检测）、ZIP 中文文件名乱码修复、TXT/CSV 编码乱码修复（支持 Excel 友好 UTF-8 BOM）以及大文件 MD5/SHA1/SHA256/CRC32 哈希校验比对。
- **计算与换算**：房贷与提前还款双方案对比（等额本息/等额本金、年限不变减月供 vs 月供不变缩年限）、复利定投、本地时区日期与工作日间隔、存储单位与 HEX/RGB/HSL 色值换算。

## 环境要求

- Windows 10 / 11，Python 3.10+
- Python 依赖：
  ```bash
  pip install -r requirements.txt
  ```
- 按需外部工具：
  - **FFmpeg**（含 `ffprobe` 并加入系统 `PATH`）：视频工坊必需，可通过 `winget install Gyan.FFmpeg` 安装。
  - **Microsoft Word**：仅「Word → PDF」功能需要，其余全部功能不依赖 Word。

## 启动方式

双击 `启动工具箱.cmd` 即可无黑框启动本地服务并自动在浏览器打开；所有导出文件默认保存在 `下载\工具箱输出`。

## 目录说明

- `启动工具箱.cmd` / `launch.pyw`：无黑框一键启动入口（自动复用已运行实例）
- `server.py`：本地 HTTP 服务（仅监听 `127.0.0.1`，带 Host / Token / CSP 安全防护）
- `tools_video.py` / `tools_image.py` / `tools_pdf.py` / `tools_files.py`：各模块后端实现
- `web/`：纯离线前端界面（`index.html`、`style.css`、`app.js`、`qrcode.js`）
