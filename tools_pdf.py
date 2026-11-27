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


def _ensure_unlocked(doc, name=''):
    """检测加密 PDF 并给出统一友好的中文提示，避免抛出底层英文异常。"""
    if doc.needs_pass:
        prefix = f'「{name}」' if name else '该 PDF '
        raise ValueError(f'{prefix}已设置打开密码，请先在「加密 / 解锁」中解锁后再处理')


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
            try:
                raw_start, raw_end = int(a.strip()), int(b.strip())
            except ValueError:
                raise ValueError(f'页码范围格式有误: "{part}"（示例：1-3, 5）')
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
            try:
                idx = int(part) - 1
            except ValueError:
                raise ValueError(f'页码格式有误: "{part}"（请输入数字或区间，如 1-3, 5）')
            if 0 <= idx < total_pages and idx not in seen:
                seen.add(idx)
                result.append(idx)
    return result


def pdf_info(path_str):
    path = Path(path_str)
    with pymupdf.open(path) as doc:
        needs_pass = bool(doc.needs_pass)
        is_encrypted = bool(doc.is_encrypted)
        pages = 0 if needs_pass else len(doc)
        w = round(doc[0].rect.width) if pages else 0
        h = round(doc[0].rect.height) if pages else 0
        return {
            'name': _clean_stem(path) + path.suffix,
            'path': str(path),
            'pages': pages,
            'size_bytes': path.stat().st_size,
            'page_size': f'{w} × {h} pt' if pages else '需密码查看',
            'needs_pass': needs_pass,
            'is_encrypted': is_encrypted,
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
                _ensure_unlocked(src, Path(p).name)
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
        _ensure_unlocked(doc)
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
            if not selected:
                raise ValueError('未匹配到任何有效页码')
            angle = int(angle or 90) % 360
            for idx in selected:
                page = doc[idx]
                page.set_rotation((page.rotation + angle) % 360)
            out_path = unique_path(out_dir, f'{stem}_旋转', '.pdf')
            doc.save(out_path, garbage=3, deflate=True)
            return {'name': out_path.name, 'path': str(out_path), 'pages': total,
                    'output_size': out_path.stat().st_size, 'output_dir': str(out_dir)}

        if action == 'split_all':
            if not selected:
                raise ValueError('未匹配到任何有效页码')
            zip_path = unique_path(out_dir, f'{stem}_拆分全部', '.zip')
            try:
                with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
                    for idx in selected:
                        single = pymupdf.open()
                        try:
                            single.insert_pdf(doc, from_page=idx, to_page=idx)
                            pdf_bytes = single.tobytes(garbage=3, deflate=True)
                        finally:
                            single.close()
                        zf.writestr(f'{stem}_第{idx + 1}页.pdf', pdf_bytes)
            except Exception:
                zip_path.unlink(missing_ok=True)
                raise
            return {'name': zip_path.name, 'path': str(zip_path), 'pages': len(selected),
                    'output_size': zip_path.stat().st_size, 'output_dir': str(out_dir)}

        raise ValueError(f'不支持的 PDF 操作: {action}')


def pdf_to_images(path_str, fmt='png', dpi=150, pages_expr='', out_dir=None):
    out_dir = Path(out_dir or OUTPUT_DIR)
    stem = _clean_stem(path_str)
    dpi = max(72, min(300, int(dpi or 150)))
    is_jpg = fmt.lower() in ('jpg', 'jpeg')
    ext = '.jpg' if is_jpg else '.png'
    pix_fmt = 'jpeg' if is_jpg else 'png'

    with pymupdf.open(path_str) as doc:
        _ensure_unlocked(doc)
        selected = parse_pages(pages_expr, len(doc))
        if not selected:
            raise ValueError('未匹配到任何有效页码')

        if len(selected) == 1:
            idx = selected[0]
            pix = doc[idx].get_pixmap(dpi=dpi, alpha=False)
            p = unique_path(out_dir, f'{stem}_p{idx + 1}', ext)
            pix.save(str(p))
            return {'name': p.name, 'path': str(p), 'count': 1,
                    'output_size': p.stat().st_size, 'output_dir': str(out_dir)}

        zip_path = unique_path(out_dir, f'{stem}_导出图片', '.zip')
        try:
            with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
                for idx in selected:
                    pix = doc[idx].get_pixmap(dpi=dpi, alpha=False)
                    zf.writestr(f'{stem}_p{idx + 1:03d}{ext}', pix.tobytes(pix_fmt))
        except Exception:
            zip_path.unlink(missing_ok=True)
            raise
        return {'name': zip_path.name, 'path': str(zip_path), 'count': len(selected),
                'output_size': zip_path.stat().st_size, 'output_dir': str(out_dir)}


def images_to_pdf(paths, out_dir=None):
    if not paths:
        raise ValueError('请至少选择 1 张图片')
    import io
    from tools_image import _open_oriented

    out_dir = Path(out_dir or OUTPUT_DIR)
    out_path = unique_path(out_dir, '图片合成文档', '.pdf')
    doc = pymupdf.open()
    try:
        for p in paths:
            with _open_oriented(p) as raw:
                if raw.mode in ('RGBA', 'LA', 'P'):
                    bg = Image.new('RGB', raw.size, (255, 255, 255))
                    rgba = raw.convert('RGBA')
                    bg.paste(rgba, mask=rgba.split()[-1])
                    img = bg
                elif raw.mode != 'RGB':
                    img = raw.convert('RGB')
                else:
                    img = raw
                w, h = img.size
                # 按 A4 长边 842pt（297mm）等比缩放页面尺寸，避免高像素图生成数米巨型 PDF 页
                scale = min(1.0, 842.0 / max(w, h)) if max(w, h) > 0 else 1.0
                pw, ph = round(w * scale, 2), round(h * scale, 2)
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
        _ensure_unlocked(doc)
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
    """通过独立 PowerShell STA 进程调用本机 Microsoft Word COM 导出 PDF。

    若检测到用户已在桌面打开 Word，则以无窗只读模式借用转换，绝不隐藏用户窗口、不关闭用户已打开文档、也不强退 Word。
    """
    import tempfile
    import uuid

    pid_file = Path(tempfile.gettempdir()) / f'toolbox_word_{uuid.uuid4().hex[:8]}.pid'
    # 将参数写入临时 .ps1 脚本文件执行，避免 -Command 按空格拆分含空格路径
    ps_script_file = Path(tempfile.gettempdir()) / f'toolbox_word_{uuid.uuid4().hex[:8]}.ps1'
    ps_script = (
        '$ErrorActionPreference = "Stop"\n'
        '$src = [System.IO.Path]::GetFullPath($args[0]); $dst = [System.IO.Path]::GetFullPath($args[1])\n'
        '$fmt = [int]$args[2]; $pidFile = $args[3]\n'
        '$word = $null; $openedDoc = $null; $reused = $false; $origAlerts = $null\n'
        'try {\n'
        '    $before = @(Get-Process -Name WINWORD -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id)\n'
        '    $word = New-Object -ComObject Word.Application\n'
        '    $after = @(Get-Process -Name WINWORD -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id)\n'
        '    $newPids = @($after | Where-Object { $before -notcontains $_ })\n'
        '    $reused = ($newPids.Count -eq 0) -or ($word.Visible -eq $true) -or ($word.Documents.Count -gt 0)\n'
        '    if (-not $reused -and $newPids.Count -gt 0) {\n'
        '        ($newPids -join ",") | Set-Content -Path $pidFile -Encoding ASCII\n'
        '    }\n'
        '    $origAlerts = $word.DisplayAlerts\n'
        '    if (-not $reused) { $word.Visible = $false }\n'
        '    $word.DisplayAlerts = 0\n'
        '    $targetDoc = $null\n'
        '    if ($reused) {\n'
        '        foreach ($d in $word.Documents) {\n'
        '            try {\n'
        '                if ([string]::Equals([System.IO.Path]::GetFullPath($d.FullName), $src, [System.StringComparison]::OrdinalIgnoreCase)) {\n'
        '                    $targetDoc = $d; break\n'
        '                }\n'
        '            } catch {}\n'
        '        }\n'
        '    }\n'
        '    if ($null -eq $targetDoc) {\n'
        '        $m = [System.Reflection.Missing]::Value\n'
        '        $openedDoc = $word.Documents.Open($src, $false, $true, $false, $m, $m, $false, $m, $m, $m, $m, $false)\n'
        '        $targetDoc = $openedDoc\n'
        '    }\n'
        '    $targetDoc.ExportAsFixedFormat($dst, $fmt)\n'
        '} finally {\n'
        '    if ($openedDoc) { try { $openedDoc.Close(0) } catch {} }\n'
        '    if ($word) {\n'
        '        if ($reused) {\n'
        '            if ($null -ne $origAlerts) { try { $word.DisplayAlerts = $origAlerts } catch {} }\n'
        '        } else {\n'
        '            try { $word.Quit(0) } catch {}\n'
        '        }\n'
        '        try { [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($word) } catch {}\n'
        '    }\n'
        '}\n'
    )
    try:
        ps_script_file.write_text(ps_script, encoding='utf-8')
        proc = subprocess.Popen(
            ['powershell.exe', '-NoProfile', '-NonInteractive', '-STA',
             '-ExecutionPolicy', 'Bypass', '-File', str(ps_script_file),
             str(src_path), str(dst_path), str(wd_format), str(pid_file)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding='utf-8', errors='replace', creationflags=_NO_WINDOW,
        )
        try:
            stdout, stderr = proc.communicate(timeout=120)
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
        ps_script_file.unlink(missing_ok=True)
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
        _ensure_unlocked(doc)
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


def protect_pdf(path_str, user_pw='', owner_pw='', allow_print=True, allow_copy=True, out_dir=None):
    """使用 AES-256 为 PDF 设置打开密码或打印/复制权限限制（原样保留密码字符，不做隐式裁剪）。"""
    user_pw = '' if user_pw is None else str(user_pw)
    owner_pw = '' if owner_pw is None else str(owner_pw)
    if user_pw == '' and owner_pw == '':
        raise ValueError('请至少填写“打开密码”或“权限密码”之一')
    out_dir = Path(out_dir or OUTPUT_DIR)
    src = Path(path_str)
    if not src.exists():
        raise FileNotFoundError('PDF 文件不存在')

    perms = int(pymupdf.PDF_PERM_ACCESSIBILITY)
    if allow_print:
        perms |= int(pymupdf.PDF_PERM_PRINT)
    if allow_copy:
        perms |= int(pymupdf.PDF_PERM_COPY)

    out_path = unique_path(out_dir, f'{_clean_stem(src)}_加密', '.pdf')
    with pymupdf.open(src) as doc:
        if doc.needs_pass:
            raise ValueError('原 PDF 已有打开密码，请先使用“解除密码”功能解锁')
        pages = len(doc)
        doc.save(
            out_path,
            encryption=pymupdf.PDF_ENCRYPT_AES_256,
            user_pw=user_pw,
            owner_pw=owner_pw or user_pw,
            permissions=perms,
            garbage=3,
            deflate=True,
        )
    return {
        'name': out_path.name,
        'path': str(out_path),
        'pages': pages,
        'output_size': out_path.stat().st_size,
        'output_dir': str(out_dir),
    }


def unlock_pdf(path_str, password='', out_dir=None):
    """解除 PDF 打开密码（需已知密码）以及打印/复制等权限限制。"""
    out_dir = Path(out_dir or OUTPUT_DIR)
    src = Path(path_str)
    if not src.exists():
        raise FileNotFoundError('PDF 文件不存在')

    out_path = unique_path(out_dir, f'{_clean_stem(src)}_解锁', '.pdf')
    with pymupdf.open(src) as doc:
        if doc.needs_pass:
            if not password or not doc.authenticate(password):
                raise ValueError('密码不正确，无法解锁该 PDF')
        elif password:
            # 即使无需打开密码，若提供了权限密码也可尝试验证
            doc.authenticate(password)
        pages = len(doc)
        doc.save(
            out_path,
            encryption=pymupdf.PDF_ENCRYPT_NONE,
            garbage=3,
            deflate=True,
        )
    return {
        'name': out_path.name,
        'path': str(out_path),
        'pages': pages,
        'output_size': out_path.stat().st_size,
        'output_dir': str(out_dir),
    }
