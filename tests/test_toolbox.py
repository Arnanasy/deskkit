"""本地工具箱核心逻辑单元测试（纯标准库，不触碰真实用户文件、FFmpeg 或 Word）。"""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import tools_files
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


class TestToolsPdf(unittest.TestCase):
    """PDF 页码解析表达式边界。"""

    def test_parse_pages_ranges_order_dedup_and_bounds(self):
        self.assertEqual(tools_pdf.parse_pages('', 5), [0, 1, 2, 3, 4])
        self.assertEqual(tools_pdf.parse_pages('1-3，5, 2, 10-12', 6), [0, 1, 2, 4])
        # 支持倒序区间
        self.assertEqual(tools_pdf.parse_pages('4-2', 5), [3, 2, 1])


class TestToolsVideo(unittest.TestCase):
    """时间解析与视频任务并发上限。"""

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


if __name__ == '__main__':
    unittest.main()
