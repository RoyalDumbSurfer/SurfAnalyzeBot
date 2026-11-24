"""Bounded FFmpeg export of a saved coach timeline; never modifies source media."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import textwrap
import threading
import time

import cv2

from services.video_director import validate_plan, VideoDirectorError

MAX_DURATION = 180
RENDER_TIMEOUT = 300
PAUSE_SECONDS = 3
SLOW_SECONDS = 1
_slot = threading.BoundedSemaphore(1)


class RenderError(RuntimeError):
    pass


class RenderBusy(RenderError):
    pass


def render_key(review: dict) -> str:
    return hashlib.sha256(json.dumps({'engine': 1, 'review': review},
                                    sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:24]


def _run(args, cwd, deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise RenderError('Rendering timed out')
    try:
        return subprocess.run(args, cwd=cwd, capture_output=True, check=True,
                              timeout=remaining).stdout
    except (OSError, subprocess.SubprocessError) as error:
        # Do not return process stderr, paths, or coach comments to clients/logs.
        raise RenderError('Video processing failed') from error


def _font() -> Path:
    for candidate in (os.environ.get('VIDEO_RENDER_FONT', ''),
                      'C:/Windows/Fonts/consola.ttf',
                      '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf'):
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    raise RenderError('A Unicode rendering font is required')


def render_video(source: Path, frame_paths: list[Path], review: dict, destination: Path) -> Path:
    """Render a silent H.264 MP4, with arrows on sampled stills only.

    One active render per web process; temporary files disappear on failure.
    Cache identity is the immutable saved review, including its revision.
    """
    try:
        plan = review['plan']
        count = plan['frame_count']
        if type(count) is not int or not 2 <= count <= 20 or len(frame_paths) != count:
            raise RenderError('Coaching frames are unavailable')
        plan = validate_plan({'cues': plan['cues']}, count)
    except (KeyError, TypeError, VideoDirectorError) as error:
        raise RenderError('Invalid saved timeline') from error
    if not _slot.acquire(blocking=False):
        raise RenderBusy('Another export is running; retry shortly')
    try:
        if destination.is_file():
            return destination
        destination.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + RENDER_TIMEOUT
        with tempfile.TemporaryDirectory(prefix='render-', dir=destination.parent) as folder:
            work = Path(folder)
            raw = _run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-count_frames',
                        '-show_entries', 'stream=duration,nb_read_frames:format=duration',
                        '-of', 'json', str(source.resolve())], work, deadline)
            try:
                info = json.loads(raw)
                stream = info['streams'][0]
                duration = float(stream.get('duration') or info['format']['duration'])
                total_frames = int(stream['nb_read_frames'])
                if not math.isfinite(duration) or not 0 < duration <= MAX_DURATION or total_frames < count:
                    raise ValueError
                # Existing extraction samples min(15, frame count). Missing JPEGs
                # cannot safely be assigned evenly spaced source positions.
                if count != min(15, total_frames):
                    raise ValueError
            except (ValueError, KeyError, IndexError, TypeError) as error:
                raise RenderError('Export needs a video up to 180 seconds and a complete frame sample') from error
            shutil.copyfile(_font(), work / 'font.ttf')
            segments = []
            base_filter = ('scale=960:720:force_original_aspect_ratio=decrease:force_divisible_by=2,'
                           'pad=960:720:(ow-iw)/2:(oh-ih)/2,setsar=1,pad=960:920:0:0:black')

            def encode(inputs, filters, seconds):
                name = f'part-{len(segments):02}.mp4'
                _run(['ffmpeg', '-nostdin', '-v', 'error', '-y', *inputs,
                      '-map', '0:v:0', '-an', '-vf', filters, '-t', f'{seconds:.6f}',
                      '-r', '30', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23',
                      '-pix_fmt', 'yuv420p', '-threads', '2', name], work, deadline)
                segments.append(name)

            def motion(start, end, speed=1):
                if end - start < 0.001:
                    return
                encode(['-ss', f'{start:.6f}', '-i', str(source.resolve())],
                       f'setpts=(PTS-STARTPTS)/{speed},' + base_filter, (end-start)/speed)

            cursor = 0.0
            for index, cue in enumerate(plan['cues']):
                frame_index = (cue['frame_number'] - 1) * (total_frames - 1) // (count - 1)
                anchor = duration * frame_index / total_frames
                slow_start = max(cursor, anchor - SLOW_SECONDS)
                motion(cursor, slow_start)
                motion(slow_start, anchor, .5)
                still = cv2.imread(str(frame_paths[cue['frame_number'] - 1]))
                if still is None:
                    raise RenderError('Coaching frame is unreadable')
                arrow = cue['arrow']
                if arrow:
                    height, width = still.shape[:2]
                    start = (round(arrow['x1']*(width-1)/1000), round(arrow['y1']*(height-1)/1000))
                    end = (round(arrow['x2']*(width-1)/1000), round(arrow['y2']*(height-1)/1000))
                    cv2.arrowedLine(still, start, end, (255, 229, 0),
                                    max(2, round(width/160)), cv2.LINE_AA, tipLength=.16)
                image_name = f'cue-{index}.png'
                if not cv2.imwrite(str(work / image_name), still):
                    raise RenderError('Could not write coaching frame')
                text_name = f'cue-{index}.txt'
                # User text is data, never filter syntax, shell code or expansion.
                lines = textwrap.wrap(' '.join(cue['title'].split()), width=62)
                lines += textwrap.wrap(' '.join(cue['note'].split()), width=62)
                # LF is required: Windows CRLF produces extra drawtext spacing.
                (work / text_name).write_bytes('\n'.join(lines).encode('utf-8'))
                encode(['-loop', '1', '-i', image_name], base_filter +
                       f',drawtext=fontfile=font.ttf:textfile={text_name}:expansion=none:'
                       'fontcolor=white:fontsize=24:line_spacing=4:x=24:y=740', PAUSE_SECONDS)
                cursor = anchor
            motion(cursor, duration)
            (work / 'parts.txt').write_text(''.join(f"file '{name}'\n" for name in segments), encoding='ascii')
            _run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-f', 'concat', '-safe', '1',
                  '-i', 'parts.txt', '-c', 'copy', '-movflags', '+faststart', 'output.mp4'], work, deadline)
            os.replace(work / 'output.mp4', destination)
        return destination
    finally:
        _slot.release()
