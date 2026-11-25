"""静默启动 DeskKit 并在浏览器打开；若已在运行则直接复用现有实例。"""
import ctypes
from pathlib import Path
import sys
import threading
import time
from urllib.request import urlopen
import webbrowser

sys.dont_write_bytecode = True
APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_DIR))

from server import DEFAULT_PORT, PORT_SPAN, create_server
from tools_video import video_tasks


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
    threading.Timer(0.25, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    finally:
        video_tasks.cancel_all()
        httpd.server_close()


if __name__ == '__main__':
    try:
        main()
    except Exception as err:
        log_file = APP_DIR / 'DeskKit_error.log'
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {err!r}\n")
        ctypes.WinDLL('user32').MessageBoxW(
            None, f'DeskKit 启动失败：\n{err}', 'DeskKit', 0x10
        )
