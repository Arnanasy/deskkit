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


class TestToolsPdf(unittest.TestCase):
    """PDF 页码解析表达式边界与 AES-256 加密/解锁。"""

    def test_parse_pages_ranges_order_dedup_and_bounds(self):
        self.assertEqual(tools_pdf.parse_pages('', 5), [0, 1, 2, 3, 4])
        self.assertEqual(tools_pdf.parse_pages('1-3，5, 2, 10-12', 6), [0, 1, 2, 4])
        # 支持倒序区间
        self.assertEqual(tools_pdf.parse_pages('4-2', 5), [3, 2, 1])

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

    def test_video_task_manager_enforces_concurrency_limit(self):
        mgr = tools_video.VideoTaskManager()
        mgr._tasks['existing'] = {'id': 'existing', 'status': 'running', 'started_at': 0}
        with mock.patch.object(tools_video, 'ffmpeg_bins', return_value=('ffmpeg', 'ffprobe')):
            with self.assertRaises(RuntimeError) as ctx:
                mgr.start('dummy.mp4', 'compat')
            self.assertIn('正在处理中', str(ctx.exception))

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


if __name__ == '__main__':
    unittest.main()
