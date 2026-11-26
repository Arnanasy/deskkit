"""本地工具箱核心逻辑单元测试（覆盖文件、图片、PDF、视频与字幕、编码修复与哈希校验）。"""
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import zipfile
import zlib

from PIL import Image, features
import pymupdf

PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import tools_files
import tools_image
import tools_pdf
import tools_video


class TestToolsFiles(unittest.TestCase):
    """路径安全、文件名清洗、去重生成与批量重命名（含异常回滚）。"""

    def test_is_within_blocks_prefix_sibling_bypass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'out'
            sibling = Path(tmp) / 'out_evil' / 'a.txt'
            inside = root / 'sub' / 'a.txt'
            root.mkdir()
            sibling.parent.mkdir()
            self.assertTrue(tools_files.is_within(inside, root))
            self.assertFalse(tools_files.is_within(sibling, root))

    def test_safe_filename_sanitizes_illegal_chars_and_windows_reserved(self):
        self.assertEqual(tools_files.safe_filename('a<b>c:d/e\\f|g?h*i'), 'a_b_c_d_e_f_g_h_i')
        self.assertEqual(tools_files.safe_filename('...'), 'file')
        self.assertEqual(tools_files.safe_filename('CON'), '_CON')
        self.assertEqual(tools_files.safe_filename('nul.txt'), '_nul.txt')
        self.assertEqual(tools_files.safe_filename('com1'), '_com1')
        self.assertEqual(tools_files.safe_filename('normal_name'), 'normal_name')

    def test_clean_stem_only_strips_toolbox_upload_prefix(self):
        self.assertEqual(tools_files.clean_stem('__tb_1a2b3c4d_我的报告.pdf'), '我的报告')
        self.assertEqual(tools_files.clean_stem('__tb_nothexzz_报告.pdf'), '__tb_nothexzz_报告')
        self.assertEqual(tools_files.clean_stem('普通文件.mp4'), '普通文件')

    def test_unique_path_increments_suffix(self):
        with tempfile.TemporaryDirectory() as tmp:
            p1 = tools_files.unique_path(tmp, 'demo', '.txt')
            self.assertEqual(p1.name, 'demo.txt')
            p1.write_text('1', encoding='utf-8')
            p2 = tools_files.unique_path(tmp, 'demo', 'txt')
            self.assertEqual(p2.name, 'demo_2.txt')

    def test_preview_batch_rename_caps_pad_digits_and_detects_conflicts(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'a.txt').write_text('a', encoding='utf-8')
            (Path(tmp) / 'b.txt').write_text('b', encoding='utf-8')

            # pad_digits 极大值应被截断为 12 位
            res = tools_files.preview_batch_rename(tmp, numbering=True, start_num=1, pad_digits=9999)
            self.assertEqual(res['items'][0]['new_name'], 'a_000000000001.txt')

            # 全部替换为同一名称时应标出冲突
            conflict_res = tools_files.preview_batch_rename(tmp, find_text='a', replace_text='b')
            self.assertEqual(conflict_res['conflicts'], 1)

    def test_execute_batch_rename_two_phase_swap_and_rollback(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / 'a.txt').write_text('AAA', encoding='utf-8')
            (base / 'b.txt').write_text('BBB', encoding='utf-8')

            # 互换文件名（a <-> b）依靠两阶段临时名应一次成功
            res = tools_files.execute_batch_rename(tmp, [
                {'old_name': 'a.txt', 'new_name': 'b.txt', 'changed': True, 'conflict': False},
                {'old_name': 'b.txt', 'new_name': 'a.txt', 'changed': True, 'conflict': False},
            ])
            self.assertEqual(res['renamed'], 2)
            self.assertEqual((base / 'a.txt').read_text(encoding='utf-8'), 'BBB')
            self.assertEqual((base / 'b.txt').read_text(encoding='utf-8'), 'AAA')

            # 跨目录越界必须被拦截
            with self.assertRaises(ValueError):
                tools_files.execute_batch_rename(tmp, [
                    {'old_name': 'a.txt', 'new_name': '../escape.txt', 'changed': True, 'conflict': False},
                ])

            # 目标已存在（与未参与重命名的 c.txt 冲突）时应自动回滚，不能残留临时名
            (base / 'c.txt').write_text('CCC', encoding='utf-8')
            with self.assertRaises(ValueError):
                tools_files.execute_batch_rename(tmp, [
                    {'old_name': 'a.txt', 'new_name': 'x.txt', 'changed': True, 'conflict': False},
                    {'old_name': 'b.txt', 'new_name': 'c.txt', 'changed': True, 'conflict': False},
                ])
            self.assertEqual((base / 'a.txt').read_text(encoding='utf-8'), 'BBB')
            self.assertEqual((base / 'b.txt').read_text(encoding='utf-8'), 'AAA')
            self.assertFalse((base / 'x.txt').exists())
            self.assertEqual(sorted(p.name for p in base.iterdir()), ['a.txt', 'b.txt', 'c.txt'])

    def test_preview_batch_rename_ext_case(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'Photo.JPG').write_text('x', encoding='utf-8')
            res_low = tools_files.preview_batch_rename(tmp, ext_case='lower')
            self.assertEqual(res_low['items'][0]['new_name'], 'Photo.jpg')
            res_up = tools_files.preview_batch_rename(tmp, ext_case='upper')
            self.assertEqual(res_up['items'][0]['new_name'], 'Photo.JPG')

    def test_preview_batch_rename_detects_conflict_with_unselected_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'pic.jpg').write_text('a', encoding='utf-8')
            (Path(tmp) / 'pic.png').write_text('b', encoding='utf-8')
            res = tools_files.preview_batch_rename(tmp, ext_filter='.jpg', new_ext='.png')
            self.assertEqual(res['conflicts'], 1)
            self.assertTrue(res['items'][0]['conflict'])

    def test_fix_zip_encoding_restores_gbk_chinese_and_sanitizes_zip_slip(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / '中文目录'
            base.mkdir()
            src_zip = base / '乱码包.zip'
            out_dir = base / '输出'

            # 模拟旧版 Windows 打包：以 GB18030 原始字节写入文件名且 flag_bits 不置 UTF-8 (0x800)
            gbk_name_bytes = '文档目录/测试中文.txt'.encode('gb18030')

            class RawZipInfo(zipfile.ZipInfo):
                def _encodeFilenameFlags(self):
                    return gbk_name_bytes, 0

            with zipfile.ZipFile(src_zip, 'w') as zf:
                zi1 = RawZipInfo('placeholder.txt')
                zf.writestr(zi1, '你好，世界！'.encode('utf-8'))
                zi2 = zipfile.ZipInfo('../越界文件.txt')
                zf.writestr(zi2, b'safe')

            res = tools_files.fix_zip_encoding(str(src_zip), source_encoding='auto', out_dir=out_dir)
            self.assertGreaterEqual(res['fixed'], 1)
            fixed_zip = Path(res['path'])
            self.assertTrue(fixed_zip.exists())
            with zipfile.ZipFile(fixed_zip, 'r') as zf:
                names = zf.namelist()
                self.assertIn('文档目录/测试中文.txt', names)
                self.assertIn('越界文件.txt', names)
                self.assertFalse(any('..' in n for n in names))
                self.assertEqual(zf.read('文档目录/测试中文.txt').decode('utf-8'), '你好，世界！')

            # 非 ZIP 文件应抛出 ValueError
            bad_file = base / 'not_zip.txt'
            bad_file.write_text('hello', encoding='utf-8')
            with self.assertRaises(ValueError):
                tools_files.fix_zip_encoding(str(bad_file), out_dir=out_dir)

            # 非法源编码名应抛出友好 ValueError 而非 LookupError
            with self.assertRaises(ValueError):
                tools_files.fix_zip_encoding(str(src_zip), source_encoding='not_a_real_enc', out_dir=out_dir)

    def test_fix_text_encoding_gbk_to_utf8_bom_and_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / '中文路径'
            base.mkdir()
            csv_path = base / '报表.csv'
            content = '姓名,城市\n张三,北京\n李四,上海\n'
            csv_path.write_bytes(content.encode('gb18030'))

            res = tools_files.fix_text_encoding(str(csv_path), source_encoding='auto',
                                                target_encoding='utf-8-sig', out_dir=base)
            self.assertEqual(res['detected_encoding'], 'gb18030')
            out_bytes = Path(res['path']).read_bytes()
            self.assertTrue(out_bytes.startswith(b'\xef\xbb\xbf'))
            self.assertEqual(out_bytes.decode('utf-8-sig'), content)

            with self.assertRaises(ValueError):
                tools_files.fix_text_encoding(str(csv_path), target_encoding='invalid-enc', out_dir=base)

            # 二进制文件与无法解码的未知编码字节流不得静默回退 latin1 制造乱码，必须抛 ValueError
            bin_path = base / 'binary.dat'
            bin_path.write_bytes(b'MZ\x90\x00\x03\x00\x00\x00binary')
            with self.assertRaises(ValueError):
                tools_files.fix_text_encoding(str(bin_path), source_encoding='auto', out_dir=base)

            undecodable = base / 'bad_bytes.txt'
            # 构造同时非法于 UTF-8 / GB18030 / Big5 / Shift_JIS 的孤立高位字节序列
            undecodable.write_bytes(b'\x80\xff\xfe\x81\xff')
            with self.assertRaises(ValueError):
                tools_files.fix_text_encoding(str(undecodable), source_encoding='auto', out_dir=base)

    def test_calc_file_hash_normal_and_empty_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / '哈希测试'
            base.mkdir()
            f1 = base / '样本文件.bin'
            payload = '本地工具箱校验测试 123456'.encode('utf-8')
            f1.write_bytes(payload)
            res = tools_files.calc_file_hash(str(f1))
            self.assertEqual(res['md5'], hashlib.md5(payload).hexdigest())
            self.assertEqual(res['sha1'], hashlib.sha1(payload).hexdigest())
            self.assertEqual(res['sha256'], hashlib.sha256(payload).hexdigest())
            self.assertEqual(res['crc32'], f'{zlib.crc32(payload) & 0xffffffff:08x}')

            # 空文件边界
            f0 = base / 'empty.dat'
            f0.write_bytes(b'')
            res0 = tools_files.calc_file_hash(str(f0))
            self.assertEqual(res0['size_bytes'], 0)
            self.assertEqual(res0['md5'], hashlib.md5(b'').hexdigest())
            self.assertEqual(res0['crc32'], '00000000')


class TestToolsImage(unittest.TestCase):
    """图片工坊：透明通道+保留EXIF转JPG回归测试、AVIF支持、旋转翻转、长图分割。"""

    def test_rgba_with_exif_to_jpg_when_keep_exif_does_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / '中文图库'
            base.mkdir()
            png_path = base / '透明带EXIF.png'
            img = Image.new('RGBA', (40, 30), (255, 0, 0, 128))
            exif = Image.Exif()
            exif[0x010F] = 'TestCamera'
            img.save(png_path, format='PNG', exif=exif.tobytes())

            # strip_exif=False 且 RGBA -> JPG 之前会绕过白底转换报错，现应成功并输出 RGB JPEG
            res = tools_image.process_convert_compress(
                [str(png_path)], target_fmt='jpg', quality=85, strip_exif=False, out_dir=base
            )
            out_path = Path(res['files'][0]['path'])
            self.assertTrue(out_path.exists())
            with Image.open(out_path) as out_img:
                self.assertEqual(out_img.format, 'JPEG')
                self.assertEqual(out_img.mode, 'RGB')

    def test_avif_roundtrip_if_supported(self):
        if not features.check('avif'):
            self.skipTest('当前 Pillow 未启用 AVIF')
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            src = base / 'sample.png'
            Image.new('RGB', (32, 24), (10, 120, 220)).save(src)
            res = tools_image.process_convert_compress([str(src)], target_fmt='avif', out_dir=base)
            avif_path = Path(res['files'][0]['path'])
            self.assertEqual(avif_path.suffix.lower(), '.avif')
            # 再把 AVIF 转回 PNG
            res2 = tools_image.process_convert_compress([str(avif_path)], target_fmt='png', out_dir=base)
            self.assertTrue(Path(res2['files'][0]['path']).exists())

    def test_heic_read_and_ffmpeg_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / '苹果相册'
            base.mkdir()
            heic_path = base / '照片样本.heic'

            # 1. 若安装了 pillow-heif，实测真实 HEIC 编码 -> 读取转 JPG 闭环
            has_heif = False
            try:
                import pillow_heif
                pillow_heif.register_heif_opener()
                has_heif = True
            except Exception:
                pass

            if has_heif:
                Image.new('RGB', (48, 36), (220, 80, 40)).save(heic_path, format='HEIF', quality=80)
                res = tools_image.process_convert_compress([str(heic_path)], target_fmt='keep', out_dir=base)
                jpg_out = Path(res['files'][0]['path'])
                self.assertEqual(jpg_out.suffix.lower(), '.jpg')
                with Image.open(jpg_out) as im:
                    self.assertEqual(im.size, (48, 36))

            # 2. 模拟 Pillow 无法直接打开 HEIC 时自动回退 _decode_via_ffmpeg
            fake_heic = base / '回退测试.heic'
            fake_heic.write_bytes(b'fake_heic')
            fallback_img = Image.new('RGB', (32, 32), (10, 200, 100))
            with mock.patch.object(tools_image.Image, 'open', side_effect=OSError('cannot identify')), \
                 mock.patch.object(tools_image, '_decode_via_ffmpeg', return_value=fallback_img) as fb_mock:
                opened = tools_image._open_oriented(fake_heic)
                self.assertEqual(opened.size, (32, 32))
                fb_mock.assert_called_once()

    def test_rotate_flip_and_split_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / '图片目录'
            base.mkdir()
            src = base / '长图测试.png'
            Image.new('RGB', (60, 120), (30, 144, 255)).save(src)

            # 旋转 90° 后宽高应互换
            rot = tools_image.rotate_flip_images([str(src)], op='cw90', out_dir=base)
            self.assertEqual(rot['files'][0]['width'], 120)
            self.assertEqual(rot['files'][0]['height'], 60)

            # 空列表报错
            with self.assertRaises(ValueError):
                tools_image.rotate_flip_images([], op='cw90', out_dir=base)

            # 竖向按份数切分 3 份
            sp1 = tools_image.split_image(str(src), mode='vertical', parts=3, out_dir=base)
            self.assertEqual(sp1['count'], 3)
            self.assertTrue(Path(sp1['zip_path']).exists())

            # 按单段最大高度切分（120 / 50 -> 3 张）
            sp2 = tools_image.split_image(str(src), mode='vertical', max_piece_height=50, out_dir=base)
            self.assertEqual(sp2['count'], 3)

            # 九宫格切图（3x3 -> 9 张）
            sp3 = tools_image.split_image(str(src), mode='grid', rows=3, cols=3, out_dir=base)
            self.assertEqual(sp3['count'], 9)

            # 单段高度 >= 原图高度应报错
            with self.assertRaises(ValueError):
                tools_image.split_image(str(src), mode='vertical', max_piece_height=200, out_dir=base)

    def test_stitch_canvas_validation(self):
        with self.assertRaises(ValueError):
            tools_image._validate_canvas_size(100, 70000, 'jpg')
        with self.assertRaises(ValueError):
            tools_image._validate_canvas_size(20000, 20000, 'png')
        with self.assertRaises(ValueError):
            tools_image._validate_canvas_size(100, 100, 'exe')


class TestToolsPdf(unittest.TestCase):
    """PDF 页码解析表达式边界与 AES-256 加密/解锁。"""

    def test_parse_pages_ranges_order_dedup_and_bounds(self):
        self.assertEqual(tools_pdf.parse_pages('', 5), [0, 1, 2, 3, 4])
        self.assertEqual(tools_pdf.parse_pages('1-3，5, 2, 10-12', 6), [0, 1, 2, 4])
        # 支持倒序区间
        self.assertEqual(tools_pdf.parse_pages('4-2', 5), [3, 2, 1])
        # 非法字符应给出友好中文报错
        with self.assertRaises(ValueError) as ctx:
            tools_pdf.parse_pages('1-a', 5)
        self.assertIn('页码', str(ctx.exception))

    def test_protect_and_unlock_pdf(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / '文档测试'
            base.mkdir()
            src = base / '合同样本.pdf'
            doc = pymupdf.open()
            page = doc.new_page()
            page.insert_text((72, 72), 'Hello Local Toolbox')
            doc.save(src)
            doc.close()

            # 两个密码均空应报错
            with self.assertRaises(ValueError):
                tools_pdf.protect_pdf(str(src), user_pw='', owner_pw='', out_dir=base)

            # 设置打开密码加密
            enc = tools_pdf.protect_pdf(str(src), user_pw='secret123', allow_print=False, allow_copy=False, out_dir=base)
            enc_path = enc['path']
            info = tools_pdf.pdf_info(enc_path)
            self.assertTrue(info['needs_pass'])
            self.assertTrue(info['is_encrypted'])

            # 加密 PDF 送入合并/编辑/压缩应给出友好中文提示
            with self.assertRaises(ValueError) as ctx:
                tools_pdf.merge_pdfs([str(src), enc_path], out_dir=base)
            self.assertIn('解锁', str(ctx.exception))
            with self.assertRaises(ValueError) as ctx2:
                tools_pdf.edit_pages(enc_path, action='rotate', pages_expr='1', out_dir=base)
            self.assertIn('解锁', str(ctx2.exception))
            with self.assertRaises(ValueError) as ctx3:
                tools_pdf.compress_pdf(enc_path, out_dir=base)
            self.assertIn('解锁', str(ctx3.exception))

            # 旋转页码无有效匹配时应报错
            with self.assertRaises(ValueError):
                tools_pdf.edit_pages(str(src), action='rotate', pages_expr='99', out_dir=base)

            # 错误密码解锁失败
            with self.assertRaises(ValueError):
                tools_pdf.unlock_pdf(enc_path, password='wrong', out_dir=base)

            # 正确密码解锁成功
            dec = tools_pdf.unlock_pdf(enc_path, password='secret123', out_dir=base)
            dec_info = tools_pdf.pdf_info(dec['path'])
            self.assertFalse(dec_info['needs_pass'])
            self.assertFalse(dec_info['is_encrypted'])
            self.assertEqual(dec_info['pages'], 1)

    def test_images_to_pdf_transparent_png_has_white_background(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            trans_png = base / '透明图.png'
            Image.new('RGBA', (80, 80), (0, 0, 0, 0)).save(trans_png)
            res = tools_pdf.images_to_pdf([str(trans_png)], out_dir=base)
            with pymupdf.open(res['path']) as doc:
                pix = doc[0].get_pixmap(dpi=72)
                r, g, b = pix.pixel(40, 40)[:3]
                self.assertGreaterEqual(min(r, g, b), 245)


class TestToolsVideo(unittest.TestCase):
    """时间解析、视频任务并发上限、旋转指令构建与字幕互转。"""

    def test_time_to_seconds_formats(self):
        self.assertEqual(tools_video._time_to_seconds(''), 0.0)
        self.assertEqual(tools_video._time_to_seconds('45'), 45.0)
        self.assertEqual(tools_video._time_to_seconds('01:30'), 90.0)
        self.assertEqual(tools_video._time_to_seconds('01:02:03.5'), 3723.5)
        self.assertEqual(tools_video._time_to_seconds('bad'), 0.0)

    def test_video_task_manager_queues_and_cancels_cleanly(self):
        mgr = tools_video.VideoTaskManager()
        mgr._tasks['existing'] = {'id': 'existing', 'status': 'running', 'started_at': 0}
        mgr._worker_alive = True
        fake_info = {
            'duration': 8.0, 'can_remux_video': True, 'can_remux_audio': True,
            'audio_codec': 'aac', 'size_bytes': 2048,
        }
        with tempfile.TemporaryDirectory() as tmp:
            cn_dir = Path(tmp) / '中文视频目录'
            cn_dir.mkdir()
            src = cn_dir / '测试片段.mp4'
            src.write_bytes(b'00')
            with mock.patch.object(tools_video, 'ffmpeg_bins', return_value=('ffmpeg', 'ffprobe')), \
                 mock.patch.object(tools_video, 'probe_video', return_value=fake_info):
                t1 = mgr.start(str(src), 'compat', {'output_dir': str(cn_dir)})
                t2 = mgr.start(str(src), 'compat', {'output_dir': str(cn_dir)})
                self.assertEqual(t1['status'], 'queued')
                self.assertEqual(t1['queue_pos'], 1)
                self.assertEqual(t2['status'], 'queued')
                self.assertEqual(t2['queue_pos'], 2)

                # 取消排第 1 位的任务后，第 2 位应自动递补为第 1 位
                self.assertTrue(mgr.cancel(t1['id']))
                self.assertEqual(mgr.get(t1['id'])['status'], 'cancelled')
                self.assertEqual(mgr.get(t2['id'])['queue_pos'], 1)

                # 超出队列上限应给出友好报错
                mgr.MAX_QUEUE = 1
                with self.assertRaises(RuntimeError) as ctx:
                    mgr.start(str(src), 'compat', {'output_dir': str(cn_dir)})
                self.assertIn('上限', str(ctx.exception))

    def test_video_rotate_command_and_merge_validation(self):
        mgr = tools_video.VideoTaskManager()
        fake_info = {
            'duration': 10.0, 'can_remux_video': True, 'can_remux_audio': True,
            'audio_codec': 'aac', 'size_bytes': 1024,
        }
        with mock.patch.object(tools_video, 'has_nvenc', return_value=False):
            cmd, out_path, desc, dur = mgr._build_command(
                'ffmpeg', Path('demo.mp4'), fake_info, 'rotate',
                {'rotate_op': 'cw90', 'use_nvenc': False}, Path(tempfile.gettempdir())
            )
            self.assertIn('transpose=1,format=yuv420p', cmd)
            self.assertIn('顺时针90°', desc)
            self.assertEqual(dur, 10.0)

        with self.assertRaises(ValueError):
            mgr.start_merge(['only_one.mp4'])

    def test_subtitle_roundtrip_srt_vtt_ass_with_gbk(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / '字幕测试'
            base.mkdir()
            srt_path = base / '示例字幕.srt'
            srt_content = (
                '1\n00:00:01,200 --> 00:00:03,500\n你好，本地工具箱\n第二行字幕\n\n'
                '2\n00:00:04,000 --> 00:00:06,250\n测试完成\n'
            )
            # 用 GB18030 写入以测试自动编码识别
            srt_path.write_bytes(srt_content.encode('gb18030'))

            vtt = tools_video.convert_subtitle(str(srt_path), target_fmt='vtt', out_dir=base)
            self.assertEqual(vtt['cues'], 2)
            self.assertEqual(vtt['detected_encoding'], 'gb18030')
            vtt_txt = Path(vtt['path']).read_text(encoding='utf-8')
            self.assertTrue(vtt_txt.startswith('WEBVTT'))
            self.assertIn('00:00:01.200 --> 00:00:03.500', vtt_txt)

            ass = tools_video.convert_subtitle(vtt['path'], target_fmt='ass', out_dir=base)
            self.assertEqual(ass['cues'], 2)
            ass_txt = Path(ass['path']).read_text(encoding='utf-8')
            self.assertIn('Dialogue: 0,0:00:01.20,0:00:03.50,Default,,0,0,0,,你好，本地工具箱\\N第二行字幕', ass_txt)

            back_srt = tools_video.convert_subtitle(ass['path'], target_fmt='srt', out_dir=base)
            self.assertEqual(back_srt['cues'], 2)
            back_txt = Path(back_srt['path']).read_text(encoding='utf-8')
            self.assertIn('你好，本地工具箱\n第二行字幕', back_txt)

            # 空字幕文件应报错
            empty_sub = base / 'empty.srt'
            empty_sub.write_text('', encoding='utf-8')
            with self.assertRaises(ValueError):
                tools_video.convert_subtitle(str(empty_sub), target_fmt='vtt', out_dir=base)

            # 空行含空格的 SRT 与 UTF-16 BOM 字幕均应正确分块解析
            sp_sub = base / 'space_blank.srt'
            sp_sub.write_text(
                '1\n00:00:01,000 --> 00:00:02,000\n第一句\n \n2\n00:00:03,000 --> 00:00:04,000\n第二句\n',
                encoding='utf-8',
            )
            sp_res = tools_video.convert_subtitle(str(sp_sub), target_fmt='vtt', out_dir=base)
            self.assertEqual(sp_res['cues'], 2)

            u16_sub = base / 'utf16.srt'
            u16_sub.write_bytes('1\n00:00:01,000 --> 00:00:02,000\n你好世界\n'.encode('utf-16'))
            u16_res = tools_video.convert_subtitle(str(u16_sub), target_fmt='vtt', out_dir=base)
            self.assertEqual(u16_res['cues'], 1)
            self.assertEqual(u16_res['detected_encoding'], 'utf-16')

    def test_export_video_frames_interval_exceeds_duration_does_not_crash(self):
        ffmpeg, _ = tools_video.ffmpeg_bins()
        if not ffmpeg:
            self.skipTest('未安装 FFmpeg')
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            clip = base / '短片.mp4'
            subprocess.run(
                [ffmpeg, '-y', '-hide_banner', '-loglevel', 'error',
                 '-f', 'lavfi', '-i', 'testsrc=duration=1:size=160x120:rate=25',
                 '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(clip)],
                check=True,
            )
            res = tools_video.export_video_frames(str(clip), mode='interval', interval=5.0, fmt='jpg', out_dir=base)
            self.assertGreaterEqual(res['count'], 1)
            self.assertTrue(Path(res['path']).exists())


class TestServerAndTray(unittest.TestCase):
    """系统托盘图标生成与本地 HTTP 服务 Host / Token 安全拦截验证。"""

    def test_tray_icon_gdi_creation(self):
        import tray
        hicon = tray._make_toolbox_icon()
        self.assertTrue(bool(hicon))
        tray.user32.DestroyIcon(hicon)

    def test_server_host_get_token_and_post_whitelist_defense_in_depth(self):
        import json
        import threading
        from urllib.error import HTTPError
        from urllib.parse import quote
        from urllib.request import Request, urlopen
        import server

        httpd, port = server.create_server(18700)
        tok = httpd.api_token
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        log_patcher = mock.patch.object(server, 'log')
        log_patcher.start()
        try:
            # 1. /api/health 仅返回基础存活布尔值，不暴露本机路径
            with urlopen(f'http://127.0.0.1:{port}/api/health', timeout=3) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                self.assertEqual(data, {'ok': True})

            # 2. 伪造 Host 头应被 403 拦截（防 DNS Rebinding）
            bad_host_req = Request(f'http://127.0.0.1:{port}/api/health', headers={'Host': 'evil.example.com'})
            with self.assertRaises(HTTPError) as ctx1:
                urlopen(bad_host_req, timeout=3)
            self.assertEqual(ctx1.exception.code, 403)

            # 3. GET /api/* 未携带 Token 一律 403 拦截；携带 Header 或 Query Token 正常放行
            for sub in ('/api/env', '/api/preview?path=x', '/api/download?path=x', '/api/video/thumb?path=x', '/api/video/task/1'):
                with self.assertRaises(HTTPError) as ctx_g:
                    urlopen(f'http://127.0.0.1:{port}{sub}', timeout=3)
                self.assertEqual(ctx_g.exception.code, 403)

            env_req = Request(f'http://127.0.0.1:{port}/api/env', headers={'X-Toolbox-Token': tok})
            with urlopen(env_req, timeout=3) as resp_env:
                env_data = json.loads(resp_env.read().decode('utf-8'))
                self.assertIn('output_dir', env_data)

            # 4. 缺少 X-Toolbox-Token 的 POST 请求应被 403 拦截（防 CSRF）
            no_tok_req = Request(
                f'http://127.0.0.1:{port}/api/rename/preview',
                data=b'{}',
                headers={'Content-Type': 'application/json'},
                method='POST',
            )
            with self.assertRaises(HTTPError) as ctx2:
                urlopen(no_tok_req, timeout=3)
            self.assertEqual(ctx2.exception.code, 403)

            # 5. 携带合法 Token，但传入未经白名单授权的文件或文件夹路径 -> 必须被 403 拦截
            with tempfile.TemporaryDirectory() as tmp:
                secret_dir = Path(tmp) / '未授权中文目录'
                secret_dir.mkdir()
                secret_file = secret_dir / '机密.txt'
                secret_file.write_text('hello', encoding='utf-8')

                def post_json(api_path, payload):
                    req = Request(
                        f'http://127.0.0.1:{port}{api_path}',
                        data=json.dumps(payload).encode('utf-8'),
                        headers={'Content-Type': 'application/json', 'X-Toolbox-Token': tok},
                        method='POST',
                    )
                    return urlopen(req, timeout=3)

                with self.assertRaises(HTTPError) as ctx_f:
                    post_json('/api/file/hash', {'path': str(secret_file)})
                self.assertEqual(ctx_f.exception.code, 403)

                with self.assertRaises(HTTPError) as ctx_d:
                    post_json('/api/rename/preview', {'folder': str(secret_dir)})
                self.assertEqual(ctx_d.exception.code, 403)

                # 模拟经系统弹窗授权加入白名单后，GET 预览（带 query token）与 POST 处理均正常放行
                httpd.allowed_paths.add(str(secret_file.resolve()).lower())
                httpd.allowed_folders.add(str(secret_dir.resolve()).lower())

                with post_json('/api/file/hash', {'path': str(secret_file)}) as ok_f:
                    self.assertEqual(ok_f.status, 200)
                with post_json('/api/rename/preview', {'folder': str(secret_dir)}) as ok_d:
                    self.assertEqual(ok_d.status, 200)
                with urlopen(
                    f'http://127.0.0.1:{port}/api/preview?path={quote(str(secret_file))}&token={tok}',
                    timeout=3,
                ) as ok_prev:
                    self.assertEqual(ok_prev.read(), b'hello')

            # 6. /api/upload 流式上传（中文文件名、自动通过白名单计算哈希、超限 413 拦截）与未预期异常脱敏验证
            uploaded_temp = None
            try:
                payload_bytes = '流式上传中文内容测试 12345'.encode('utf-8')
                up_req = Request(
                    f"http://127.0.0.1:{port}/api/upload?name={quote('测试上传文档.txt')}",
                    data=payload_bytes,
                    headers={'X-Toolbox-Token': tok, 'Content-Length': str(len(payload_bytes))},
                    method='POST',
                )
                with urlopen(up_req, timeout=3) as up_resp:
                    up_data = json.loads(up_resp.read().decode('utf-8'))
                uploaded_temp = Path(up_data['path'])
                self.assertTrue(uploaded_temp.exists())
                self.assertEqual(up_data['name'], '测试上传文档.txt')

                # 上传目录内的文件无需额外 pick-files 即可直接通过白名单计算哈希
                hash_req = Request(
                    f'http://127.0.0.1:{port}/api/file/hash',
                    data=json.dumps({'path': str(uploaded_temp)}).encode('utf-8'),
                    headers={'Content-Type': 'application/json', 'X-Toolbox-Token': tok},
                    method='POST',
                )
                with urlopen(hash_req, timeout=3) as h_resp:
                    h_data = json.loads(h_resp.read().decode('utf-8'))
                self.assertEqual(h_data['md5'], hashlib.md5(payload_bytes).hexdigest())

                # 超出 4GB 上限的 Content-Length 应立即返回 413
                huge_req = Request(
                    f'http://127.0.0.1:{port}/api/upload?name=huge.bin',
                    data=b'x',
                    headers={'X-Toolbox-Token': tok, 'Content-Length': str(server.MAX_UPLOAD_BYTES + 10)},
                    method='POST',
                )
                with self.assertRaises(HTTPError) as ctx_413:
                    urlopen(huge_req, timeout=3)
                self.assertEqual(ctx_413.exception.code, 413)

                # 模拟内部抛出未预期 KeyError（含敏感路径），前端只能收到 500 通用脱敏提示（静音测试日志避免污染真实 DeskKit_error.log）
                with mock.patch.object(server, 'log'), \
                     mock.patch.object(server, 'calc_file_hash', side_effect=KeyError(r'C:\Users\secret_internal_key')):
                    err_req = Request(
                        f'http://127.0.0.1:{port}/api/file/hash',
                        data=json.dumps({'path': str(uploaded_temp)}).encode('utf-8'),
                        headers={'Content-Type': 'application/json', 'X-Toolbox-Token': tok},
                        method='POST',
                    )
                    with self.assertRaises(HTTPError) as ctx_500:
                        urlopen(err_req, timeout=3)
                    self.assertEqual(ctx_500.exception.code, 500)
                    err_body = ctx_500.exception.read().decode('utf-8')
                    self.assertNotIn('secret_internal_key', err_body)
            finally:
                if uploaded_temp is not None:
                    uploaded_temp.unlink(missing_ok=True)
        finally:
            log_patcher.stop()
            httpd.shutdown()
            httpd.server_close()

    def test_audit_fixes_gif_guard_queue_collision_pdf_space_pw_big5_sjis_and_http_keepalive(self):
        """覆盖深度体检修复项：GIF内存保护、视频排队防覆盖误删、PDF空格密码与零散文件、Big5/日文识别、细长图拼图及HTTP长连接防粘包。"""
        import http.client
        import json
        import threading
        import server

        # 1. 视频转 GIF：未填结束时间强制补齐 -t 6.000s，超 30s 报错，开始时间超总时长报错
        mgr = tools_video.VideoTaskManager()
        long_info = {
            'duration': 1800.0, 'can_remux_video': True, 'can_remux_audio': True,
            'audio_codec': 'aac', 'size_bytes': 10_000_000,
        }
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / '视频输出'
            out_dir.mkdir()
            cmd_gif, _, desc_gif, est_gif = mgr._build_command(
                'ffmpeg', Path('半小时长片.mp4'), long_info, 'gif', {}, out_dir,
            )
            self.assertIn('-t', cmd_gif)
            t_idx = cmd_gif.index('-t')
            self.assertEqual(cmd_gif[t_idx + 1], '6.000')
            self.assertEqual(est_gif, 6.0)

            with self.assertRaises(ValueError):
                mgr._build_command('ffmpeg', Path('半小时长片.mp4'), long_info, 'gif', {'start': '0', 'end': '45'}, out_dir)
            with self.assertRaises(ValueError):
                mgr._build_command('ffmpeg', Path('半小时长片.mp4'), long_info, 'gif', {'start': '1900'}, out_dir)

            # 2. 视频排队原子输出名防碰撞覆盖 & 取消排队任务绝不误删磁盘已有成品
            mgr2 = tools_video.VideoTaskManager()
            mgr2._tasks['busy'] = {'id': 'busy', 'status': 'running', 'started_at': 0}
            mgr2._worker_alive = True
            src_v = out_dir / '样片.mp4'
            src_v.write_bytes(b'00')
            existing_done = out_dir / '样片_兼容.mp4'
            existing_done.write_bytes(b'finished_video_data')

            with mock.patch.object(tools_video, 'ffmpeg_bins', return_value=('ffmpeg', 'ffprobe')), \
                 mock.patch.object(tools_video, 'probe_video', return_value=long_info):
                q1 = mgr2.start(str(src_v), 'compat', {'output_dir': str(out_dir)})
                q2 = mgr2.start(str(src_v), 'compat', {'output_dir': str(out_dir)})
                q3 = mgr2.start(str(src_v), 'compat', {'output_dir': str(out_dir)})
                self.assertEqual(
                    [q1['output_name'], q2['output_name'], q3['output_name']],
                    ['样片_兼容_2.mp4', '样片_兼容_3.mp4', '样片_兼容_4.mp4'],
                )
                # 取消 q1 后，已有成品与其余文件完好无损，且释放出的 _2 名称可被后续新任务复用
                mgr2.cancel(q1['id'])
                self.assertEqual(existing_done.read_bytes(), b'finished_video_data')
                q4 = mgr2.start(str(src_v), 'compat', {'output_dir': str(out_dir)})
                self.assertEqual(q4['output_name'], '样片_兼容_2.mp4')

                # 60fps 视频重编码合并保留 fps=60
                info_60 = dict(long_info, width=1920, height=1080, fps=60.0, video_codec='h264')
                with mock.patch.object(tools_video, 'probe_video', return_value=info_60), \
                     mock.patch.object(tools_video, 'has_nvenc', return_value=False):
                    m_task = mgr2.start_merge([str(src_v), str(src_v)], {'reencode': True, 'output_dir': str(out_dir)})
                    queued_cmd = [it[1] for it in mgr2._queue if it[0] == m_task['id']][0]
                    fc_str = queued_cmd[queued_cmd.index('-filter_complex') + 1]
                    self.assertIn('fps=60', fc_str)

        # 3. PDF 首尾带空格密码原样加密与解锁 + 拆分/转多图/切图零散文件污染
        with tempfile.TemporaryDirectory() as tmp:
            p_dir = Path(tmp) / 'PDF整洁测试'
            p_dir.mkdir()
            src_pdf = p_dir / '三页文档.pdf'
            doc = pymupdf.open()
            for i in range(3):
                pg = doc.new_page()
                pg.insert_text((72, 72), f'Page {i + 1}')
            doc.save(src_pdf)
            doc.close()

            out_sub = p_dir / 'out'
            enc = tools_pdf.protect_pdf(str(src_pdf), user_pw='  space pw  ', out_dir=out_sub)
            with self.assertRaises(ValueError):
                tools_pdf.unlock_pdf(enc['path'], password='space pw', out_dir=out_sub)
            dec = tools_pdf.unlock_pdf(enc['path'], password='  space pw  ', out_dir=out_sub)
            self.assertEqual(tools_pdf.pdf_info(dec['path'])['pages'], 3)

            split_out = p_dir / 'split_clean'
            sp_res = tools_pdf.edit_pages(str(src_pdf), action='split_all', out_dir=split_out)
            self.assertEqual([f.name for f in split_out.iterdir()], [Path(sp_res['path']).name])
            with zipfile.ZipFile(sp_res['path']) as zf:
                self.assertEqual(len(zf.namelist()), 3)

            img_out = p_dir / 'img_clean'
            pi_res = tools_pdf.pdf_to_images(str(src_pdf), fmt='png', out_dir=img_out)
            self.assertEqual([f.name for f in img_out.iterdir()], [Path(pi_res['path']).name])
            with zipfile.ZipFile(pi_res['path']) as zf:
                self.assertEqual(len(zf.namelist()), 3)

            # 切图零散文件污染 + 超宽细长条图片拼图防 0 像素崩溃
            grid_out = p_dir / 'grid_clean'
            tall_img = p_dir / 'tall.png'
            Image.new('RGB', (90, 90), (20, 40, 80)).save(tall_img)
            g_res = tools_image.split_image(str(tall_img), mode='grid', rows=3, cols=3, out_dir=grid_out)
            self.assertEqual([f.name for f in grid_out.iterdir()], [Path(g_res['zip_path']).name])

            thin = p_dir / 'thin.png'
            small = p_dir / 'small.png'
            Image.new('RGB', (1000, 1), (255, 0, 0)).save(thin)
            Image.new('RGB', (50, 50), (0, 255, 0)).save(small)
            for st_mode in ('vertical', 'horizontal', 'grid'):
                st_res = tools_image.stitch_images([str(thin), str(small)], mode=st_mode, out_dir=p_dir)
                self.assertGreaterEqual(st_res['width'], 1)
                self.assertGreaterEqual(st_res['height'], 1)

        # 4. 繁体 Big5 / 日文 Shift_JIS 乱码自动识别 + 下载目录迁移 + 含逗号文件定位
        with tempfile.TemporaryDirectory() as tmp:
            enc_dir = Path(tmp) / '多语种测试'
            enc_dir.mkdir()
            big5_txt = '繁體中文測試檔案，臺灣年度財務報告與資料彙整說明\n'
            big5_file = enc_dir / 'big5_doc.txt'
            big5_file.write_bytes(big5_txt.encode('big5'))
            r_b5 = tools_files.fix_text_encoding(str(big5_file), source_encoding='auto', target_encoding='utf-8', out_dir=enc_dir)
            self.assertEqual(r_b5['detected_encoding'], 'big5')
            self.assertEqual(Path(r_b5['path']).read_text(encoding='utf-8'), big5_txt)

            sjis_txt = '日本語のテキストファイルです。文字化けテスト確認と修正。\n'
            sjis_file = enc_dir / 'sjis_doc.txt'
            sjis_file.write_bytes(sjis_txt.encode('shift_jis'))
            r_sj = tools_files.fix_text_encoding(str(sjis_file), source_encoding='auto', target_encoding='utf-8', out_dir=enc_dir)
            self.assertEqual(r_sj['detected_encoding'], 'shift_jis')
            self.assertEqual(Path(r_sj['path']).read_text(encoding='utf-8'), sjis_txt)

            # 含英文逗号输出文件定位
            comma_out = enc_dir / '报表,2026,终版.pdf'
            comma_out.write_bytes(b'%PDF')
            with mock.patch.object(tools_files, 'OUTPUT_DIR', enc_dir), \
                 mock.patch.object(tools_files, '_select_file_via_shell', return_value=True) as sh_sel:
                tools_files.open_in_explorer(str(comma_out))
                sh_sel.assert_called_once_with(comma_out.resolve())

        # 5. 路径脱敏正则（含空格目录与正斜杠）、只读目录日志回退与 HTTP/1.1 错误断连防粘包
        san1 = server._sanitize_error_msg(r'无法打开 C:\Program Files\My App\secret file.docx: 权限不足')
        self.assertNotIn('Program Files', san1)
        self.assertNotIn('secret file', san1)
        self.assertIn('<本地路径>', san1)

        san2 = server._sanitize_error_msg('Read failed at D:/My Workspace/Private Folder/data.csv!')
        self.assertNotIn('My Workspace', san2)
        self.assertNotIn('Private Folder', san2)

        with mock.patch.object(server.os, 'access', return_value=False):
            fb_log = server._resolve_log_path()
            self.assertEqual(fb_log.parent, Path(tempfile.gettempdir()))

        httpd2, port2 = server.create_server(18730)
        tok2 = httpd2.api_token
        t2 = threading.Thread(target=httpd2.serve_forever, daemon=True)
        t2.start()
        try:
            conn = http.client.HTTPConnection('127.0.0.1', port2, timeout=3)
            try:
                conn.request('POST', '/api/rename/preview', body=b'{"x": 123}', headers={'Content-Type': 'application/json'})
                resp403 = conn.getresponse()
                resp403.read()
                self.assertEqual(resp403.status, 403)
                self.assertEqual(resp403.getheader('Connection'), 'close')
            finally:
                conn.close()

            # 6. /api/cleanup-uploads：清理闲置临时上传副本，但保护正在后台队列中的输入文件
            tools_files.ensure_dirs()
            idle_up = tools_files.UPLOAD_DIR / '__tb_deadbeef_idle.mp4'
            busy_up = tools_files.UPLOAD_DIR / '__tb_deadbeef_busy.mp4'
            idle_up.write_bytes(b'111')
            busy_up.write_bytes(b'222')
            try:
                with mock.patch.object(server.video_tasks, 'active_input_paths', return_value={str(busy_up.resolve())}):
                    c2 = http.client.HTTPConnection('127.0.0.1', port2, timeout=3)
                    try:
                        c2.request(
                            'POST', '/api/cleanup-uploads',
                            body=json.dumps({'paths': [str(idle_up), str(busy_up)]}).encode('utf-8'),
                            headers={'Content-Type': 'application/json', 'X-Toolbox-Token': tok2},
                        )
                        r_clean = json.loads(c2.getresponse().read().decode('utf-8'))
                        self.assertEqual(r_clean['removed'], 1)
                        self.assertFalse(idle_up.exists())
                        self.assertTrue(busy_up.exists())
                    finally:
                        c2.close()
            finally:
                idle_up.unlink(missing_ok=True)
                busy_up.unlink(missing_ok=True)
        finally:
            httpd2.shutdown()
            httpd2.server_close()


if __name__ == '__main__':
    unittest.main()
