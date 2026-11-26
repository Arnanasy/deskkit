"""静默启动 DeskKit 本地服务、驻留右下角系统托盘并在浏览器打开；若已在运行则直接复用现有实例。"""
import ctypes
from pathlib import Path
import sys
import threading
import time
from urllib.request import urlopen
import webbrowser

sys.dont_write_bytecode = True
IS_FROZEN = getattr(sys, 'frozen', False)
APP_DIR = Path(sys.executable).resolve().parent if IS_FROZEN else Path(__file__).resolve().parent
RESOURCE_DIR = Path(getattr(sys, '_MEIPASS', APP_DIR)) if IS_FROZEN else APP_DIR
if not IS_FROZEN:
    sys.path.insert(0, str(APP_DIR))

# 打包为单文件 .exe 后的系统文件/文件夹弹窗子进程入口
if len(sys.argv) >= 5 and sys.argv[1] == '--dialog':
    from tools_files import run_tk_dialog_from_args
    run_tk_dialog_from_args(sys.argv[2], sys.argv[3], sys.argv[4])
    sys.exit(0)

from server import DEFAULT_PORT, PORT_SPAN, create_server
from tools_files import OUTPUT_DIR, open_in_explorer
from tools_video import video_tasks
from tray import DeskKitTray


def _running_port():
    for port in range(DEFAULT_PORT, DEFAULT_PORT + PORT_SPAN):
        try:
            with urlopen(f'http://127.0.0.1:{port}/api/health', timeout=0.35) as resp:
                if resp.status == 200:
                    return port
        except OSError:
            continue
    return None


def main():
    existing = _running_port()
    if existing:
        webbrowser.open(f'http://127.0.0.1:{existing}/')
        return

    httpd, port = create_server(DEFAULT_PORT)
    url = f'http://127.0.0.1:{port}/'
    icon_file = RESOURCE_DIR / 'DeskKit.ico'
    tray = DeskKitTray(
        tip=f'DeskKit 本地工具箱（左键打开，右键菜单 · 127.0.0.1:{port}）',
        on_open=lambda: webbrowser.open(url),
        on_folder=lambda: open_in_explorer(str(OUTPUT_DIR)),
        icon_path=icon_file if icon_file.is_file() else None,
    )
    httpd.on_shutdown = tray.request_quit

    srv_thread = threading.Thread(target=httpd.serve_forever, name='deskkit-http', daemon=True)
    srv_thread.start()
    threading.Timer(0.25, lambda: webbrowser.open(url)).start()
    try:
        tray.run()
    finally:
        video_tasks.cancel_all()
        try:
            httpd.shutdown()
        except Exception:
            pass
        httpd.server_close()


if __name__ == '__main__':
    try:
        main()
    except Exception as err:
        log_file = APP_DIR / 'DeskKit_error.log'
        try:
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {err!r}\n")
        except OSError:
            pass
        ctypes.WinDLL('user32').MessageBoxW(
            None, f'DeskKit 启动失败：\n{err}', 'DeskKit', 0x10
        )
