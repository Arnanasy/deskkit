"""图片工坊：批量压缩、格式互转（JPG/PNG/WEBP/ICO）、改尺寸、拼长图/宫格、去 EXIF。"""
import math
from pathlib import Path
import zipfile

from PIL import Image, ImageOps

from tools_files import OUTPUT_DIR, clean_stem, unique_path

# 本地工具箱放宽 Pillow 默认的 1.79 亿像素限制（支持高像素长图/超清壁纸，同时保留 10 亿像素防爆底线）
Image.MAX_IMAGE_PIXELS = 1_000_000_000


def _open_oriented(path):
    img = Image.open(path)
    return ImageOps.exif_transpose(img)


def _save_image(img, out_path, fmt, quality=85):
    fmt_upper = fmt.upper()
    if fmt_upper in ('JPG', 'JPEG'):
        if img.mode in ('RGBA', 'LA', 'P'):
            bg = Image.new('RGB', img.size, (255, 255, 255))
            rgba = img.convert('RGBA')
            bg.paste(rgba, mask=rgba.split()[-1])
            img = bg
        elif img.mode != 'RGB':
            img = img.convert('RGB')
        img.save(out_path, format='JPEG', quality=quality, optimize=True)
    elif fmt_upper == 'PNG':
        img.save(out_path, format='PNG', optimize=True)
    elif fmt_upper == 'WEBP':
        img.save(out_path, format='WEBP', quality=quality, method=4)
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
                if fmt == 'jpeg':
                    fmt = 'jpg'
            else:
                fmt = target_fmt.lower().lstrip('.')
                ext = '.' + fmt

            stem = clean_stem(src)
            out_path = unique_path(out_dir, f'{stem}_处理', ext)

            # 默认保存本身就不带原始 exif，从而天然清除隐私 EXIF
            if strip_exif:
                _save_image(img, out_path, fmt, quality=quality)
            else:
                exif = img.info.get('exif')
                if exif and fmt in ('jpg', 'jpeg', 'webp'):
                    img.save(out_path, quality=quality, exif=exif)
                else:
                    _save_image(img, out_path, fmt, quality=quality)

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


def stitch_images(paths, mode='vertical', gap=0, bg_color='#ffffff', cols=2, out_fmt='png', out_dir=None):
    """拼长图（竖向/横向）或拼宫格。"""
    if len(paths) < 2:
        raise ValueError('请至少选择 2 张图片进行拼接')
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
            canvas = Image.new('RGBA', (total_w, total_h), bg_color)
            for idx, im in enumerate(imgs):
                fitted = ImageOps.fit(im, (cell_w, cell_h), Image.Resampling.LANCZOS)
                r, c = divmod(idx, cols)
                canvas.paste(fitted, (c * (cell_w + gap), r * (cell_h + gap)), fitted)

        ext = '.' + (out_fmt.lower().lstrip('.') or 'png')
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
