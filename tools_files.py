"""本机文件与目录管理：输出目录、临时上传、系统文件弹窗、打开目录、批量重命名。"""
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

OUTPUT_DIR = Path.home() / 'Downloads' / '工具箱输出'
UPLOAD_DIR = Path(tempfile.gettempdir()) / 'local_toolbox_uploads'
UPLOAD_PREFIX = '__tb_'


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


def cleanup_old_uploads(max_age_seconds=86400):
    """清理超过一天的临时上传文件，避免占用 C 盘空间。"""
    if not UPLOAD_DIR.exists():
        return
    now = time.time()
    for item in UPLOAD_DIR.iterdir():
        try:
            if now - item.stat().st_mtime > max_age_seconds:
                if item.is_dir():
                    shutil.rmtree(item, ignore_errors=True)
                else:
                    item.unlink(missing_ok=True)
        except OSError:
            pass


_WIN_RESERVED_NAMES = {
    'CON', 'PRN', 'AUX', 'NUL',
    *(f'COM{i}' for i in range(1, 10)),
    *(f'LPT{i}' for i in range(1, 10)),
}


def safe_filename(name):
    """清洗文件名中的非法字符并规避 Windows 设备保留名（CON/NUL/PRN/COM1 等）。"""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', (name or 'file').strip())
    cleaned = cleaned.strip('. ') or 'file'
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


def unique_path(directory, stem, ext):
    """在目标目录生成不重名的文件路径。"""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    stem = safe_filename(stem)
    if ext and not ext.startswith('.'):
        ext = '.' + ext
    candidate = directory / f'{stem}{ext}'
    idx = 2
    while candidate.exists():
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


def open_in_explorer(path_str):
    """在资源管理器中打开输出目录或选中输出目录内的指定文件。"""
    ensure_dirs()
    target = Path(path_str).resolve() if path_str else OUTPUT_DIR.resolve()
    if not is_within(target, OUTPUT_DIR):
        raise ValueError('仅允许打开工具箱输出目录内的路径')
    if not target.exists():
        target = OUTPUT_DIR.resolve()
    if target.is_file():
        subprocess.Popen(['explorer.exe', '/select,', str(target)])
    else:
        os.startfile(str(target))


def _run_dialog_script(script, payload):
    """通过独立子进程执行文件/文件夹弹窗，并用临时 UTF-8 JSON 文件回传结果（兼容 pythonw 无 stdout）。"""
    ensure_dirs()
    out_file = UPLOAD_DIR / f'dialog_{uuid.uuid4().hex[:8]}.json'
    creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    try:
        subprocess.run(
            [sys.executable, '-B', '-c', script, json.dumps(payload, ensure_ascii=False), str(out_file)],
            creationflags=creationflags,
        )
        if out_file.exists():
            return json.loads(out_file.read_text(encoding='utf-8'))
    finally:
        out_file.unlink(missing_ok=True)
    return None


def pick_files(title='选择文件', filetypes=None, multiple=False):
    """通过独立 Python 子进程调用系统文件选择框，避免在 HTTP 线程操作 Tk 死锁。"""
    filetypes = filetypes or [('所有文件', '*.*')]
    script = (
        'import ctypes, json, pathlib, sys, tkinter as tk\n'
        'from tkinter import filedialog\n'
        'try: ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)\n'
        'except Exception: pass\n'
        'root = tk.Tk(); root.withdraw(); root.attributes("-topmost", True)\n'
        'cfg = json.loads(sys.argv[1])\n'
        'fts = [tuple(x) for x in cfg["filetypes"]]\n'
        'if cfg["multiple"]:\n'
        '    res = list(filedialog.askopenfilenames(title=cfg["title"], filetypes=fts))\n'
        'else:\n'
        '    p = filedialog.askopenfilename(title=cfg["title"], filetypes=fts)\n'
        '    res = [p] if p else []\n'
        'pathlib.Path(sys.argv[2]).write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")\n'
    )
    res = _run_dialog_script(script, {'title': title, 'filetypes': filetypes, 'multiple': multiple})
    return res if isinstance(res, list) else []


def pick_folder(title='选择文件夹'):
    """调用系统文件夹选择框。"""
    script = (
        'import ctypes, json, pathlib, sys, tkinter as tk\n'
        'from tkinter import filedialog\n'
        'try: ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)\n'
        'except Exception: pass\n'
        'root = tk.Tk(); root.withdraw(); root.attributes("-topmost", True)\n'
        'cfg = json.loads(sys.argv[1])\n'
        'p = filedialog.askdirectory(title=cfg["title"])\n'
        'pathlib.Path(sys.argv[2]).write_text(json.dumps(p or "", ensure_ascii=False), encoding="utf-8")\n'
    )
    res = _run_dialog_script(script, {'title': title})
    return res if isinstance(res, str) else ''


def preview_batch_rename(folder, find_text='', replace_text='', prefix='', suffix='',
                         use_regex=False, numbering=False, start_num=1, pad_digits=2,
                         ext_filter='', new_ext=''):
    """预览文件夹内文件的批量重命名结果，并检查重名冲突。"""
    base = Path(folder)
    if not base.exists() or not base.is_dir():
        raise ValueError('请选择有效的本地文件夹路径')

    allowed_exts = {
        ('.' + e.strip().lstrip('.').lower())
        for e in ext_filter.split(',') if e.strip()
    } if ext_filter.strip() else set()

    files = sorted([p for p in base.iterdir() if p.is_file()], key=lambda p: p.name.lower())
    if allowed_exts:
        files = [p for p in files if p.suffix.lower() in allowed_exts]

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
        new_name = safe_filename(stem) + ext
        changed = new_name != f.name
        key = new_name.lower()
        conflict = key in seen_lower
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
