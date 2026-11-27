"""本机文件与目录管理：输出目录、临时上传、系统文件弹窗、打开目录、批量重命名、ZIP/文本乱码修复、文件哈希校验。"""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
import winreg
import zipfile
import zlib

_SHELL_FOLDERS_KEY = r'Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders'
_DOWNLOADS_GUID = '{374DE290-123F-4565-9164-39C4925E467B}'


def _resolve_downloads_dir():
    """读取系统注册表真实「下载」文件夹路径（兼容用户将下载目录迁移到 D/E 盘的场景）。"""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _SHELL_FOLDERS_KEY) as key:
            raw, _ = winreg.QueryValueEx(key, _DOWNLOADS_GUID)
        if isinstance(raw, str) and raw.strip():
            expanded = Path(os.path.expandvars(raw.strip()))
            if expanded.exists() or expanded.anchor and Path(expanded.anchor).exists():
                return expanded
    except OSError:
        pass
    return Path.home() / 'Downloads'


OUTPUT_DIR = _resolve_downloads_dir() / '工具箱输出'
UPLOAD_DIR = Path(tempfile.gettempdir()) / 'local_toolbox_uploads'
UPLOAD_PREFIX = '__tb_'
IS_FROZEN = getattr(sys, 'frozen', False)
_last_upload_cleanup = 0.0


def is_within(path, root):
    """安全判断 path 是否位于 root 目录内（使用 Path.is_relative_to，防止同名前缀目录绕过）。"""
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


def ensure_dirs():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    return OUTPUT_DIR, UPLOAD_DIR


def cleanup_old_uploads(max_age_seconds=7200, protected_paths=None):
    """清理过期的临时上传副本（跳过正在排队或处理中的活跃任务文件），防止长期占用 C 盘空间。"""
    global _last_upload_cleanup
    _last_upload_cleanup = time.monotonic()
    if not UPLOAD_DIR.exists():
        return 0
    protected = {
        os.path.normcase(str(Path(p).resolve()))
        for p in (protected_paths or ())
        if p
    }
    now = time.time()
    removed = 0
    for item in UPLOAD_DIR.iterdir():
        try:
            norm = os.path.normcase(str(item.resolve()))
            if norm in protected:
                continue
            if max_age_seconds <= 0 or (now - item.stat().st_mtime > max_age_seconds):
                if item.is_dir():
                    shutil.rmtree(item, ignore_errors=True)
                else:
                    item.unlink(missing_ok=True)
                removed += 1
        except OSError:
            pass
    return removed


def maybe_cleanup_uploads(interval_seconds=600, max_age_seconds=7200, protected_paths=None):
    """节流执行临时上传清理（运行期间每 10 分钟最多扫描一次）。"""
    if time.monotonic() - _last_upload_cleanup >= interval_seconds:
        cleanup_old_uploads(max_age_seconds=max_age_seconds, protected_paths=protected_paths)


def touch_upload_if_temp(path_str):
    """当访问或排队使用上传目录内的临时文件时，刷新其修改时间以避免中途被过期回收。"""
    if not path_str:
        return
    try:
        p = Path(path_str)
        if p.is_file() and is_within(p, UPLOAD_DIR):
            os.utime(p, None)
    except OSError:
        pass


_WIN_RESERVED_NAMES = {
    'CON', 'PRN', 'AUX', 'NUL',
    *(f'COM{i}' for i in range(1, 10)),
    *(f'LPT{i}' for i in range(1, 10)),
}


def safe_filename(name):
    """清洗文件名中的非法字符并规避 Windows 设备保留名（保留 .env / .gitignore 等合法开头点号）。"""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', (name or 'file').strip())
    # Windows 仅禁止文件名末尾点号或空格；开头点号（如 .env、.gitignore）合法，不可吞掉
    cleaned = cleaned.rstrip('. ').lstrip(' ')
    if not cleaned or cleaned in ('.', '..'):
        cleaned = 'file'
    stem_head = cleaned.split('.', 1)[0].upper()
    if stem_head in _WIN_RESERVED_NAMES:
        cleaned = f'_{cleaned}'
    return cleaned


def clean_stem(path):
    """仅剥离本工具箱上传临时文件的专属前缀（__tb_<8hex>_），不误伤用户真实文件名。"""
    stem = Path(path).stem
    if stem.startswith(UPLOAD_PREFIX) and len(stem) > len(UPLOAD_PREFIX) + 9:
        rest = stem[len(UPLOAD_PREFIX):]
        if rest[8] == '_' and all(c in '0123456789abcdef' for c in rest[:8]):
            return rest[9:]
    return stem


def unique_path(directory, stem, ext, reserved=None):
    """在目标目录生成不重名的文件路径（可选避开队列已预留但尚未落盘的路径集合）。"""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    stem = safe_filename(stem)
    if ext and not ext.startswith('.'):
        ext = '.' + ext
    reserved_norm = reserved if isinstance(reserved, set) else set()
    candidate = directory / f'{stem}{ext}'
    idx = 2
    while candidate.exists() or os.path.normcase(str(candidate.resolve())) in reserved_norm:
        candidate = directory / f'{stem}_{idx}{ext}'
        idx += 1
    return candidate


def save_upload(filename, data_bytes):
    """保存前端上传的文件到临时目录并返回绝对路径。"""
    ensure_dirs()
    token = uuid.uuid4().hex[:8]
    safe = safe_filename(Path(filename).name)
    target = UPLOAD_DIR / f'{UPLOAD_PREFIX}{token}_{safe}'
    target.write_bytes(data_bytes)
    return target


def _select_file_via_shell(file_path):
    """使用 Windows Shell PIDL 原生 API 打开文件夹并高亮文件（完美兼容含英文逗号、空格、等号的文件名）。"""
    try:
        ole32 = ctypes.WinDLL('ole32')
        shell32 = ctypes.WinDLL('shell32')
        ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        ole32.CoInitializeEx.restype = ctypes.c_long
        ole32.CoUninitialize.argtypes = []
        ole32.CoUninitialize.restype = None
        shell32.ILCreateFromPathW.argtypes = [ctypes.c_wchar_p]
        shell32.ILCreateFromPathW.restype = ctypes.c_void_p
        shell32.ILFree.argtypes = [ctypes.c_void_p]
        shell32.ILFree.restype = None
        shell32.SHOpenFolderAndSelectItems.argtypes = [
            ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint32,
        ]
        shell32.SHOpenFolderAndSelectItems.restype = ctypes.c_long

        hr_init = ole32.CoInitializeEx(None, 0x2)
        try:
            pidl = shell32.ILCreateFromPathW(str(file_path))
            if pidl:
                try:
                    if shell32.SHOpenFolderAndSelectItems(pidl, 0, None, 0) == 0:
                        return True
                finally:
                    shell32.ILFree(pidl)
        finally:
            if hr_init in (0, 1):
                ole32.CoUninitialize()
    except OSError:
        pass
    return False


def open_in_explorer(path_str):
    """在资源管理器中打开输出目录或选中输出目录内的指定文件。"""
    ensure_dirs()
    target = Path(path_str).resolve() if path_str else OUTPUT_DIR.resolve()
    if not is_within(target, OUTPUT_DIR):
        raise ValueError('仅允许打开工具箱输出目录内的路径')
    if not target.exists():
        target = OUTPUT_DIR.resolve()
    if target.is_file():
        if not _select_file_via_shell(target):
            no_win = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
            subprocess.Popen(f'explorer.exe /select,"{target}"', creationflags=no_win)
    else:
        os.startfile(str(target))


def run_tk_dialog_from_args(kind, payload_json, out_file_str):
    """在独立子进程内弹出高 DPI 系统文件/文件夹选择框，并将结果以 UTF-8 JSON 写入临时文件。"""
    import ctypes
    import tkinter as tk
    from tkinter import filedialog
    try:
        ctypes.WinDLL('shcore').SetProcessDpiAwareness(2)
    except Exception:
        pass
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    cfg = json.loads(payload_json)
    if kind == 'files':
        fts = [tuple(x) for x in (cfg.get('filetypes') or [('所有文件', '*.*')])]
        if cfg.get('multiple'):
            res = list(filedialog.askopenfilenames(title=cfg.get('title', '选择文件'), filetypes=fts))
        else:
            p = filedialog.askopenfilename(title=cfg.get('title', '选择文件'), filetypes=fts)
            res = [p] if p else []
    else:
        res = filedialog.askdirectory(title=cfg.get('title', '选择文件夹')) or ''
    Path(out_file_str).write_text(json.dumps(res, ensure_ascii=False), encoding='utf-8')
    root.destroy()


def _run_dialog_subprocess(kind, payload):
    """通过独立子进程执行文件/文件夹弹窗（同时兼容源码脚本与 PyInstaller 单文件 exe）。"""
    ensure_dirs()
    out_file = UPLOAD_DIR / f'dialog_{uuid.uuid4().hex[:8]}.json'
    creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    payload_str = json.dumps(payload, ensure_ascii=False)
    if IS_FROZEN:
        cmd = [sys.executable, '--dialog', kind, payload_str, str(out_file)]
    else:
        cmd = [sys.executable, '-B', str(Path(__file__).resolve()), '--dialog', kind, payload_str, str(out_file)]
    try:
        subprocess.run(cmd, creationflags=creationflags)
        if out_file.exists():
            return json.loads(out_file.read_text(encoding='utf-8'))
    finally:
        out_file.unlink(missing_ok=True)
    return None


def pick_files(title='选择文件', filetypes=None, multiple=False):
    """通过独立子进程调用系统文件选择框，避免在 HTTP 线程操作 Tk 死锁。"""
    filetypes = filetypes or [('所有文件', '*.*')]
    res = _run_dialog_subprocess('files', {'title': title, 'filetypes': filetypes, 'multiple': bool(multiple)})
    return res if isinstance(res, list) else []


def pick_folder(title='选择文件夹'):
    """调用系统文件夹选择框。"""
    res = _run_dialog_subprocess('folder', {'title': title})
    return res if isinstance(res, str) else ''


def preview_batch_rename(folder, find_text='', replace_text='', prefix='', suffix='',
                         use_regex=False, numbering=False, start_num=1, pad_digits=2,
                         ext_filter='', new_ext='', ext_case=''):
    """预览文件夹内文件的批量重命名结果，并检查重名冲突。"""
    base = Path(folder)
    if not base.exists() or not base.is_dir():
        raise ValueError('请选择有效的本地文件夹路径')

    allowed_exts = {
        ('.' + e.strip().lstrip('.').lower())
        for e in ext_filter.split(',') if e.strip()
    } if ext_filter.strip() else set()

    all_files = sorted([p for p in base.iterdir() if p.is_file()], key=lambda p: p.name.lower())
    if allowed_exts:
        files = [p for p in all_files if p.suffix.lower() in allowed_exts]
        selected_lower = {p.name.lower() for p in files}
        existing_unselected = {p.name.lower() for p in all_files if p.name.lower() not in selected_lower}
    else:
        files = all_files
        existing_unselected = set()

    regex = None
    if find_text and use_regex:
        try:
            regex = re.compile(find_text)
        except re.error as err:
            raise ValueError(f'正则表达式有误: {err}')

    items = []
    seen_lower = set()
    conflict_count = 0
    for idx, f in enumerate(files):
        stem = f.stem
        ext = f.suffix
        if find_text:
            if regex:
                stem = regex.sub(replace_text, stem)
            else:
                stem = stem.replace(find_text, replace_text)
        if prefix:
            stem = prefix + stem
        if suffix:
            stem = stem + suffix
        if numbering:
            num_str = str(start_num + idx).zfill(max(1, min(12, int(pad_digits))))
            stem = f'{stem}_{num_str}' if stem else num_str
        if new_ext.strip():
            ext = '.' + new_ext.strip().lstrip('.')
        if ext_case == 'lower':
            ext = ext.lower()
        elif ext_case == 'upper':
            ext = ext.upper()
        new_name = safe_filename(stem) + ext
        changed = new_name != f.name
        key = new_name.lower()
        conflict = (key in seen_lower) or (key in existing_unselected)
        seen_lower.add(key)
        if conflict:
            conflict_count += 1
        items.append({
            'old_name': f.name,
            'new_name': new_name,
            'changed': changed,
            'conflict': conflict,
        })
    return {
        'folder': str(base),
        'total': len(items),
        'changed': sum(1 for i in items if i['changed']),
        'conflicts': conflict_count,
        'items': items,
    }


def _validate_direct_child_name(name, label):
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f'{label}不能为空')
    if '/' in name or '\\' in name or name in ('.', '..') or '..' in Path(name).parts:
        raise ValueError(f'{label}包含非法路径字符: {name}')
    return name


def execute_batch_rename(folder, items):
    """两阶段执行批量重命名（先临时名再目标名），并在服务端严格校验所有文件名不越界。"""
    base = Path(folder).resolve()
    if not base.exists() or not base.is_dir():
        raise ValueError('目标文件夹不存在')
    changes = [i for i in items if i.get('changed') and not i.get('conflict')]
    if not changes:
        return {'renamed': 0}

    validated = []
    seen_targets = set()
    for c in changes:
        old_name = _validate_direct_child_name(c.get('old_name', ''), '原文件名')
        raw_new = _validate_direct_child_name(c.get('new_name', ''), '新文件名')
        new_p = Path(raw_new)
        new_name = safe_filename(new_p.stem) + new_p.suffix
        if new_name != raw_new or '/' in new_name or '\\' in new_name:
            raise ValueError(f'新文件名不合法: {raw_new}')
        src = (base / old_name).resolve()
        dst = (base / new_name).resolve()
        if src.parent != base or dst.parent != base:
            raise ValueError('禁止跨目录重命名文件')
        key = new_name.lower()
        if key in seen_targets:
            raise ValueError('存在重名冲突，请调整命名规则后再执行')
        seen_targets.add(key)
        validated.append((src, dst))

    temp_map = []
    done_map = []
    token = uuid.uuid4().hex[:6]
    try:
        for idx, (src, dst) in enumerate(validated):
            if not src.exists() or not src.is_file():
                continue
            tmp = base / f'.__rename_{token}_{idx}'
            src.rename(tmp)
            temp_map.append((src, tmp, dst))
        for src, tmp, dst in temp_map:
            if dst.exists():
                raise ValueError(f'目标文件已存在: {dst.name}')
            tmp.rename(dst)
            done_map.append((src, dst))
    except Exception:
        # 尽力回滚已完成与临时重命名的文件，避免残留临时名
        for src, dst in reversed(done_map):
            try:
                if dst.exists() and not src.exists():
                    dst.rename(src)
            except OSError:
                pass
        for src, tmp, _ in reversed(temp_map):
            try:
                if tmp.exists() and not src.exists():
                    tmp.rename(src)
            except OSError:
                pass
        raise
    return {'renamed': len(done_map)}


def _sanitize_zip_entry_name(name):
    """清洗 ZIP 条目相对路径，剥离前导斜杠与 .. 段，防御 Zip Slip。"""
    normalized = name.replace('\\', '/')
    is_dir = normalized.endswith('/')
    parts = [p for p in normalized.split('/') if p and p not in ('.', '..')]
    if not parts:
        return ''
    safe_parts = [safe_filename(p) for p in parts]
    result = '/'.join(safe_parts)
    return result + ('/' if is_dir else '')


def _score_decoded_sample(sample_text, enc):
    """基于东亚字符集常用字分区（GB2312 一级字 / Big5 第一字面 / 日文假名）评估解码可读性，避免 GB18030 超集盲目吞噬繁体或日文。"""
    score = 0.0
    for ch in sample_text:
        code = ord(ch)
        if code < 0x80:
            continue
        if 0xE000 <= code <= 0xF8FF or code == 0xFFFD or (code < 0x20 and ch not in '\r\n\t') or (0x7F <= code <= 0x9F):
            score -= 8.0
            continue
        if enc == 'gb18030':
            if 0x4E00 <= code <= 0x9FFF:
                try:
                    ch.encode('gb2312')
                    score += 3.0
                except UnicodeEncodeError:
                    score -= 1.5
            elif 0x3000 <= code <= 0x303F or 0xFF01 <= code <= 0xFF5E:
                score += 1.5
            else:
                score -= 1.5
        elif enc == 'big5':
            try:
                b = ch.encode('big5')
            except UnicodeEncodeError:
                score -= 4.0
                continue
            if len(b) == 2 and 0xA4 <= b[0] <= 0xC6:
                score += 3.2
            elif len(b) == 2 and 0xA1 <= b[0] <= 0xA3:
                score += 1.5
            else:
                score -= 1.2
        elif enc == 'shift_jis':
            if 0x3040 <= code <= 0x309F:
                score += 4.0
            elif 0x30A0 <= code <= 0x30FF:
                score += 2.8
            elif 0x4E00 <= code <= 0x9FFF:
                score += 2.0
            elif 0x3000 <= code <= 0x303F or 0xFF01 <= code <= 0xFF5E:
                score += 1.5
            elif 0xFF61 <= code <= 0xFF9F:
                score -= 2.5
            else:
                score -= 1.5
    return score


def _detect_legacy_encoding(raw_bytes):
    """自动识别无 BOM 字节流的真实编码，返回 (encoding_name, decoded_text)；均不合法时返回 (None, None)。"""
    try:
        return 'utf-8', raw_bytes.decode('utf-8')
    except UnicodeDecodeError:
        pass
    valid = []
    for idx, enc in enumerate(('gb18030', 'big5', 'shift_jis')):
        try:
            decoded = raw_bytes.decode(enc)
        except UnicodeDecodeError:
            continue
        sc = _score_decoded_sample(decoded[:4096], enc)
        valid.append((sc, -idx, enc, decoded))
    if not valid:
        return None, None
    valid.sort(reverse=True)
    _, _, best_enc, best_txt = valid[0]
    return best_enc, best_txt


def fix_zip_encoding(path_str, source_encoding='auto', out_dir=None):
    """修复 ZIP 压缩包内中文/日文文件名乱码，并重新打包为标准 UTF-8 ZIP。"""
    src = Path(path_str)
    if not src.exists():
        raise FileNotFoundError('ZIP 文件不存在')
    if not zipfile.is_zipfile(src):
        raise ValueError('该文件不是有效的 ZIP 压缩包')

    if source_encoding == 'auto':
        candidates = None
    else:
        import codecs
        try:
            codecs.lookup(source_encoding)
        except LookupError:
            raise ValueError(f'不支持的源编码: {source_encoding}')
        candidates = [source_encoding]

    out_dir = Path(out_dir or OUTPUT_DIR)
    out_path = unique_path(out_dir, f'{clean_stem(src)}_修复中文', '.zip')

    fixed_count = 0
    total_count = 0
    preview_items = []
    seen_names = set()
    max_entry_bytes = 256 * 1024 * 1024     # 单文件解压上限 256MB，防内存撑爆
    max_total_bytes = 2 * 1024 * 1024 * 1024  # 累计解压上限 2GB，防御 ZIP 炸弹
    total_unpacked = 0

    try:
        with zipfile.ZipFile(src, 'r') as zin, zipfile.ZipFile(out_path, 'w', compression=zipfile.ZIP_DEFLATED) as zout:
            infos = zin.infolist()
            if candidates is None:
                # 汇总包内非 UTF-8 标志的文件名字节样本做整体编码评分，提升短文件名繁体/日文识别率
                sample_chunks = []
                for inf in infos[:60]:
                    if not (inf.flag_bits & 0x800):
                        try:
                            b = inf.filename.encode('cp437')
                        except UnicodeEncodeError:
                            continue
                        try:
                            b.decode('utf-8')
                        except UnicodeDecodeError:
                            sample_chunks.append(b)
                if sample_chunks:
                    det_enc, _ = _detect_legacy_encoding(b'\n'.join(sample_chunks))
                else:
                    det_enc = None
                base_order = ['utf-8', 'gb18030', 'big5', 'shift_jis']
                if det_enc and det_enc != 'utf-8':
                    candidates = ['utf-8', det_enc] + [e for e in ('gb18030', 'big5', 'shift_jis') if e != det_enc]
                else:
                    candidates = base_order

            for info in infos:
                total_count += 1
                if not info.is_dir() and info.file_size > max_entry_bytes:
                    raise ValueError(f'压缩包内单个文件过大（超过 256MB）：{info.filename}')
                orig_name = info.filename
                new_name = orig_name
                if not (info.flag_bits & 0x800):
                    try:
                        raw_bytes = orig_name.encode('cp437')
                    except UnicodeEncodeError:
                        raw_bytes = None
                    if raw_bytes is not None:
                        for enc in candidates:
                            try:
                                decoded = raw_bytes.decode(enc)
                                new_name = decoded
                                break
                            except UnicodeDecodeError:
                                continue

                clean_name = _sanitize_zip_entry_name(new_name)
                if not clean_name:
                    continue
                # 防止重名覆盖
                if clean_name in seen_names:
                    p_obj = Path(clean_name.rstrip('/'))
                    suffix = '/' if clean_name.endswith('/') else p_obj.suffix
                    stem = p_obj.name if clean_name.endswith('/') else p_obj.stem
                    parent = str(p_obj.parent).replace('\\', '/')
                    idx = 2
                    while True:
                        cand = f'{stem}_{idx}{suffix}'
                        cand = f'{parent}/{cand}' if parent and parent != '.' else cand
                        if cand not in seen_names:
                            clean_name = cand
                            break
                        idx += 1
                seen_names.add(clean_name)

                changed = (clean_name != orig_name)
                if changed:
                    fixed_count += 1
                if len(preview_items) < 30:
                    preview_items.append({'old': orig_name, 'new': clean_name, 'changed': changed})

                dt = info.date_time
                if not dt or len(dt) < 6 or dt[0] < 1980 or dt[1] < 1 or dt[2] < 1:
                    dt = (1980, 1, 1, 0, 0, 0)
                new_info = zipfile.ZipInfo(filename=clean_name, date_time=dt)
                new_info.external_attr = info.external_attr
                new_info.compress_type = zipfile.ZIP_DEFLATED
                if clean_name.endswith('/'):
                    zout.writestr(new_info, b'')
                else:
                    try:
                        with zin.open(info, 'r') as src_stream, zout.open(new_info, 'w') as dst_stream:
                            entry_read = 0
                            while True:
                                chunk = src_stream.read(1024 * 1024)
                                if not chunk:
                                    break
                                entry_read += len(chunk)
                                total_unpacked += len(chunk)
                                if entry_read > max_entry_bytes:
                                    raise ValueError(f'压缩包内单文件解压体积超过 256MB 上限：{clean_name}')
                                if total_unpacked > max_total_bytes:
                                    raise ValueError('压缩包累计解压体积超过 2GB 上限，已中止以防内存/磁盘耗尽')
                                dst_stream.write(chunk)
                    except RuntimeError as err:
                        if 'encrypted' in str(err).lower():
                            raise ValueError('该 ZIP 压缩包已加密，暂不支持直接修复加密压缩包')
                        raise
    except Exception:
        out_path.unlink(missing_ok=True)
        raise

    return {
        'name': out_path.name,
        'path': str(out_path),
        'total': total_count,
        'fixed': fixed_count,
        'items': preview_items,
        'output_size': out_path.stat().st_size,
        'output_dir': str(out_dir),
    }


def fix_text_encoding(path_str, source_encoding='auto', target_encoding='utf-8', out_dir=None):
    """自动识别并修复文本/CSV/字幕等文件的编码乱码（支持输出标准 UTF-8 或 Excel 友好的 UTF-8 BOM）。"""
    src = Path(path_str)
    if not src.exists():
        raise FileNotFoundError('文件不存在')
    size = src.stat().st_size
    if size > 50 * 1024 * 1024:
        raise ValueError('文本文件超过 50MB 上限，请确认选择的是纯文本/CSV 文件')

    allowed_targets = {'utf-8', 'utf-8-sig', 'gb18030'}
    if target_encoding not in allowed_targets:
        raise ValueError(f'不支持的目标编码: {target_encoding}')

    raw = src.read_bytes()
    detected = source_encoding
    text = None

    if source_encoding == 'auto':
        if raw.startswith(b'\xef\xbb\xbf'):
            detected, text = 'utf-8-sig', raw.decode('utf-8-sig')
        elif raw.startswith((b'\xff\xfe', b'\xfe\xff')):
            detected, text = 'utf-16', raw.decode('utf-16')
        else:
            if b'\x00' in raw[:8192]:
                raise ValueError('检测到二进制文件内容，请选择纯文本或 CSV 文件')
            detected, text = _detect_legacy_encoding(raw)
            if text is None:
                raise ValueError('无法自动识别该文件的文本编码，请手动选择原文件编码后重试')
    else:
        try:
            text = raw.decode(source_encoding)
        except LookupError:
            raise ValueError(f'不支持的源编码: {source_encoding}')
        except UnicodeDecodeError:
            raise ValueError(f'无法使用 {source_encoding} 编码解析该文件，请尝试其他源编码')

    out_dir = Path(out_dir or OUTPUT_DIR)
    ext = src.suffix or '.txt'
    tag = 'UTF8BOM' if target_encoding == 'utf-8-sig' else target_encoding.upper().replace('-', '')
    out_path = unique_path(out_dir, f'{clean_stem(src)}_{tag}', ext)
    out_bytes = text.encode(target_encoding, errors='replace')
    out_path.write_bytes(out_bytes)

    preview_lines = text.splitlines()[:6]
    return {
        'name': out_path.name,
        'path': str(out_path),
        'detected_encoding': detected,
        'target_encoding': target_encoding,
        'preview': '\n'.join(preview_lines)[:600],
        'output_size': out_path.stat().st_size,
        'output_dir': str(out_dir),
    }


def calc_file_hash(path_str):
    """流式分块计算任意文件的 MD5、SHA1、SHA256 与 CRC32（大文件不占内存）。"""
    src = Path(path_str)
    if not src.exists() or not src.is_file():
        raise FileNotFoundError('文件不存在')
    md5 = hashlib.md5()
    sha1 = hashlib.sha1()
    sha256 = hashlib.sha256()
    crc = 0
    total = 0
    with open(src, 'rb') as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            md5.update(chunk)
            sha1.update(chunk)
            sha256.update(chunk)
            crc = zlib.crc32(chunk, crc)
            total += len(chunk)
    return {
        'name': clean_stem(src) + src.suffix,
        'path': str(src),
        'size_bytes': total,
        'md5': md5.hexdigest(),
        'sha1': sha1.hexdigest(),
        'sha256': sha256.hexdigest(),
        'crc32': f'{crc & 0xffffffff:08x}',
    }


if __name__ == '__main__' and len(sys.argv) >= 5 and sys.argv[1] == '--dialog':
    run_tk_dialog_from_args(sys.argv[2], sys.argv[3], sys.argv[4])
