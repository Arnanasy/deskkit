"""图片工坊：批量压缩、格式互转（JPG/PNG/WEBP/AVIF/ICO，支持 HEIC 读取）、改尺寸、拼长图/宫格、旋转翻转、长图分割、去 EXIF。"""
import io
import math
from pathlib import Path
import shutil
import subprocess
import zipfile

from PIL import Image, ImageOps, features

from tools_files import OUTPUT_DIR, clean_stem, unique_path

# 本地工具箱放宽 Pillow 默认的 1.79 亿像素限制（支持高像素长图/超清壁纸，同时保留 10 亿像素防爆底线）
Image.MAX_IMAGE_PIXELS = 1_000_000_000
_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
_HEIF_REGISTERED = False


def _try_register_heif():
    global _HEIF_REGISTERED
    if _HEIF_REGISTERED:
        return True
    try:
        import pillow_heif  # type: ignore
        pillow_heif.register_heif_opener()
        _HEIF_REGISTERED = True
        return True
    except Exception:
        return False


def _decode_via_ffmpeg(path):
    """当 Pillow 无法直接解码（如未装 pillow-heif 时的 HEIC/HEIF）时，回退用本机 FFmpeg 解码首帧。"""
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        raise RuntimeError('当前环境无法读取该图片格式（HEIC 需安装 FFmpeg 或 pillow-heif）')
    run = subprocess.run(
        [ffmpeg, '-hide_banner', '-loglevel', 'error', '-i', str(path),
         '-frames:v', '1', '-f', 'image2pipe', '-vcodec', 'png', 'pipe:1'],
        capture_output=True, timeout=20, creationflags=_NO_WINDOW,
    )
    if run.returncode != 0 or not run.stdout:
        detail = (run.stderr.decode('utf-8', errors='replace') or '').strip()
        raise RuntimeError(f'无法解码图片 {Path(path).name}: {detail or "格式不受支持或文件损坏"}')
    img = Image.open(io.BytesIO(run.stdout))
    img.load()
    return img


def _open_oriented(path):
    p = Path(path)
    if p.suffix.lower() in ('.heic', '.heif'):
        _try_register_heif()
    try:
        with Image.open(p) as raw:
            transposed = ImageOps.exif_transpose(raw)
            transposed.load()
            # 保留原始 exif（exif_transpose 后 info 中仍带 exif）
            return transposed
    except Exception:
        if p.suffix.lower() in ('.heic', '.heif', '.avif'):
            return _decode_via_ffmpeg(p)
        raise


def _save_image(img, out_path, fmt, quality=85, exif=None):
    fmt_upper = fmt.upper()
    save_kwargs = {}
    if exif and fmt_upper in ('JPG', 'JPEG', 'WEBP'):
        save_kwargs['exif'] = exif

    if fmt_upper in ('JPG', 'JPEG'):
        if img.mode in ('RGBA', 'LA', 'P'):
            bg = Image.new('RGB', img.size, (255, 255, 255))
            rgba = img.convert('RGBA')
            bg.paste(rgba, mask=rgba.split()[-1])
            img = bg
        elif img.mode != 'RGB':
            img = img.convert('RGB')
        img.save(out_path, format='JPEG', quality=quality, optimize=True, **save_kwargs)
    elif fmt_upper == 'PNG':
        img.save(out_path, format='PNG', optimize=True)
    elif fmt_upper == 'WEBP':
        img.save(out_path, format='WEBP', quality=quality, method=4, **save_kwargs)
    elif fmt_upper == 'AVIF':
        if not features.check('avif'):
            raise RuntimeError('当前 Pillow 版本不支持保存 AVIF 格式，请改选 JPG / WEBP / PNG')
        if img.mode == 'P':
            img = img.convert('RGBA')
        img.save(out_path, format='AVIF', quality=quality)
    elif fmt_upper == 'ICO':
        icon = img.convert('RGBA')
        sizes = [(s, s) for s in (256, 128, 64, 48, 32, 16) if s <= max(icon.size) or s == 32]
        icon.save(out_path, format='ICO', sizes=sizes or [(64, 64)])
    else:
        img.save(out_path)


def _bundle_zip(out_dir, paths, stem):
    zip_path = unique_path(out_dir, stem, '.zip')
    with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        for p in paths:
            zf.write(p, arcname=p.name)
    return zip_path


def process_convert_compress(paths, target_fmt='keep', quality=82, max_width=0, max_height=0,
                             strip_exif=True, out_dir=None):
    """批量压缩、格式转换、尺寸缩放与清理 EXIF。"""
    if not paths:
        raise ValueError('请至少选择 1 张图片')
    out_dir = Path(out_dir or OUTPUT_DIR)
    quality = max(10, min(100, int(quality or 82)))
    max_width = max(0, int(max_width or 0))
    max_height = max(0, int(max_height or 0))

    results = []
    out_paths = []
    for p_str in paths:
        src = Path(p_str)
        in_size = src.stat().st_size
        with _open_oriented(src) as img:
            if max_width > 0 or max_height > 0:
                w, h = img.size
                mw = max_width or w
                mh = max_height or h
                if w > mw or h > mh:
                    img.thumbnail((mw, mh), Image.Resampling.LANCZOS)

            if target_fmt == 'keep':
                ext = src.suffix.lower() or '.png'
                fmt = ext.lstrip('.')
                if fmt in ('jpeg', 'heic', 'heif'):
                    fmt = 'jpg'
                    ext = '.jpg'
            else:
                fmt = target_fmt.lower().lstrip('.')
                ext = '.' + fmt

            stem = clean_stem(src)
            out_path = unique_path(out_dir, f'{stem}_处理', ext)

            # 统一经由 _save_image 处理色彩空间（含透明通道白底合成），按需透传 EXIF
            exif = None if strip_exif else img.info.get('exif')
            _save_image(img, out_path, fmt, quality=quality, exif=exif)

        out_size = out_path.stat().st_size
        out_paths.append(out_path)
        results.append({
            'name': out_path.name,
            'path': str(out_path),
            'input_size': in_size,
            'output_size': out_size,
            'saved_pct': round((1 - out_size / in_size) * 100, 1) if in_size else 0,
        })

    zip_path = _bundle_zip(out_dir, out_paths, '图片批量处理') if len(out_paths) > 1 else None
    return {
        'files': results,
        'zip_path': str(zip_path) if zip_path else '',
        'zip_name': zip_path.name if zip_path else '',
        'output_dir': str(out_dir),
    }


def _validate_canvas_size(width, height, fmt):
    """提前拦截超大拼接画布与 JPG 单边 65500px 上限，避免内存爆涨或保存失败。"""
    fmt_l = (fmt or 'png').lower().lstrip('.')
    if fmt_l not in ('png', 'jpg', 'jpeg', 'webp', 'avif'):
        raise ValueError(f'不支持的输出图片格式: {fmt}')
    if width <= 0 or height <= 0:
        raise ValueError('目标画布尺寸无效')
    if fmt_l in ('jpg', 'jpeg') and (width > 65000 or height > 65000):
        raise ValueError(f'拼接尺寸 {width}×{height} 超出 JPG 单边 65000px 上限，请改选 PNG 或先压缩图片')
    if width * height > 300_000_000:
        raise ValueError(f'拼接总像素过大（{width}×{height}），请先批量缩小尺寸或减少拼接张数')


def stitch_images(paths, mode='vertical', gap=0, bg_color='#ffffff', cols=2, out_fmt='png', out_dir=None):
    """拼长图（竖向/横向）或拼宫格。"""
    if len(paths) < 2:
        raise ValueError('请至少选择 2 张图片进行拼接')
    fmt_clean = (out_fmt or 'png').lower().lstrip('.')
    if fmt_clean not in ('png', 'jpg', 'jpeg', 'webp', 'avif'):
        raise ValueError(f'不支持的输出图片格式: {out_fmt}')
    out_dir = Path(out_dir or OUTPUT_DIR)
    gap = max(0, min(100, int(gap or 0)))
    cols = max(2, min(6, int(cols or 2)))

    imgs = [_open_oriented(Path(p)).convert('RGBA') for p in paths]
    try:
        if mode == 'vertical':
            target_w = max(im.width for im in imgs)
            resized = [
                im.resize((target_w, round(im.height * target_w / im.width)), Image.Resampling.LANCZOS)
                if im.width != target_w else im
                for im in imgs
            ]
            total_h = sum(im.height for im in resized) + gap * (len(resized) - 1)
            _validate_canvas_size(target_w, total_h, fmt_clean)
            canvas = Image.new('RGBA', (target_w, total_h), bg_color)
            y = 0
            for im in resized:
                canvas.paste(im, (0, y), im)
                y += im.height + gap
        elif mode == 'horizontal':
            target_h = max(im.height for im in imgs)
            resized = [
                im.resize((round(im.width * target_h / im.height), target_h), Image.Resampling.LANCZOS)
                if im.height != target_h else im
                for im in imgs
            ]
            total_w = sum(im.width for im in resized) + gap * (len(resized) - 1)
            _validate_canvas_size(total_w, target_h, fmt_clean)
            canvas = Image.new('RGBA', (total_w, target_h), bg_color)
            x = 0
            for im in resized:
                canvas.paste(im, (x, 0), im)
                x += im.width + gap
        else:
            # 宫格拼接：统一缩放到同一格子尺寸
            cell_w = min(max(im.width for im in imgs), 1200)
            cell_h = round(cell_w * (imgs[0].height / imgs[0].width))
            rows = math.ceil(len(imgs) / cols)
            total_w = cols * cell_w + gap * (cols - 1)
            total_h = rows * cell_h + gap * (rows - 1)
            _validate_canvas_size(total_w, total_h, fmt_clean)
            canvas = Image.new('RGBA', (total_w, total_h), bg_color)
            for idx, im in enumerate(imgs):
                fitted = ImageOps.fit(im, (cell_w, cell_h), Image.Resampling.LANCZOS)
                r, c = divmod(idx, cols)
                canvas.paste(fitted, (c * (cell_w + gap), r * (cell_h + gap)), fitted)

        ext = '.' + fmt_clean
        out_path = unique_path(out_dir, '拼接图片', ext)
        _save_image(canvas, out_path, ext.lstrip('.'), quality=90)
        return {
            'name': out_path.name,
            'path': str(out_path),
            'output_size': out_path.stat().st_size,
            'width': canvas.width,
            'height': canvas.height,
            'output_dir': str(out_dir),
        }
    finally:
        for im in imgs:
            im.close()


def rotate_flip_images(paths, op='cw90', out_fmt='keep', out_dir=None):
    """批量旋转或翻转图片（cw90 / ccw90 / 180 / flip_h / flip_v）。"""
    if not paths:
        raise ValueError('请至少选择 1 张图片')
    op_map = {
        'cw90': (Image.Transpose.ROTATE_270, '顺时针90'),
        'ccw90': (Image.Transpose.ROTATE_90, '逆时针90'),
        '180': (Image.Transpose.ROTATE_180, '旋转180'),
        'flip_h': (Image.Transpose.FLIP_LEFT_RIGHT, '水平翻转'),
        'flip_v': (Image.Transpose.FLIP_TOP_BOTTOM, '垂直翻转'),
    }
    if op not in op_map:
        raise ValueError(f'不支持的旋转/翻转操作: {op}')
    transpose_flag, tag = op_map[op]
    out_dir = Path(out_dir or OUTPUT_DIR)

    results = []
    out_paths = []
    for p_str in paths:
        src = Path(p_str)
        with _open_oriented(src) as img:
            transformed = img.transpose(transpose_flag)
            if out_fmt == 'keep':
                ext = src.suffix.lower() or '.png'
                fmt = ext.lstrip('.')
                if fmt in ('jpeg', 'heic', 'heif'):
                    fmt, ext = 'jpg', '.jpg'
            else:
                fmt = out_fmt.lower().lstrip('.')
                ext = '.' + fmt
            out_path = unique_path(out_dir, f'{clean_stem(src)}_{tag}', ext)
            _save_image(transformed, out_path, fmt, quality=92)
            out_paths.append(out_path)
            results.append({
                'name': out_path.name,
                'path': str(out_path),
                'width': transformed.width,
                'height': transformed.height,
                'output_size': out_path.stat().st_size,
            })
            transformed.close()

    zip_path = _bundle_zip(out_dir, out_paths, f'图片批量_{tag}') if len(out_paths) > 1 else None
    return {
        'files': results,
        'zip_path': str(zip_path) if zip_path else '',
        'zip_name': zip_path.name if zip_path else '',
        'output_dir': str(out_dir),
    }


def split_image(path_str, mode='vertical', parts=3, rows=3, cols=3,
                max_piece_height=0, out_fmt='png', out_dir=None):
    """长图分割（竖向/横向均分或按最大高度切分）与宫格切图（如九宫格）。"""
    src = Path(path_str)
    if not src.exists():
        raise FileNotFoundError('图片文件不存在')
    out_dir = Path(out_dir or OUTPUT_DIR)
    fmt = (out_fmt or 'png').lower().lstrip('.')
    ext = '.' + fmt
    stem = clean_stem(src)

    out_paths = []
    with _open_oriented(src) as img:
        w, h = img.size
        boxes = []
        if mode == 'vertical':
            max_h = max(0, int(max_piece_height or 0))
            if max_h > 0:
                if max_h >= h:
                    raise ValueError(f'图片高度仅 {h}px，不大于设定的单段高度 {max_h}px，无需分割')
                y = 0
                while y < h:
                    y2 = min(h, y + max_h)
                    boxes.append((0, y, w, y2))
                    y = y2
                    if len(boxes) > 100:
                        raise ValueError('切分数量超过 100 张上限，请调大单段高度')
            else:
                n = max(2, min(50, int(parts or 3)))
                if n > h:
                    raise ValueError(f'图片高度仅 {h}px，无法竖向切分为 {n} 份')
                for i in range(n):
                    y1 = round(h * i / n)
                    y2 = round(h * (i + 1) / n)
                    if y2 > y1:
                        boxes.append((0, y1, w, y2))
        elif mode == 'horizontal':
            n = max(2, min(50, int(parts or 3)))
            if n > w:
                raise ValueError(f'图片宽度仅 {w}px，无法横向切分为 {n} 份')
            for i in range(n):
                x1 = round(w * i / n)
                x2 = round(w * (i + 1) / n)
                if x2 > x1:
                    boxes.append((x1, 0, x2, h))
        elif mode == 'grid':
            r_cnt = max(1, min(10, int(rows or 3)))
            c_cnt = max(1, min(10, int(cols or 3)))
            if r_cnt * c_cnt < 2:
                raise ValueError('宫格切图行数与列数乘积至少为 2')
            if r_cnt > h or c_cnt > w:
                raise ValueError('图片尺寸小于所选宫格行列数')
            for r in range(r_cnt):
                y1, y2 = round(h * r / r_cnt), round(h * (r + 1) / r_cnt)
                for c in range(c_cnt):
                    x1, x2 = round(w * c / c_cnt), round(w * (c + 1) / c_cnt)
                    if x2 > x1 and y2 > y1:
                        boxes.append((x1, y1, x2, y2))
        else:
            raise ValueError(f'不支持的切图模式: {mode}')

        for idx, box in enumerate(boxes, 1):
            piece = img.crop(box)
            p = unique_path(out_dir, f'{stem}_切片{idx:02d}', ext)
            _save_image(piece, p, fmt, quality=92)
            piece.close()
            out_paths.append(p)

    zip_path = _bundle_zip(out_dir, out_paths, f'{stem}_分割_{len(out_paths)}张')
    return {
        'count': len(out_paths),
        'first_path': str(out_paths[0]),
        'zip_path': str(zip_path),
        'zip_name': zip_path.name,
        'output_size': zip_path.stat().st_size,
        'output_dir': str(out_dir),
    }
