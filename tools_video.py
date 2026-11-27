"""视频工坊：ffprobe 编码检测、一键转 Win 通用 MP4（无损换壳/NVENC/x264）、压缩、裁剪、旋转、多视频合并、提音频、转 GIF、批量截图、字幕互转。"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
import zipfile

from tools_files import OUTPUT_DIR, UPLOAD_DIR, clean_stem, ensure_dirs, touch_upload_if_temp, unique_path

_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
_NVENC_CACHE = None
DEFAULT_GIF_SECONDS = 6.0
MAX_GIF_SECONDS = 30.0


def ffmpeg_bins():
    return shutil.which('ffmpeg'), shutil.which('ffprobe')


def has_nvenc():
    """实测 NVIDIA h264_nvenc 在本机是否可真实编码（避免有驱动但版本不匹配时报错）。"""
    global _NVENC_CACHE
    if _NVENC_CACHE is not None:
        return _NVENC_CACHE
    ffmpeg, _ = ffmpeg_bins()
    if not ffmpeg:
        _NVENC_CACHE = False
        return False
    try:
        run = subprocess.run(
            [ffmpeg, '-hide_banner', '-loglevel', 'error',
             '-f', 'lavfi', '-i', 'color=c=black:s=256x256:d=0.1',
             '-c:v', 'h264_nvenc', '-f', 'null', '-'],
            capture_output=True, timeout=6, creationflags=_NO_WINDOW,
        )
        _NVENC_CACHE = (run.returncode == 0)
    except Exception:
        _NVENC_CACHE = False
    return _NVENC_CACHE


def _parse_fps(rate_str):
    if not rate_str or rate_str == '0/0':
        return 0.0
    if '/' in rate_str:
        a, b = rate_str.split('/', 1)
        try:
            return round(float(a) / float(b), 2) if float(b) else 0.0
        except ValueError:
            return 0.0
    try:
        return round(float(rate_str), 2)
    except ValueError:
        return 0.0


def probe_video(path_str):
    """读取视频容器、编码、色彩位深、时长并给出 Windows 兼容性诊断。"""
    _, ffprobe = ffmpeg_bins()
    if not ffprobe:
        raise RuntimeError('未找到 ffprobe，请确认已安装 FFmpeg')
    path = Path(path_str)
    if not path.exists():
        raise FileNotFoundError('视频文件不存在')
    run = subprocess.run(
        [ffprobe, '-v', 'quiet', '-print_format', 'json', '-show_format', '-show_streams', str(path)],
        capture_output=True, text=True, encoding='utf-8', timeout=15, creationflags=_NO_WINDOW,
    )
    if run.returncode != 0 or not run.stdout.strip():
        raise RuntimeError('无法解析该媒体文件，可能已损坏或不是有效视频')
    data = json.loads(run.stdout)
    streams = data.get('streams', [])
    fmt = data.get('format', {})

    v = next((s for s in streams if s.get('codec_type') == 'video'), None)
    a = next((s for s in streams if s.get('codec_type') == 'audio'), None)

    v_codec = (v.get('codec_name') or '').lower() if v else ''
    pix_fmt = (v.get('pix_fmt') or '').lower() if v else ''
    a_codec = (a.get('codec_name') or '').lower() if a else ''
    duration = float(fmt.get('duration') or (v.get('duration') if v else 0) or 0)
    size_bytes = int(fmt.get('size') or path.stat().st_size)
    ext = path.suffix.lower()

    # 判断 Windows 自带播放器兼容性
    issues = []
    if v_codec and v_codec != 'h264':
        issues.append(f'视频编码为 {v_codec.upper()}（Win 自带播放器常缺少解码器）')
    if pix_fmt and pix_fmt not in ('yuv420p', 'yuvj420p', 'nv12'):
        issues.append(f'色彩格式为 {pix_fmt}（非 8-bit 4:2:0，易黑屏或花屏）')
    if a_codec and a_codec not in ('aac', 'mp3'):
        issues.append(f'音频编码为 {a_codec.upper()}（建议转为 AAC）')
    if ext not in ('.mp4', '.m4v'):
        issues.append(f'封装格式为 {ext or "未知"}（建议封装为 MP4）')

    can_remux_video = (v_codec == 'h264' and pix_fmt in ('yuv420p', 'yuvj420p', 'nv12', ''))
    can_remux_audio = (not a_codec) or (a_codec in ('aac', 'mp3'))

    if not issues:
        advice = '当前视频已完全兼容 Windows 自带播放器，通常无需转码。'
    elif can_remux_video:
        advice = '视频流本身已是兼容 H.264，可走「无损秒换壳」，几秒完成且零画质损失！'
    else:
        advice = '需要重新编码为 H.264 (8-bit) + AAC；开启硬件加速可大幅提速。'

    return {
        'path': str(path),
        'name': clean_stem(path) + path.suffix,
        'size_bytes': size_bytes,
        'duration': round(duration, 2),
        'width': v.get('width', 0) if v else 0,
        'height': v.get('height', 0) if v else 0,
        'fps': _parse_fps(v.get('avg_frame_rate') or v.get('r_frame_rate')) if v else 0,
        'video_codec': v_codec or '无',
        'pix_fmt': pix_fmt or '未知',
        'audio_codec': a_codec or '无音轨',
        'compatible': len(issues) == 0,
        'can_remux_video': can_remux_video,
        'can_remux_audio': can_remux_audio,
        'issues': issues,
        'advice': advice,
        'nvenc_available': has_nvenc(),
    }


def _parse_time_str(t):
    """校验并返回合法时间字符串（如 00:01:20 或 80），空则返回 None。"""
    if t is None:
        return None
    s = str(t).strip()
    return s if s else None


def _time_to_seconds(s):
    if not s:
        return 0.0
    parts = s.split(':')
    try:
        vals = [float(p) for p in parts]
    except ValueError:
        return 0.0
    if len(vals) == 1:
        return vals[0]
    if len(vals) == 2:
        return vals[0] * 60 + vals[1]
    if len(vals) == 3:
        return vals[0] * 3600 + vals[1] * 60 + vals[2]
    return 0.0


class VideoTaskManager:
    """后台执行 FFmpeg 转码任务（单并发保护 CPU/显卡，多任务自动排队依次执行，支持随时取消与回收）。"""

    MAX_HISTORY = 50
    MAX_CONCURRENT = 1
    MAX_QUEUE = 20

    def __init__(self):
        self._tasks = {}
        self._queue = []            # [(task_id, cmd, out_path, est_duration, cleanup_paths), ...]
        self._reserved_outputs = set()
        self._worker_alive = False
        self._lock = threading.Lock()

    def _reserve_output(self, out_dir, stem, ext):
        with self._lock:
            out_path = unique_path(out_dir, stem, ext, reserved=self._reserved_outputs)
            self._reserved_outputs.add(os.path.normcase(str(out_path.resolve())))
            return out_path

    def _release_reserved_locked(self, out_path):
        if out_path is not None:
            self._reserved_outputs.discard(os.path.normcase(str(Path(out_path).resolve())))

    def active_input_paths(self):
        """返回当前所有排队中或运行中任务正在引用的输入文件及辅助临时文件路径集合。"""
        with self._lock:
            active = set()
            for t in self._tasks.values():
                if t.get('status') in ('running', 'queued'):
                    active.update(t.get('input_paths') or ())
                    active.update(t.get('cleanup_paths') or ())
            return active

    def _prune_locked(self):
        finished = [
            (tid, t.get('started_at', 0))
            for tid, t in self._tasks.items()
            if t.get('status') not in ('running', 'queued')
        ]
        if len(finished) > self.MAX_HISTORY:
            finished.sort(key=lambda x: x[1])
            for tid, _ in finished[:len(finished) - self.MAX_HISTORY]:
                self._tasks.pop(tid, None)

    def _queue_position_locked(self, task_id):
        for idx, item in enumerate(self._queue, 1):
            if item[0] == task_id:
                return idx
        return 0

    def get(self, task_id):
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None
            snap = {k: v for k, v in task.items() if k not in ('_proc', 'input_paths')}
            if snap.get('status') == 'queued':
                snap['queue_pos'] = self._queue_position_locked(task_id)
            return snap

    def cancel(self, task_id):
        cleanup = []
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False
            task['cancelled'] = True
            if task.get('status') == 'queued':
                task['status'] = 'cancelled'
                kept = []
                for item in self._queue:
                    if item[0] == task_id:
                        # 排队中尚未启动 FFmpeg 进程，仅释放预留输出名与临时辅助文件，严禁误删磁盘已有文件
                        self._release_reserved_locked(item[2])
                        cleanup.extend(item[4] or [])
                    else:
                        kept.append(item)
                self._queue = kept
            else:
                proc = task.get('_proc')
                if proc and proc.poll() is None:
                    try:
                        proc.terminate()
                    except OSError:
                        pass
        for cp in cleanup:
            try:
                Path(cp).unlink(missing_ok=True)
            except OSError:
                pass
        return True

    def cancel_all(self):
        """退出服务时取消排队任务并终止全部运行中的 FFmpeg 子进程，避免遗留孤儿进程。"""
        cleanup = []
        with self._lock:
            for tid, _cmd, out_p, _dur, cps in self._queue:
                t = self._tasks.get(tid)
                if t:
                    t['cancelled'] = True
                    t['status'] = 'cancelled'
                self._release_reserved_locked(out_p)
                cleanup.extend(cps or [])
            self._queue.clear()
            for task in self._tasks.values():
                if task.get('status') == 'running':
                    task['cancelled'] = True
                    proc = task.get('_proc')
                    if proc and proc.poll() is None:
                        try:
                            proc.terminate()
                        except OSError:
                            pass
        for cp in cleanup:
            try:
                Path(cp).unlink(missing_ok=True)
            except OSError:
                pass

    def _enqueue_or_start(self, task, cmd, out_path, est_duration, cleanup_paths=None):
        task_id = task['id']
        if cleanup_paths:
            task['cleanup_paths'] = [str(Path(cp).resolve()) for cp in cleanup_paths]
        for ip in (task.get('input_paths') or ()):
            touch_upload_if_temp(ip)
        for cp in (cleanup_paths or ()):
            touch_upload_if_temp(cp)
        with self._lock:
            if len(self._queue) >= self.MAX_QUEUE:
                self._release_reserved_locked(out_path)
                for cp in (cleanup_paths or []):
                    try:
                        Path(cp).unlink(missing_ok=True)
                    except OSError:
                        pass
                raise RuntimeError(f'排队中的视频任务已达上限（{self.MAX_QUEUE} 个），请稍后再添加')
            self._prune_locked()
            running = sum(1 for t in self._tasks.values() if t.get('status') == 'running')
            need_spawn = False
            if running < self.MAX_CONCURRENT and not self._worker_alive:
                task['status'] = 'running'
                task['started_at'] = time.time()
                self._tasks[task_id] = task
                self._worker_alive = True
                need_spawn = True
                first_job = (task_id, cmd, out_path, est_duration, cleanup_paths)
            else:
                task['status'] = 'queued'
                self._tasks[task_id] = task
                self._queue.append((task_id, cmd, out_path, est_duration, cleanup_paths))
                if running < self.MAX_CONCURRENT and not self._worker_alive:
                    first_job = self._queue.pop(0)
                    self._tasks[first_job[0]]['status'] = 'running'
                    self._tasks[first_job[0]]['started_at'] = time.time()
                    self._worker_alive = True
                    need_spawn = True
        if need_spawn:
            threading.Thread(
                target=self._worker_loop,
                args=(first_job,),
                name=f'ffmpeg-worker-{task_id}',
                daemon=True,
            ).start()
        return self.get(task_id)

    def _worker_loop(self, current_job):
        job = current_job
        try:
            while job is not None:
                task_id, cmd, out_path, est_duration, cleanup_paths = job
                try:
                    self._run_task(task_id, cmd, out_path, est_duration, cleanup_paths)
                except Exception as err:
                    with self._lock:
                        t = self._tasks.get(task_id)
                        if t and t.get('status') == 'running':
                            t['status'] = 'error'
                            t['error'] = str(err)
                        self._release_reserved_locked(out_path)
                job = None
                with self._lock:
                    while self._queue:
                        cand = self._queue.pop(0)
                        t = self._tasks.get(cand[0])
                        if t and not t.get('cancelled'):
                            t['status'] = 'running'
                            t['started_at'] = time.time()
                            job = cand
                            break
                    if job is None:
                        self._worker_alive = False
        finally:
            with self._lock:
                self._worker_alive = False

    def start(self, path_str, mode, options=None):
        ffmpeg, _ = ffmpeg_bins()
        if not ffmpeg:
            raise RuntimeError('未找到 ffmpeg，请确认已安装 FFmpeg')
        options = options or {}
        info = probe_video(path_str)
        src = Path(path_str)
        out_dir = Path(options.get('output_dir') or OUTPUT_DIR)

        cmd, out_path, mode_desc, est_duration = self._build_command(ffmpeg, src, info, mode, options, out_dir)
        task_id = uuid.uuid4().hex[:12]
        task = {
            'id': task_id,
            'status': 'queued',
            'progress': 0,
            'speed': '',
            'source_name': clean_stem(src) + src.suffix,
            'mode_desc': mode_desc,
            'output_path': str(out_path),
            'output_name': out_path.name,
            'input_size': info['size_bytes'],
            'output_size': 0,
            'error': '',
            'cancelled': False,
            'started_at': time.time(),
            'input_paths': [str(src.resolve())],
            '_proc': None,
        }
        return self._enqueue_or_start(task, cmd, out_path, est_duration)

    def _video_encoder_args(self, use_nvenc, quality, scale_height=0, extra_vf=None):
        vf = list(extra_vf or [])
        if scale_height and int(scale_height) > 0:
            # 保持宽高比且确保宽高均为偶数
            vf.append(f'scale=-2:min(ih\\,{int(scale_height)})')
        vf.append('format=yuv420p')
        vf_args = ['-vf', ','.join(vf)]
        enc_args, enc_name = self._raw_encoder_args(use_nvenc, quality)
        return vf_args + enc_args, enc_name

    def _raw_encoder_args(self, use_nvenc, quality):
        """仅返回视频编码器参数（不含 -vf），用于已由 filter_complex 处理滤镜链的场景。"""
        if use_nvenc and has_nvenc():
            cq_map = {'high': '21', 'balanced': '25', 'small': '30'}
            cq = cq_map.get(quality, '25')
            return ['-c:v', 'h264_nvenc', '-preset', 'p5', '-rc', 'vbr', '-cq', cq, '-b:v', '0'], 'NVENC 显卡硬编'
        crf_map = {'high': '19', 'balanced': '23', 'small': '28'}
        crf = crf_map.get(quality, '23')
        return ['-c:v', 'libx264', '-preset', 'medium', '-crf', crf], 'x264 CPU 编码'

    def start_merge(self, paths, options=None):
        """后台合并多个视频（支持无损秒合或兼容不同分辨率/编码的统一重编码合并，支持自动排队）。"""
        if not paths or len(paths) < 2:
            raise ValueError('请至少选择 2 个视频文件进行合并')
        ffmpeg, _ = ffmpeg_bins()
        if not ffmpeg:
            raise RuntimeError('未找到 ffmpeg，请确认已安装 FFmpeg')

        options = options or {}
        infos = [probe_video(p) for p in paths]
        if any(i['video_codec'] == '无' for i in infos):
            raise ValueError('所选文件中包含无视频画面的文件，无法合并')
        total_dur = sum(i['duration'] or 0.0 for i in infos)
        total_size = sum(i['size_bytes'] or 0 for i in infos)
        out_dir = Path(options.get('output_dir') or OUTPUT_DIR)
        out_path = self._reserve_output(out_dir, '合并视频', '.mp4')
        reencode = bool(options.get('reencode', False))
        use_nvenc = bool(options.get('use_nvenc', True))
        quality = options.get('quality', 'balanced')

        base = [ffmpeg, '-y', '-hide_banner', '-loglevel', 'error', '-progress', 'pipe:1', '-nostats']
        cleanup_paths = []

        if not reencode:
            ensure_dirs()
            list_file = UPLOAD_DIR / f'concat_{uuid.uuid4().hex[:8]}.txt'
            lines = []
            for p in paths:
                resolved = str(Path(p).resolve()).replace('\\', '/').replace("'", "'\\''")
                lines.append(f"file '{resolved}'")
            list_file.write_text('\n'.join(lines), encoding='utf-8')
            cleanup_paths.append(list_file)
            cmd = base + ['-f', 'concat', '-safe', '0', '-i', str(list_file),
                          '-c', 'copy', '-movflags', '+faststart', str(out_path)]
            mode_desc = f'无损快速合并 ({len(paths)} 段视频)'
        else:
            # 以首个有尺寸的视频为目标画布（保证宽高为偶数），并保留最高有效帧率（上限 60fps）
            first_w = next((i['width'] for i in infos if i['width'] > 0), 1280)
            first_h = next((i['height'] for i in infos if i['height'] > 0), 720)
            tw = first_w if first_w % 2 == 0 else first_w + 1
            th = first_h if first_h % 2 == 0 else first_h + 1
            valid_fps = [i['fps'] for i in infos if (i.get('fps') or 0) > 0]
            target_fps = min(60.0, max(valid_fps)) if valid_fps else 30.0
            fps_expr = str(int(round(target_fps))) if abs(target_fps - round(target_fps)) < 0.05 else f'{target_fps:.2f}'
            has_any_audio = any(i['audio_codec'] != '无音轨' for i in infos)

            in_args = []
            for p in paths:
                in_args += ['-i', str(Path(p).resolve())]

            fc_parts = []
            concat_inputs = []
            for idx, info in enumerate(infos):
                fc_parts.append(
                    f'[{idx}:v:0]scale={tw}:{th}:force_original_aspect_ratio=decrease,'
                    f'pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps_expr},format=yuv420p[v{idx}]'
                )
                concat_inputs.append(f'[v{idx}]')
                if has_any_audio:
                    if info['audio_codec'] != '无音轨':
                        fc_parts.append(
                            f'[{idx}:a:0]aformat=sample_rates=44100:channel_layouts=stereo,aresample=async=1[a{idx}]'
                        )
                    else:
                        dur = max(0.1, info['duration'] or 1.0)
                        fc_parts.append(
                            f'anullsrc=channel_layout=stereo:sample_rate=44100,atrim=0:{dur:.3f}[a{idx}]'
                        )
                    concat_inputs.append(f'[a{idx}]')

            if has_any_audio:
                fc_parts.append(f'{"".join(concat_inputs)}concat=n={len(paths)}:v=1:a=1[outv][outa]')
                map_args = ['-map', '[outv]', '-map', '[outa]', '-c:a', 'aac', '-b:a', '192k']
            else:
                fc_parts.append(f'{"".join(concat_inputs)}concat=n={len(paths)}:v=1:a=0[outv]')
                map_args = ['-map', '[outv]', '-an']

            enc_args, enc_name = self._raw_encoder_args(use_nvenc, quality)
            cmd = base + in_args + ['-filter_complex', ';'.join(fc_parts)] + map_args + enc_args + [
                '-movflags', '+faststart', str(out_path)
            ]
            mode_desc = f'统一重编码合并 {len(paths)} 段 ({enc_name})'

        task_id = uuid.uuid4().hex[:12]
        task = {
            'id': task_id,
            'status': 'queued',
            'progress': 0,
            'speed': '',
            'source_name': f'{len(paths)} 段视频合并',
            'mode_desc': mode_desc,
            'output_path': str(out_path),
            'output_name': out_path.name,
            'input_size': total_size,
            'output_size': 0,
            'error': '',
            'cancelled': False,
            'started_at': time.time(),
            'input_paths': [str(Path(p).resolve()) for p in paths],
            '_proc': None,
        }
        return self._enqueue_or_start(task, cmd, out_path, max(0.5, total_dur), cleanup_paths)

    def _build_command(self, ffmpeg, src, info, mode, options, out_dir):
        duration = info['duration'] or 0.0
        use_nvenc = bool(options.get('use_nvenc', True))
        quality = options.get('quality', 'balanced')
        stem = clean_stem(src)

        base = [ffmpeg, '-y', '-hide_banner', '-loglevel', 'error', '-progress', 'pipe:1', '-nostats']

        if mode == 'compat':
            out_path = self._reserve_output(out_dir, f'{stem}_兼容', '.mp4')
            force_reencode = bool(options.get('force_reencode', False))
            if info['can_remux_video'] and not force_reencode:
                a_args = ['-c:a', 'copy'] if info['can_remux_audio'] else ['-c:a', 'aac', '-b:a', '192k']
                cmd = base + ['-i', str(src), '-map', '0:v:0', '-map', '0:a?', '-c:v', 'copy'] + a_args + [
                    '-movflags', '+faststart', str(out_path)
                ]
                return cmd, out_path, '智能无损换壳 → 通用 MP4', duration
            v_args, enc_name = self._video_encoder_args(use_nvenc, quality)
            cmd = base + ['-i', str(src), '-map', '0:v:0', '-map', '0:a?'] + v_args + [
                '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', str(out_path)
            ]
            return cmd, out_path, f'{enc_name} → Win 通用 MP4', duration

        if mode == 'compress':
            scale_h = int(options.get('max_height') or 0)
            suffix = f'_压缩{scale_h}p' if scale_h else '_压缩'
            out_path = self._reserve_output(out_dir, f'{stem}{suffix}', '.mp4')
            v_args, enc_name = self._video_encoder_args(use_nvenc, quality or 'small', scale_h)
            cmd = base + ['-i', str(src), '-map', '0:v:0', '-map', '0:a?'] + v_args + [
                '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart', str(out_path)
            ]
            return cmd, out_path, f'{enc_name} 压缩体积', duration

        if mode == 'trim':
            start_s = _parse_time_str(options.get('start'))
            end_s = _parse_time_str(options.get('end'))
            start_sec = _time_to_seconds(start_s)
            end_sec = _time_to_seconds(end_s) if end_s else 0.0
            if duration > 0 and start_sec >= duration:
                raise ValueError('开始时间超出了视频总时长')
            if end_s and end_sec <= start_sec:
                raise ValueError('结束时间必须大于开始时间')
            lossless = bool(options.get('lossless', False))
            out_path = self._reserve_output(out_dir, f'{stem}_裁剪', '.mp4')
            pre = ['-ss', start_s] if start_s else []
            # -ss 置于 -i 之前时会重置时间轴为 0，因此用 -t 指定截取时长而非 -to
            if end_s:
                clip_dur = end_sec - start_sec
                post = ['-t', f'{clip_dur:.3f}']
                est = max(0.5, clip_dur)
            else:
                post = []
                est = max(0.5, duration - start_sec)
            if lossless and info['can_remux_video']:
                cmd = base + pre + ['-i', str(src)] + post + [
                    '-c', 'copy', '-movflags', '+faststart', str(out_path)
                ]
                return cmd, out_path, '无损快速裁剪', est
            v_args, enc_name = self._video_encoder_args(use_nvenc, 'high')
            cmd = base + pre + ['-i', str(src)] + post + v_args + [
                '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', str(out_path)
            ]
            return cmd, out_path, f'精确裁剪（{enc_name}）', est

        if mode == 'audio':
            if info['audio_codec'] == '无音轨':
                raise ValueError('该视频不包含音轨，无法提取音频')
            afmt = (options.get('audio_format') or 'mp3').lower()
            if afmt not in ('mp3', 'm4a', 'wav'):
                afmt = 'mp3'
            out_path = self._reserve_output(out_dir, f'{stem}_音频', f'.{afmt}')
            if afmt == 'mp3':
                a_args = ['-vn', '-c:a', 'libmp3lame', '-b:a', '192k']
            elif afmt == 'm4a':
                a_args = ['-vn', '-c:a', 'aac', '-b:a', '192k']
            else:
                a_args = ['-vn', '-c:a', 'pcm_s16le']
            cmd = base + ['-i', str(src)] + a_args + [str(out_path)]
            return cmd, out_path, f'提取音频 ({afmt.upper()})', duration

        if mode == 'gif':
            start_s = _parse_time_str(options.get('start'))
            end_s = _parse_time_str(options.get('end'))
            start_sec = _time_to_seconds(start_s)
            end_sec = _time_to_seconds(end_s) if end_s else 0.0
            if duration > 0 and start_sec >= duration:
                raise ValueError('开始时间超出了视频总时长')
            if end_s and end_sec <= start_sec:
                raise ValueError('结束时间必须大于开始时间')
            if end_s:
                clip_dur = end_sec - start_sec
                if clip_dur > MAX_GIF_SECONDS:
                    raise ValueError(f'GIF 单次截取时长上限为 {int(MAX_GIF_SECONDS)} 秒（过长会耗尽内存），请缩短起止时间')
            else:
                rem = (duration - start_sec) if duration > start_sec else DEFAULT_GIF_SECONDS
                clip_dur = max(0.2, min(rem, DEFAULT_GIF_SECONDS))
            fps = max(5, min(24, int(options.get('fps') or 12)))
            width = max(160, min(960, int(options.get('width') or 480)))
            out_path = self._reserve_output(out_dir, f'{stem}_动图', '.gif')
            pre = ['-ss', start_s] if start_s else []
            # 无论是否填写结束时间，均强制传入 -t 截断上限，防止长视频全量帧进入 palettegen 撑爆内存
            post = ['-t', f'{clip_dur:.3f}']
            est = max(0.5, clip_dur)
            vf = (
                f'fps={fps},scale={width}:-1:flags=lanczos,'
                'split[s0][s1];[s0]palettegen=stats_mode=diff[p];[s1][p]paletteuse=dither=bayer'
            )
            cmd = base + pre + ['-i', str(src)] + post + ['-vf', vf, '-loop', '0', str(out_path)]
            return cmd, out_path, f'生成高清 GIF ({width}px / {fps}fps / {clip_dur:.1f}s)', est

        if mode == 'rotate':
            rot_map = {
                'cw90': ('transpose=1', '顺时针90°'),
                'ccw90': ('transpose=2', '逆时针90°'),
                '180': ('transpose=1,transpose=1', '旋转180°'),
                'flip_h': ('hflip', '水平镜像'),
                'flip_v': ('vflip', '垂直翻转'),
            }
            op = options.get('rotate_op', 'cw90')
            if op not in rot_map:
                raise ValueError(f'不支持的视频旋转/翻转方式: {op}')
            rot_vf, label = rot_map[op]
            out_path = self._reserve_output(out_dir, f'{stem}_旋转', '.mp4')
            v_args, enc_name = self._video_encoder_args(use_nvenc, quality, extra_vf=[rot_vf])
            a_args = ['-c:a', 'copy'] if info['can_remux_audio'] else ['-c:a', 'aac', '-b:a', '192k']
            cmd = base + ['-i', str(src), '-map', '0:v:0', '-map', '0:a?'] + v_args + a_args + [
                '-movflags', '+faststart', str(out_path)
            ]
            return cmd, out_path, f'画面{label}（{enc_name}）', duration

        raise ValueError(f'不支持的视频处理模式: {mode}')

    def _run_task(self, task_id, cmd, out_path, est_duration, cleanup_paths=None):
        stderr_lines = []
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='replace',
                creationflags=_NO_WINDOW,
            )
            with self._lock:
                self._tasks[task_id]['_proc'] = proc

            def read_err():
                for line in proc.stderr:
                    stderr_lines.append(line.strip())

            err_thread = threading.Thread(target=read_err, daemon=True)
            err_thread.start()

            for line in proc.stdout:
                line = line.strip()
                if '=' not in line:
                    continue
                k, v = line.split('=', 1)
                if k == 'out_time_us' and est_duration > 0:
                    try:
                        pct = min(99, max(0, int(int(v) / (est_duration * 1_000_000) * 100)))
                        with self._lock:
                            self._tasks[task_id]['progress'] = pct
                    except ValueError:
                        pass
                elif k == 'speed':
                    with self._lock:
                        self._tasks[task_id]['speed'] = v.strip()

            proc.wait()
            err_thread.join(timeout=2)

            with self._lock:
                task = self._tasks[task_id]
                if task['cancelled']:
                    task['status'] = 'cancelled'
                    try:
                        out_path.unlink(missing_ok=True)
                    except OSError:
                        pass
                elif proc.returncode == 0 and out_path.exists():
                    task['status'] = 'done'
                    task['progress'] = 100
                    task['output_size'] = out_path.stat().st_size
                    task['elapsed'] = round(time.time() - task['started_at'], 1)
                else:
                    task['status'] = 'error'
                    task['error'] = ' | '.join(stderr_lines[-3:]) or f'FFmpeg 返回错误码 {proc.returncode}'
                    try:
                        out_path.unlink(missing_ok=True)
                    except OSError:
                        pass
        except Exception as err:
            with self._lock:
                self._tasks[task_id]['status'] = 'error'
                self._tasks[task_id]['error'] = str(err)
            try:
                Path(out_path).unlink(missing_ok=True)
            except OSError:
                pass
        finally:
            with self._lock:
                self._release_reserved_locked(out_path)
            for cp in (cleanup_paths or []):
                try:
                    Path(cp).unlink(missing_ok=True)
                except OSError:
                    pass


video_tasks = VideoTaskManager()


def export_video_frames(path_str, mode='interval', interval=2.0, count=10,
                        fmt='jpg', start='', end='', out_dir=None):
    """批量导出视频截图（按固定间隔秒数或均匀截取指定张数），单张直接输出，多张打包 ZIP。"""
    ffmpeg, _ = ffmpeg_bins()
    if not ffmpeg:
        raise RuntimeError('未找到 ffmpeg，请确认已安装 FFmpeg')
    info = probe_video(path_str)
    src = Path(path_str)
    out_dir = Path(out_dir or OUTPUT_DIR)
    stem = clean_stem(src)

    ext = '.png' if (fmt or 'jpg').lower() == 'png' else '.jpg'
    start_s = _parse_time_str(start)
    end_s = _parse_time_str(end)
    start_sec = _time_to_seconds(start_s)
    end_sec = _time_to_seconds(end_s) if end_s else 0.0
    if end_s and end_sec <= start_sec:
        raise ValueError('结束时间必须大于开始时间')
    duration = info['duration'] or 0.0
    span = (end_sec - start_sec) if end_s else max(0.5, duration - start_sec)

    max_frames = 200
    if mode == 'count':
        n = max(1, min(max_frames, int(count or 10)))
        fps_val = n / max(0.5, span)
        limit_args = ['-frames:v', str(n)]
    else:
        iv = max(0.2, float(interval or 2.0))
        # 当间隔大于视频片段时长时，至少保证截取 1 帧，避免 fps 滤镜输出 0 帧导致 mjpeg 编码器报错
        eff_iv = min(iv, span) if span > 0 else iv
        fps_val = 1.0 / max(0.2, eff_iv)
        limit_args = ['-frames:v', str(max_frames)]

    pre = ['-ss', start_s] if start_s else []
    post = ['-t', f'{(end_sec - start_sec):.3f}'] if end_s else []
    vf_chain = f'fps={fps_val:.6f},format=yuvj420p' if ext == '.jpg' else f'fps={fps_val:.6f}'
    q_args = ['-q:v', '2'] if ext == '.jpg' else []

    with tempfile.TemporaryDirectory(prefix='tb_frames_') as tmp:
        # 长视频按张数均匀截图时，改用输入前 -ss 关键帧秒级定位抽帧，避免全片软解超时
        if mode == 'count' and span > 90 and n <= 60:
            step = span / max(1, n)
            for idx in range(n):
                ts = start_sec + step * (idx + 0.5)
                if duration > 0:
                    ts = min(max(0.0, ts), max(0.0, duration - 0.05))
                out_f = str(Path(tmp) / f'frame_{idx + 1:04d}{ext}')
                vf_single = ['-vf', 'format=yuvj420p'] if ext == '.jpg' else []
                cmd = [ffmpeg, '-y', '-hide_banner', '-loglevel', 'error',
                       '-ss', f'{ts:.3f}', '-i', str(src), '-frames:v', '1'] + vf_single + q_args + [out_f]
                try:
                    run = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8',
                                         errors='replace', timeout=30, creationflags=_NO_WINDOW)
                except subprocess.TimeoutExpired:
                    raise RuntimeError('视频截图单帧定位超时，请尝试缩短时间范围或减少截图张数')
                if run.returncode != 0:
                    raise RuntimeError(run.stderr.strip() or '视频截图导出失败')
        else:
            pattern = str(Path(tmp) / f'frame_%04d{ext}')
            cmd = [ffmpeg, '-y', '-hide_banner', '-loglevel', 'error'] + pre + [
                '-i', str(src),
            ] + post + ['-vf', vf_chain] + q_args + limit_args + [pattern]
            timeout_sec = max(120, min(600, int(span * 0.4) + 120))
            try:
                run = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8',
                                     errors='replace', timeout=timeout_sec, creationflags=_NO_WINDOW)
            except subprocess.TimeoutExpired:
                raise RuntimeError('视频截图处理超时（视频较长或分辨率较高），建议缩小起止时间范围后重试')
            if run.returncode != 0:
                raise RuntimeError(run.stderr.strip() or '视频截图导出失败')
        frames = sorted(Path(tmp).glob(f'frame_*{ext}'))
        if not frames:
            raise RuntimeError('未截取到任何画面帧，请检查时间范围或视频时长')

        if len(frames) == 1:
            out_path = unique_path(out_dir, f'{stem}_截图', ext)
            shutil.copy2(frames[0], out_path)
            return {
                'count': 1,
                'name': out_path.name,
                'path': str(out_path),
                'preview_path': str(out_path),
                'output_size': out_path.stat().st_size,
                'output_dir': str(out_dir),
            }

        zip_path = unique_path(out_dir, f'{stem}_截图_{len(frames)}张', '.zip')
        with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
            for idx, fp in enumerate(frames, 1):
                zf.write(fp, arcname=f'{stem}_截图_{idx:03d}{ext}')
        return {
            'count': len(frames),
            'name': zip_path.name,
            'path': str(zip_path),
            'preview_path': '',
            'output_size': zip_path.stat().st_size,
            'output_dir': str(out_dir),
        }


# ==================== 字幕格式互转（SRT / VTT / ASS） ====================

def _decode_text_bytes(raw_bytes):
    """按 BOM 优先与常见中文/国际编码智能评分顺序解码文本字节（避免 Big5 繁体被误判为 GB18030）。"""
    if raw_bytes.startswith(b'\xef\xbb\xbf'):
        try:
            return raw_bytes.decode('utf-8-sig'), 'utf-8-sig'
        except UnicodeDecodeError:
            pass
    if raw_bytes.startswith((b'\xff\xfe', b'\xfe\xff')):
        try:
            return raw_bytes.decode('utf-16'), 'utf-16'
        except UnicodeDecodeError:
            pass
    from tools_files import _detect_legacy_encoding
    det_enc, det_txt = _detect_legacy_encoding(raw_bytes)
    if det_enc and det_txt is not None:
        return det_txt, det_enc
    for enc in ('utf-16', 'utf-8'):
        try:
            return raw_bytes.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw_bytes.decode('utf-8', errors='replace'), 'utf-8(replace)'


def _ts_to_ms(ts_str):
    """解析 SRT/VTT/ASS 时间戳为毫秒整数。"""
    s = ts_str.strip().replace(',', '.')
    parts = s.split(':')
    if len(parts) == 2:
        h, m, sec = 0, int(parts[0]), float(parts[1])
    elif len(parts) == 3:
        h, m, sec = int(parts[0]), int(parts[1]), float(parts[2])
    else:
        raise ValueError(f'无法识别的时间戳: {ts_str}')
    return max(0, int(round((h * 3600 + m * 60 + sec) * 1000)))


def _ms_to_srt(ms):
    h, rem = divmod(max(0, int(ms)), 3600_000)
    m, rem = divmod(rem, 60_000)
    s, frac = divmod(rem, 1000)
    return f'{h:02d}:{m:02d}:{s:02d},{frac:03d}'


def _ms_to_vtt(ms):
    return _ms_to_srt(ms).replace(',', '.')


def _ms_to_ass(ms):
    h, rem = divmod(max(0, int(ms)), 3600_000)
    m, rem = divmod(rem, 60_000)
    s, frac = divmod(rem, 1000)
    cs = frac // 10
    return f'{h}:{m:02d}:{s:02d}.{cs:02d}'


def _parse_srt_or_vtt(text):
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    cues = []
    # 兼容空行中包含空格或制表符的 SRT/VTT 文件
    blocks = re.split(r'\n[ \t]*\n+', text.strip())
    time_re = re.compile(
        r'(\d{1,2}:\d{2}(?::\d{2})?[.,]\d{1,3})\s*-->\s*(\d{1,2}:\d{2}(?::\d{2})?[.,]\d{1,3})'
    )
    for blk in blocks:
        lines = [ln for ln in blk.split('\n') if ln.strip() != '']
        if not lines:
            continue
        if lines[0].upper().startswith(('WEBVTT', 'NOTE', 'STYLE', 'REGION')):
            continue
        m_idx = -1
        m_obj = None
        for i, ln in enumerate(lines):
            m = time_re.search(ln)
            if m:
                m_idx = i
                m_obj = m
                break
        if m_obj is None:
            continue
        start_ms = _ts_to_ms(m_obj.group(1))
        end_ms = _ts_to_ms(m_obj.group(2))
        body = '\n'.join(lines[m_idx + 1:]).strip()
        # 去除 VTT/SRT 中简单的 HTML 标签（保留纯文本）
        body = re.sub(r'</?(?:i|b|u|c(?:\.[^>]*)?|v[^>]*)>', '', body)
        if body:
            cues.append((start_ms, end_ms, body))
    return cues


def _parse_ass(text):
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    cues = []
    for ln in text.split('\n'):
        stripped = ln.lstrip()
        if not stripped.startswith('Dialogue:'):
            continue
        body_part = stripped.split(':', 1)[1].strip()
        # ASS Dialogue 固定前 9 个逗号字段，第 10 个字段起为正文（正文可能含逗号）
        fields = body_part.split(',', 9)
        if len(fields) < 10:
            continue
        try:
            start_ms = _ts_to_ms(fields[1])
            end_ms = _ts_to_ms(fields[2])
        except ValueError:
            continue
        raw_txt = fields[9]
        # 去掉 {\...} 覆盖标签，将 \N / \n 还原为换行
        clean = re.sub(r'\{[^}]*\}', '', raw_txt)
        clean = clean.replace('\\N', '\n').replace('\\n', '\n').strip()
        if clean:
            cues.append((start_ms, end_ms, clean))
    return cues


def convert_subtitle(path_str, target_fmt='srt', out_dir=None):
    """纯离线字幕格式互转（支持 .srt / .vtt / .ass / .ssa 互转，统一输出标准 UTF-8）。"""
    src = Path(path_str)
    if not src.exists():
        raise FileNotFoundError('字幕文件不存在')
    target_fmt = (target_fmt or 'srt').lower().lstrip('.')
    if target_fmt not in ('srt', 'vtt', 'ass'):
        raise ValueError(f'不支持的目标字幕格式: {target_fmt}')

    raw_text, detected_enc = _decode_text_bytes(src.read_bytes())
    src_ext = src.suffix.lower()
    if src_ext in ('.ass', '.ssa') or '[Events]' in raw_text:
        cues = _parse_ass(raw_text)
    else:
        cues = _parse_srt_or_vtt(raw_text)

    if not cues:
        raise ValueError('未能从文件中解析出有效字幕条目，请确认文件为标准 SRT / VTT / ASS 格式')

    if target_fmt == 'srt':
        out_text = '\n\n'.join(
            f'{idx}\n{_ms_to_srt(s)} --> {_ms_to_srt(e)}\n{txt}'
            for idx, (s, e, txt) in enumerate(cues, 1)
        ) + '\n'
    elif target_fmt == 'vtt':
        body = '\n\n'.join(
            f'{_ms_to_vtt(s)} --> {_ms_to_vtt(e)}\n{txt}'
            for s, e, txt in cues
        )
        out_text = f'WEBVTT\n\n{body}\n'
    else:
        header = (
            '[Script Info]\n'
            'ScriptType: v4.00+\n'
            'PlayResX: 1920\n'
            'PlayResY: 1080\n'
            'ScaledBorderAndShadow: yes\n\n'
            '[V4+ Styles]\n'
            'Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, '
            'Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, '
            'Alignment, MarginL, MarginR, MarginV, Encoding\n'
            'Style: Default,Microsoft YaHei,54,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,'
            '0,0,0,0,100,100,0,0,1,2,1,2,20,20,30,1\n\n'
            '[Events]\n'
            'Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'
        )
        lines = [
            f'Dialogue: 0,{_ms_to_ass(s)},{_ms_to_ass(e)},Default,,0,0,0,,{txt.replace(chr(10), r"\N")}'
            for s, e, txt in cues
        ]
        out_text = header + '\n'.join(lines) + '\n'

    out_dir = Path(out_dir or OUTPUT_DIR)
    out_path = unique_path(out_dir, f'{clean_stem(src)}_转换', f'.{target_fmt}')
    out_path.write_text(out_text, encoding='utf-8')
    return {
        'name': out_path.name,
        'path': str(out_path),
        'cues': len(cues),
        'detected_encoding': detected_enc,
        'output_size': out_path.stat().st_size,
        'output_dir': str(out_dir),
    }
