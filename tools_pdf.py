"""PDF 工坊（基于 PyMuPDF 与本机 Word）：合并、拆分/提取/删页、旋转、转图、压缩、PDF↔Word 互转。"""
from pathlib import Path
import subprocess
import zipfile

import pymupdf
from PIL import Image, ImageOps

from tools_files import OUTPUT_DIR, clean_stem, unique_path

Image.MAX_IMAGE_PIXELS = 1_000_000_000
_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def _clean_stem(path):
    return clean_stem(path)


def parse_pages(expr, total_pages):
    """解析如 '1-3, 5, 8-10' 的 1-based 页码表达式，返回去重保序的 0-based 页码列表。"""
    if not expr or not expr.strip():
        return list(range(total_pages))
    result = []
    seen = set()
    for part in expr.replace('，', ',').split(','):
        part = part.strip()
        if not part:
            continue
        if '-' in part:
            a, b = part.split('-', 1)
            raw_start, raw_end = int(a.strip()), int(b.strip())
            if raw_start <= raw_end:
                if raw_end < 1 or raw_start > total_pages:
                    continue
                start, end, step = max(1, raw_start), min(total_pages, raw_end), 1
            else:
                if raw_start < 1 or raw_end > total_pages:
                    continue
                start, end, step = min(total_pages, raw_start), max(1, raw_end), -1
            for p in range(start, end + step, step):
                idx = p - 1
                if 0 <= idx < total_pages and idx not in seen:
                    seen.add(idx)
                    result.append(idx)
        else:
            idx = int(part) - 1
            if 0 <= idx < total_pages and idx not in seen:
                seen.add(idx)
                result.append(idx)
    return result


def pdf_info(path_str):
    path = Path(path_str)
    with pymupdf.open(path) as doc:
        w = round(doc[0].rect.width) if len(doc) else 0
        h = round(doc[0].rect.height) if len(doc) else 0
        return {
            'name': _clean_stem(path) + path.suffix,
            'path': str(path),
            'pages': len(doc),
            'size_bytes': path.stat().st_size,
            'page_size': f'{w} × {h} pt',
        }


def merge_pdfs(paths, out_dir=None):
    if len(paths) < 2:
        raise ValueError('请至少选择 2 个 PDF 文件进行合并')
    out_dir = Path(out_dir or OUTPUT_DIR)
    out_path = unique_path(out_dir, '合并文档', '.pdf')
    merged = pymupdf.open()
    try:
        for p in paths:
            with pymupdf.open(p) as src:
                merged.insert_pdf(src)
        merged.save(out_path, garbage=3, deflate=True)
        pages = len(merged)
    finally:
        merged.close()
    return {
        'name': out_path.name,
        'path': str(out_path),
        'pages': pages,
        'output_size': out_path.stat().st_size,
        'output_dir': str(out_dir),
    }


def edit_pages(path_str, action, pages_expr='', angle=90, out_dir=None):
    """提取页 / 删除页 / 旋转页 / 按页拆分为多个 PDF。"""
    out_dir = Path(out_dir or OUTPUT_DIR)
    stem = _clean_stem(path_str)
    with pymupdf.open(path_str) as doc:
        total = len(doc)
        selected = parse_pages(pages_expr, total)

        if action == 'extract':
            if not selected:
                raise ValueError('未匹配到任何有效页码')
            out_path = unique_path(out_dir, f'{stem}_提取', '.pdf')
            out_doc = pymupdf.open()
            for idx in selected:
                out_doc.insert_pdf(doc, from_page=idx, to_page=idx)
            out_doc.save(out_path, garbage=3, deflate=True)
            out_doc.close()
            return {'name': out_path.name, 'path': str(out_path), 'pages': len(selected),
                    'output_size': out_path.stat().st_size, 'output_dir': str(out_dir)}

        if action == 'delete':
            remove_set = set(selected)
            keep = [i for i in range(total) if i not in remove_set]
            if not keep:
                raise ValueError('不能删除全部页面')
            out_path = unique_path(out_dir, f'{stem}_删页', '.pdf')
            out_doc = pymupdf.open()
            for idx in keep:
                out_doc.insert_pdf(doc, from_page=idx, to_page=idx)
            out_doc.save(out_path, garbage=3, deflate=True)
            out_doc.close()
            return {'name': out_path.name, 'path': str(out_path), 'pages': len(keep),
                    'output_size': out_path.stat().st_size, 'output_dir': str(out_dir)}

        if action == 'rotate':
            angle = int(angle or 90) % 360
            for idx in selected:
                page = doc[idx]
                page.set_rotation((page.rotation + angle) % 360)
            out_path = unique_path(out_dir, f'{stem}_旋转', '.pdf')
            doc.save(out_path, garbage=3, deflate=True)
            return {'name': out_path.name, 'path': str(out_path), 'pages': total,
                    'output_size': out_path.stat().st_size, 'output_dir': str(out_dir)}

        if action == 'split_all':
            out_paths = []
            for idx in selected:
                p = unique_path(out_dir, f'{stem}_第{idx + 1}页', '.pdf')
                single = pymupdf.open()
                single.insert_pdf(doc, from_page=idx, to_page=idx)
                single.save(p, garbage=3, deflate=True)
                single.close()
                out_paths.append(p)
            zip_path = unique_path(out_dir, f'{stem}_拆分全部', '.zip')
            with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
                for p in out_paths:
                    zf.write(p, arcname=p.name)
            return {'name': zip_path.name, 'path': str(zip_path), 'pages': len(out_paths),
                    'output_size': zip_path.stat().st_size, 'output_dir': str(out_dir)}

        raise ValueError(f'不支持的 PDF 操作: {action}')


def pdf_to_images(path_str, fmt='png', dpi=150, pages_expr='', out_dir=None):
    out_dir = Path(out_dir or OUTPUT_DIR)
    stem = _clean_stem(path_str)
    dpi = max(72, min(300, int(dpi or 150)))
    ext = '.jpg' if fmt.lower() in ('jpg', 'jpeg') else '.png'

    out_paths = []
    with pymupdf.open(path_str) as doc:
        selected = parse_pages(pages_expr, len(doc))
        if not selected:
            raise ValueError('未匹配到任何有效页码')
        for idx in selected:
            pix = doc[idx].get_pixmap(dpi=dpi, alpha=False)
            p = unique_path(out_dir, f'{stem}_p{idx + 1}', ext)
            pix.save(str(p))
            out_paths.append(p)

    if len(out_paths) == 1:
        p = out_paths[0]
        return {'name': p.name, 'path': str(p), 'count': 1,
                'output_size': p.stat().st_size, 'output_dir': str(out_dir)}

    zip_path = unique_path(out_dir, f'{stem}_导出图片', '.zip')
    with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        for p in out_paths:
            zf.write(p, arcname=p.name)
    return {'name': zip_path.name, 'path': str(zip_path), 'count': len(out_paths),
            'output_size': zip_path.stat().st_size, 'output_dir': str(out_dir)}


def images_to_pdf(paths, out_dir=None):
    if not paths:
        raise ValueError('请至少选择 1 张图片')
    out_dir = Path(out_dir or OUTPUT_DIR)
    out_path = unique_path(out_dir, '图片合成文档', '.pdf')
    doc = pymupdf.open()
    try:
        for p in paths:
            with Image.open(p) as raw:
                img = ImageOps.exif_transpose(raw).convert('RGB')
                w, h = img.size
                # 按 A4 长边 842pt（297mm）等比缩放页面尺寸，避免高像素图生成数米巨型 PDF 页
                scale = min(1.0, 842.0 / max(w, h)) if max(w, h) > 0 else 1.0
                pw, ph = round(w * scale, 2), round(h * scale, 2)
                import io
                buf = io.BytesIO()
                img.save(buf, format='JPEG', quality=92)
                page = doc.new_page(width=pw, height=ph)
                page.insert_image(pymupdf.Rect(0, 0, pw, ph), stream=buf.getvalue())
        doc.save(out_path, garbage=3, deflate=True)
        pages = len(doc)
    finally:
        doc.close()
    return {'name': out_path.name, 'path': str(out_path), 'pages': pages,
            'output_size': out_path.stat().st_size, 'output_dir': str(out_dir)}


def compress_pdf(path_str, level='balanced', out_dir=None):
    """压缩 PDF：无损结构清理，或中/强档位重采样压缩内嵌图片。"""
    out_dir = Path(out_dir or OUTPUT_DIR)
    src = Path(path_str)
    in_size = src.stat().st_size
    out_path = unique_path(out_dir, f'{_clean_stem(src)}_压缩', '.pdf')

    with pymupdf.open(src) as doc:
        if level in ('balanced', 'strong'):
            dpi = 144 if level == 'balanced' else 108
            qual = 75 if level == 'balanced' else 58
            doc.rewrite_images(dpi_threshold=dpi + 20, dpi_target=dpi, quality=qual,
                               lossy=True, lossless=True, bitonal=False)
        doc.save(out_path, garbage=4, deflate=True, clean=True)

    out_size = out_path.stat().st_size
    return {
        'name': out_path.name,
        'path': str(out_path),
        'input_size': in_size,
        'output_size': out_size,
        'saved_pct': round((1 - out_size / in_size) * 100, 1) if in_size else 0,
        'output_dir': str(out_dir),
    }


def _word_convert(src_path, dst_path, wd_format):
    """通过独立 PowerShell STA 进程调用本机 Microsoft Word COM 导出 PDF（超时精准清理本次拉起的 WINWORD 进程）。"""
    import tempfile
    import uuid

    pid_file = Path(tempfile.gettempdir()) / f'toolbox_word_{uuid.uuid4().hex[:8]}.pid'
    ps_script = (
        '$ErrorActionPreference = "Stop"\n'
        '$src = $args[0]; $dst = $args[1]; $fmt = [int]$args[2]; $pidFile = $args[3]\n'
        '$word = $null; $doc = $null\n'
        'try {\n'
        '    $before = @(Get-Process -Name WINWORD -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id)\n'
        '    $word = New-Object -ComObject Word.Application\n'
        '    $after = @(Get-Process -Name WINWORD -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id)\n'
        '    $newPids = $after | Where-Object { $before -notcontains $_ }\n'
        '    if ($newPids) { ($newPids -join ",") | Set-Content -Path $pidFile -Encoding ASCII }\n'
        '    $word.Visible = $false\n'
        '    $word.DisplayAlerts = 0\n'
        '    $doc = $word.Documents.Open($src, $false, $true, $false)\n'
        '    $doc.ExportAsFixedFormat($dst, $fmt)\n'
        '} finally {\n'
        '    if ($doc) { try { $doc.Close($false) } catch {} }\n'
        '    if ($word) { try { $word.Quit() } catch {} }\n'
        '}\n'
    )
    try:
        proc = subprocess.Popen(
            ['powershell.exe', '-NoProfile', '-NonInteractive', '-STA', '-Command',
             f'& {{ {ps_script} }}', str(src_path), str(dst_path), str(wd_format), str(pid_file)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding='utf-8', errors='replace', creationflags=_NO_WINDOW,
        )
        try:
            stdout, stderr = proc.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            # 仅精准结束本次 COM 启动的 WINWORD.EXE，不误杀用户自己打开的 Word 文档
            if pid_file.exists():
                for raw_pid in pid_file.read_text(encoding='ascii', errors='ignore').split(','):
                    raw_pid = raw_pid.strip()
                    if raw_pid.isdigit():
                        subprocess.run(
                            ['taskkill', '/F', '/PID', raw_pid],
                            capture_output=True, creationflags=_NO_WINDOW,
                        )
            raise RuntimeError('Word 后台转换超时（可能是 Office 首次启动或弹出授权提示），请先手动打开一次 Word 后重试')
    finally:
        pid_file.unlink(missing_ok=True)
    if proc.returncode != 0 or not Path(dst_path).exists():
        detail = (stderr or stdout or '').strip().splitlines()
        msg = detail[-1] if detail else 'Word 转换失败，请确认已安装 Microsoft Word 且文件未加密损坏'
        raise RuntimeError(msg)


def pdf_to_word(path_str, out_dir=None):
    """使用 pdf2docx（纯本地零弹窗）将 PDF 转为可编辑 Word (.docx)。"""
    from pdf2docx import Converter

    out_dir = Path(out_dir or OUTPUT_DIR)
    src = Path(path_str).resolve()
    if not src.exists():
        raise FileNotFoundError('PDF 文件不存在')

    # 快速检测是否包含文字层（仅检查前 5 页）
    has_text = False
    with pymupdf.open(src) as doc:
        pages = len(doc)
        for i in range(min(pages, 5)):
            if doc[i].get_text('text').strip():
                has_text = True
                break

    out_path = unique_path(out_dir, f'{_clean_stem(src)}', '.docx')
    cv = Converter(str(src))
    try:
        cv.convert(str(out_path))
    finally:
        cv.close()
    return {
        'name': out_path.name,
        'path': str(out_path),
        'pages': pages,
        'is_scanned': not has_text,
        'output_size': out_path.stat().st_size,
        'output_dir': str(out_dir),
    }


def word_to_pdf(path_str, out_dir=None):
    """将 Word (.docx / .doc) 原生无损转为 PDF。"""
    out_dir = Path(out_dir or OUTPUT_DIR)
    src = Path(path_str).resolve()
    if not src.exists():
        raise FileNotFoundError('Word 文件不存在')
    out_path = unique_path(out_dir, f'{_clean_stem(src)}', '.pdf')
    _word_convert(src, out_path, 17)  # 17 = wdExportFormatPDF
    with pymupdf.open(out_path) as doc:
        pages = len(doc)
    return {
        'name': out_path.name,
        'path': str(out_path),
        'pages': pages,
        'output_size': out_path.stat().st_size,
        'output_dir': str(out_dir),
    }
