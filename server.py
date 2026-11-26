"""DeskKit 本地 HTTP 服务（纯 Python 标准库，仅监听 127.0.0.1，带 Host/Token/CSP 防护）。"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
from logging.handlers import RotatingFileHandler
import mimetypes
from pathlib import Path
import secrets
import sys
import threading
from urllib.parse import parse_qs, quote, unquote, urlparse
import uuid

from tools_files import (
    OUTPUT_DIR, UPLOAD_DIR, UPLOAD_PREFIX, calc_file_hash, cleanup_old_uploads,
    ensure_dirs, execute_batch_rename, fix_text_encoding, fix_zip_encoding,
    is_within, open_in_explorer, pick_files, pick_folder, preview_batch_rename,
    safe_filename,
)
from tools_image import (
    process_convert_compress, rotate_flip_images, split_image, stitch_images,
)
from tools_pdf import (
    compress_pdf, edit_pages, images_to_pdf, merge_pdfs, pdf_info,
    pdf_to_images, pdf_to_word, protect_pdf, unlock_pdf, word_to_pdf,
)
from tools_video import (
    convert_subtitle, export_video_frames, ffmpeg_bins, has_nvenc, probe_video,
    video_tasks,
)

IS_FROZEN = getattr(sys, 'frozen', False)
APP_DIR = Path(sys.executable).resolve().parent if IS_FROZEN else Path(__file__).resolve().parent
RESOURCE_DIR = Path(getattr(sys, '_MEIPASS', APP_DIR)) if IS_FROZEN else APP_DIR
WEB_DIR = RESOURCE_DIR / 'web'
DEFAULT_PORT = 18642
PORT_SPAN = 20
MAX_UPLOAD_BYTES = 4 * 1024 * 1024 * 1024  # 单文件上传上限 4GB
SOCKET_TIMEOUT = 60                        # 单次读写空闲超时（秒），防慢速连接挂死线程
_THUMB_SEM = threading.Semaphore(2)        # 限制同时拉起的缩略图 FFmpeg 并发数
CSP_HEADER = (
    "default-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; media-src 'self' blob:; frame-src 'self'"
)

log = logging.getLogger('toolbox')
log.setLevel(logging.WARNING)
if not log.handlers:
    try:
        _log_path = APP_DIR / 'DeskKit_error.log'
        _handler = RotatingFileHandler(
            _log_path, maxBytes=512000, backupCount=1, delay=True, encoding='utf-8'
        )
    except OSError:
        _handler = RotatingFileHandler(
            UPLOAD_DIR.parent / 'DeskKit_error.log', maxBytes=512000, backupCount=1, delay=True, encoding='utf-8'
        )
    _handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
    log.addHandler(_handler)


class ToolboxHandler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def setup(self):
        super().setup()
        self.request.settimeout(SOCKET_TIMEOUT)

    def log_message(self, fmt, *args):
        # 静默常规访问日志，避免 pythonw 无控制台时异常
        pass

    def _allowed_hosts(self):
        port = self.server.server_port
        return {f'127.0.0.1:{port}', f'localhost:{port}'}

    def _check_host(self):
        """校验 Host 头，防御 DNS Rebinding 攻击。"""
        host = (self.headers.get('Host') or '').strip().lower()
        if host not in self._allowed_hosts():
            self._send_json({'error': '非法的 Host 来源'}, 403)
            return False
        return True

    def _check_post_auth(self):
        """校验同源 Origin 与进程级随机 Token，防御跨站 CSRF 攻击。"""
        origin = (self.headers.get('Origin') or '').strip().lower()
        if origin:
            port = self.server.server_port
            if origin not in (f'http://127.0.0.1:{port}', f'http://localhost:{port}'):
                self._send_json({'error': '禁止跨站请求'}, 403)
                return False
        token = (self.headers.get('X-Toolbox-Token') or '').strip()
        expected = getattr(self.server, 'api_token', '')
        if not expected or not secrets.compare_digest(token, expected):
            self._send_json({'error': '缺少或无效的安全令牌，请刷新页面重试'}, 403)
            return False
        return True

    def _send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get('Content-Length') or 0)
        if length < 0 or length > 10 * 1024 * 1024:
            raise ValueError('请求体大小超出限制')
        raw = self.rfile.read(length) if length > 0 else b'{}'
        return json.loads(raw.decode('utf-8'))

    def _serve_static(self, rel_path):
        if rel_path in ('', '/'):
            rel_path = '/index.html'
        target = (WEB_DIR / rel_path.lstrip('/')).resolve()
        if not is_within(target, WEB_DIR) or not target.is_file():
            self._send_json({'error': '资源不存在'}, 404)
            return
        data = target.read_bytes()
        if target.name == 'index.html':
            token = getattr(self.server, 'api_token', '')
            meta = f'<meta name="toolbox-token" content="{token}">\n</head>'
            data = data.decode('utf-8').replace('</head>', meta, 1).encode('utf-8')
        ctype, _ = mimetypes.guess_type(str(target))
        if not ctype:
            ctype = 'application/octet-stream'
        if ctype.startswith('text/') or ctype in ('application/javascript', 'application/json'):
            ctype += '; charset=utf-8'
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        if target.name == 'index.html':
            self.send_header('Content-Security-Policy', CSP_HEADER)
        self.end_headers()
        self.wfile.write(data)

    def _can_preview(self, target):
        """仅允许预览输出目录、上传目录，或本会话通过系统弹窗主动选中的文件。"""
        if is_within(target, OUTPUT_DIR) or is_within(target, UPLOAD_DIR):
            return True
        allowed = getattr(self.server, 'allowed_paths', set())
        return str(target).lower() in allowed

    def _serve_preview(self, path_str):
        target = Path(path_str).resolve()
        if not self._can_preview(target) or not target.is_file():
            self._send_json({'error': '文件不存在或无权预览'}, 404)
            return
        size = target.stat().st_size
        ctype, _ = mimetypes.guess_type(str(target))
        if target.suffix.lower() == '.webp':
            ctype = 'image/webp'
        elif target.suffix.lower() == '.avif':
            ctype = 'image/avif'
        ctype = ctype or 'application/octet-stream'

        range_hdr = self.headers.get('Range')
        start, end = 0, size - 1
        status = 200
        if range_hdr and range_hdr.startswith('bytes='):
            spec = range_hdr[6:].split(',')[0].strip()
            a, _, b = spec.partition('-')
            try:
                if a:
                    start = int(a)
                    end = int(b) if b else size - 1
                elif b:
                    start = max(0, size - int(b))
                start = max(0, min(start, max(0, size - 1)))
                end = max(start, min(end, max(0, size - 1)))
                status = 206
            except ValueError:
                start, end, status = 0, max(0, size - 1), 200

        length = max(0, end - start + 1) if size > 0 else 0
        self.send_response(status)
        self.send_header('Content-Type', ctype)
        self.send_header('X-Content-Type-Options', 'nosniff')
        # Chrome/Edge 内置 PDF 查看器在 iframe 收到 CSP: sandbox 时易白屏，仅对非 PDF 预览加 sandbox
        if target.suffix.lower() != '.pdf':
            self.send_header('Content-Security-Policy', 'sandbox')
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Content-Length', str(length))
        if status == 206 and size > 0:
            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        if length == 0:
            return
        with open(target, 'rb') as f:
            f.seek(start)
            left = length
            while left > 0:
                chunk = f.read(min(262144, left))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except OSError:
                    break
                left -= len(chunk)

    def _serve_video_thumb(self, path_str):
        """使用 FFmpeg 抽取视频封面帧（兼容 HEVC/MKV 等浏览器无法直接播放的格式）。"""
        import subprocess
        target = Path(path_str).resolve()
        if not self._can_preview(target) or not target.is_file():
            self._send_json({'error': '文件不存在或无权预览'}, 404)
            return
        ffmpeg, _ = ffmpeg_bins()
        if not ffmpeg:
            self._send_json({'error': '未找到 ffmpeg'}, 500)
            return
        no_win = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        if not _THUMB_SEM.acquire(timeout=10):
            self._send_json({'error': '缩略图生成繁忙，请稍后重试'}, 429)
            return
        try:
            run = subprocess.run(
                [ffmpeg, '-hide_banner', '-loglevel', 'error', '-ss', '00:00:01', '-i', str(target),
                 '-frames:v', '1', '-vf', 'scale=480:-2,format=yuvj420p', '-f', 'image2pipe', '-vcodec', 'mjpeg', 'pipe:1'],
                capture_output=True, timeout=8, creationflags=no_win,
            )
            data = run.stdout
            if not data:
                # 短视频不足 1 秒时回退取第 0 秒首帧
                run = subprocess.run(
                    [ffmpeg, '-hide_banner', '-loglevel', 'error', '-i', str(target),
                     '-frames:v', '1', '-vf', 'scale=480:-2,format=yuvj420p', '-f', 'image2pipe', '-vcodec', 'mjpeg', 'pipe:1'],
                    capture_output=True, timeout=8, creationflags=no_win,
                )
                data = run.stdout
        finally:
            _THUMB_SEM.release()
        if not data:
            self._send_json({'error': '无法生成缩略图'}, 404)
            return
        self.send_response(200)
        self.send_header('Content-Type', 'image/jpeg')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def _serve_download(self, path_str):
        target = Path(path_str).resolve()
        if not is_within(target, OUTPUT_DIR) or not target.is_file():
            self._send_json({'error': '文件不存在或无权访问'}, 404)
            return
        size = target.stat().st_size
        ctype, _ = mimetypes.guess_type(str(target))
        self.send_response(200)
        self.send_header('Content-Type', ctype or 'application/octet-stream')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Length', str(size))
        encoded_name = quote(target.name)
        self.send_header('Content-Disposition', f"attachment; filename*=UTF-8''{encoded_name}")
        self.end_headers()
        with open(target, 'rb') as f:
            while True:
                chunk = f.read(262144)
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except OSError:
                    break

    def do_GET(self):
        if not self._check_host():
            return
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)
        try:
            if path == '/api/health':
                ffmpeg, ffprobe = ffmpeg_bins()
                self._send_json({
                    'ok': True,
                    'output_dir': str(OUTPUT_DIR),
                    'ffmpeg': bool(ffmpeg and ffprobe),
                    'nvenc': has_nvenc(),
                })
                return

            if path == '/api/download':
                file_path = qs.get('path', [''])[0]
                self._serve_download(file_path)
                return

            if path == '/api/preview':
                file_path = qs.get('path', [''])[0]
                self._serve_preview(file_path)
                return

            if path == '/api/video/thumb':
                file_path = qs.get('path', [''])[0]
                self._serve_video_thumb(file_path)
                return

            if path.startswith('/api/video/task/'):
                task_id = path.rsplit('/', 1)[-1]
                task = video_tasks.get(task_id)
                if not task:
                    self._send_json({'error': '任务不存在'}, 404)
                else:
                    self._send_json(task)
                return

            self._serve_static(path)
        except Exception as err:
            log.exception('GET %s 异常', path)
            self._send_json({'error': str(err)}, 500)

    def do_POST(self):
        if not self._check_host() or not self._check_post_auth():
            return
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)
        try:
            # 流式二进制上传（兼容大文件，限制上限并清理中断残留）
            if path == '/api/upload':
                ensure_dirs()
                raw_name = unquote(qs.get('name', ['file'])[0])
                safe = safe_filename(Path(raw_name).name)
                token = uuid.uuid4().hex[:8]
                target = UPLOAD_DIR / f'{UPLOAD_PREFIX}{token}_{safe}'
                remaining = int(self.headers.get('Content-Length') or 0)
                if remaining < 0 or remaining > MAX_UPLOAD_BYTES:
                    self._send_json({'error': '文件过大（单文件上限 4GB），建议直接点「选本机文件」零拷贝处理'}, 413)
                    return
                try:
                    with open(target, 'wb') as f:
                        while remaining > 0:
                            chunk = self.rfile.read(min(remaining, 1048576))
                            if not chunk:
                                raise IOError('上传连接意外中断')
                            f.write(chunk)
                            remaining -= len(chunk)
                except Exception:
                    target.unlink(missing_ok=True)
                    raise
                self._send_json({
                    'path': str(target),
                    'name': Path(raw_name).name,
                    'size': target.stat().st_size,
                })
                return

            data = self._read_json()

            # ---- 系统与文件操作 ----
            if path == '/api/pick-files':
                files = pick_files(
                    title=data.get('title', '选择文件'),
                    filetypes=data.get('filetypes'),
                    multiple=bool(data.get('multiple', False)),
                )
                allowed = getattr(self.server, 'allowed_paths', None)
                if allowed is not None:
                    for fp in files:
                        allowed.add(str(Path(fp).resolve()).lower())
                self._send_json({'files': files})
                return

            if path == '/api/pick-folder':
                folder = pick_folder(title=data.get('title', '选择文件夹'))
                self._send_json({'folder': folder})
                return

            if path == '/api/open-path':
                open_in_explorer(data.get('path', ''))
                self._send_json({'ok': True})
                return

            if path == '/api/shutdown':
                video_tasks.cancel_all()
                self._send_json({'ok': True})
                on_shutdown = getattr(self.server, 'on_shutdown', None)
                if callable(on_shutdown):
                    threading.Thread(target=on_shutdown, daemon=True).start()
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return

            # ---- 视频工坊 ----
            if path == '/api/video/probe':
                self._send_json(probe_video(data['path']))
                return

            if path == '/api/video/start':
                opts = dict(data.get('options') or {})
                opts.pop('output_dir', None)  # 禁止通过 HTTP 参数指定任意输出目录
                task = video_tasks.start(data['path'], data['mode'], opts)
                self._send_json(task)
                return

            if path == '/api/video/cancel':
                ok = video_tasks.cancel(data.get('id', ''))
                self._send_json({'ok': ok})
                return

            if path == '/api/video/merge':
                opts = dict(data.get('options') or {})
                opts.pop('output_dir', None)  # 禁止通过 HTTP 参数指定任意输出目录
                task = video_tasks.start_merge(data.get('paths', []), opts)
                self._send_json(task)
                return

            if path == '/api/video/frames':
                res = export_video_frames(
                    path_str=data['path'],
                    mode=data.get('mode', 'interval'),
                    interval=data.get('interval', 2.0),
                    count=data.get('count', 10),
                    fmt=data.get('format', 'jpg'),
                    start=data.get('start', ''),
                    end=data.get('end', ''),
                )
                self._send_json(res)
                return

            if path == '/api/video/subtitle':
                res = convert_subtitle(
                    path_str=data['path'],
                    target_fmt=data.get('format', 'srt'),
                )
                self._send_json(res)
                return

            # ---- 图片工坊 ----
            if path == '/api/image/process':
                res = process_convert_compress(
                    paths=data.get('paths', []),
                    target_fmt=data.get('format', 'keep'),
                    quality=data.get('quality', 82),
                    max_width=data.get('max_width', 0),
                    max_height=data.get('max_height', 0),
                    strip_exif=bool(data.get('strip_exif', True)),
                )
                self._send_json(res)
                return

            if path == '/api/image/stitch':
                res = stitch_images(
                    paths=data.get('paths', []),
                    mode=data.get('mode', 'vertical'),
                    gap=data.get('gap', 0),
                    bg_color=data.get('bg_color', '#ffffff'),
                    cols=data.get('cols', 2),
                    out_fmt=data.get('format', 'png'),
                )
                self._send_json(res)
                return

            if path == '/api/image/rotate':
                res = rotate_flip_images(
                    paths=data.get('paths', []),
                    op=data.get('op', 'cw90'),
                    out_fmt=data.get('format', 'keep'),
                )
                self._send_json(res)
                return

            if path == '/api/image/split':
                res = split_image(
                    path_str=data['path'],
                    mode=data.get('mode', 'vertical'),
                    parts=data.get('parts', 3),
                    rows=data.get('rows', 3),
                    cols=data.get('cols', 3),
                    max_piece_height=data.get('max_piece_height', 0),
                    out_fmt=data.get('format', 'png'),
                )
                self._send_json(res)
                return

            # ---- PDF 工坊 ----
            if path == '/api/pdf/info':
                self._send_json(pdf_info(data['path']))
                return

            if path == '/api/pdf/merge':
                self._send_json(merge_pdfs(data.get('paths', [])))
                return

            if path == '/api/pdf/edit':
                self._send_json(edit_pages(
                    path_str=data['path'],
                    action=data['action'],
                    pages_expr=data.get('pages', ''),
                    angle=data.get('angle', 90),
                ))
                return

            if path == '/api/pdf/to-images':
                self._send_json(pdf_to_images(
                    path_str=data['path'],
                    fmt=data.get('format', 'png'),
                    dpi=data.get('dpi', 150),
                    pages_expr=data.get('pages', ''),
                ))
                return

            if path == '/api/pdf/from-images':
                self._send_json(images_to_pdf(data.get('paths', [])))
                return

            if path == '/api/pdf/compress':
                self._send_json(compress_pdf(data['path'], level=data.get('level', 'balanced')))
                return

            if path == '/api/pdf/to-word':
                self._send_json(pdf_to_word(data['path']))
                return

            if path == '/api/pdf/from-word':
                self._send_json(word_to_pdf(data['path']))
                return

            if path == '/api/pdf/protect':
                self._send_json(protect_pdf(
                    path_str=data['path'],
                    user_pw=data.get('user_pw', ''),
                    owner_pw=data.get('owner_pw', ''),
                    allow_print=bool(data.get('allow_print', True)),
                    allow_copy=bool(data.get('allow_copy', True)),
                ))
                return

            if path == '/api/pdf/unlock':
                self._send_json(unlock_pdf(
                    path_str=data['path'],
                    password=data.get('password', ''),
                ))
                return

            # ---- 编码修复 / ZIP 修复 / 文件哈希 ----
            if path == '/api/file/zip-fix':
                self._send_json(fix_zip_encoding(
                    path_str=data['path'],
                    source_encoding=data.get('source_encoding', 'auto'),
                ))
                return

            if path == '/api/file/text-fix':
                self._send_json(fix_text_encoding(
                    path_str=data['path'],
                    source_encoding=data.get('source_encoding', 'auto'),
                    target_encoding=data.get('target_encoding', 'utf-8'),
                ))
                return

            if path == '/api/file/hash':
                self._send_json(calc_file_hash(data['path']))
                return

            # ---- 批量重命名 ----
            if path == '/api/rename/preview':
                res = preview_batch_rename(
                    folder=data.get('folder', ''),
                    find_text=data.get('find', ''),
                    replace_text=data.get('replace', ''),
                    prefix=data.get('prefix', ''),
                    suffix=data.get('suffix', ''),
                    use_regex=bool(data.get('use_regex', False)),
                    numbering=bool(data.get('numbering', False)),
                    start_num=int(data.get('start_num') or 1),
                    pad_digits=int(data.get('pad_digits') or 2),
                    ext_filter=data.get('ext_filter', ''),
                    new_ext=data.get('new_ext', ''),
                    ext_case=data.get('ext_case', ''),
                )
                self._send_json(res)
                return

            if path == '/api/rename/execute':
                res = execute_batch_rename(data.get('folder', ''), data.get('items', []))
                self._send_json(res)
                return

            self._send_json({'error': '未知接口'}, 404)
        except Exception as err:
            log.warning('POST %s 失败: %s', path, err)
            self._send_json({'error': str(err)}, 400)


def create_server(start_port=DEFAULT_PORT):
    ensure_dirs()
    cleanup_old_uploads()
    for port in range(start_port, start_port + PORT_SPAN):
        try:
            httpd = ThreadingHTTPServer(('127.0.0.1', port), ToolboxHandler)
            httpd.daemon_threads = True
            httpd.api_token = secrets.token_hex(16)
            httpd.allowed_paths = set()
            httpd.on_shutdown = None
            return httpd, port
        except OSError:
            continue
    raise RuntimeError('找不到可用的本地端口')


if __name__ == '__main__':
    srv, p = create_server()
    print(f'DeskKit 已启动: http://127.0.0.1:{p}')
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        video_tasks.cancel_all()
        srv.server_close()
