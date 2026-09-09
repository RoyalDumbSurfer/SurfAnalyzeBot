from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

import cv2

from services.surf_analysis_service import analyze_surf_frames
from utils.video_formats import VIDEO_EXTENSIONS

from .job_manager import JobManager
from .job_model import JobStatus


# Папка, куда будут складываться "результаты".
# Пока просто кладём туда тот же файл или фейковый путь.
RESULTS_DIR = Path("videos_processed")
RESULTS_DIR.mkdir(exist_ok=True)
EXTRACTED_FRAMES_DIR = Path("data/extracted_frames")
EXTRACTED_FRAMES_DIR.mkdir(parents=True, exist_ok=True)
DEFAULT_FRAME_SAMPLE_TARGET = 15


def fake_video_analysis(input_path: Path) -> Path:
    """
    Временная заглушка для анализа видео.
    Здесь позже появится интеграция с Cocoon.
    Сейчас просто возвращаем путь в папке videos_processed
    с тем же именем файла.
    """
    output_path = RESULTS_DIR / input_path.name
    # Для MVP можно просто скопировать файл (но чтобы не тащить shutil,
    # можно оставить заглушку – будто мы что-то сделали).
    try:
        if input_path.exists() and input_path.is_file():
            # ленивый импорт, чтобы не тащить shutil в другие модули
            import shutil
            shutil.copy2(input_path, output_path)
    except Exception as e:
        print(f"[Worker] Ошибка при копировании файла: {e}")
    return output_path


def representative_frame_indices(frame_count: int, target_count: int = DEFAULT_FRAME_SAMPLE_TARGET) -> list[int]:
    """Return evenly distributed, chronological frame indices for a video."""
    sample_count = min(frame_count, target_count)
    if sample_count < 1:
        return []
    if sample_count == 1:
        return [0]

    return [index * (frame_count - 1) // (sample_count - 1) for index in range(sample_count)]


def extract_representative_frames(
    input_path: Path,
    job_id: str,
    target_count: int = DEFAULT_FRAME_SAMPLE_TARGET,
) -> list[str]:
    video = cv2.VideoCapture(str(input_path))
    if not video.isOpened():
        raise RuntimeError("Frame extraction failed: unable to open the uploaded video.")

    try:
        frame_count = max(0, int(video.get(cv2.CAP_PROP_FRAME_COUNT)))

        job_frames_dir = EXTRACTED_FRAMES_DIR / job_id
        job_frames_dir.mkdir(parents=True, exist_ok=True)
        frame_paths = []

        frame_indices = representative_frame_indices(frame_count, target_count) or [0]
        for frame_index in frame_indices:
            video.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            success, frame = video.read()
            if not success or frame is None:
                continue

            frame_filename = f"frame_{len(frame_paths) + 1:02d}.jpg"
            frame_path = job_frames_dir / frame_filename
            if not cv2.imwrite(str(frame_path), frame):
                continue

            frame_paths.append(f"/frames/{job_id}/{frame_filename}")

        if not frame_paths:
            raise RuntimeError("Frame extraction failed: no usable frames could be extracted.")

        return frame_paths
    finally:
        video.release()


def process_jobs(poll_interval: float = 2.0) -> None:
    """
    Простейший бесконечный цикл обработки задач.
    Запускается отдельным процессом / консольной командой.
    """
    jm = JobManager()
    print("[Worker] Job worker started. Press CTRL+C to stop.")

    try:
        while True:
            queued_jobs = jm.list_jobs(status=JobStatus.QUEUED)
            if queued_jobs:
                print(f"[Worker] Найдено задач в очереди: {len(queued_jobs)}")

            for job in queued_jobs:
                print(f"[Worker] Обрабатываю задачу {job.id} для user_id={job.user_id}")
                jm.update_job(job.id, status=JobStatus.PROCESSING)

                try:
                    input_path = Path(job.file_path)
                    extracted_frame_paths = None
                    if input_path.suffix.lower() in VIDEO_EXTENSIONS:
                        extracted_frame_paths = extract_representative_frames(input_path, job.id)
                    frame_file_paths = [
                        EXTRACTED_FRAMES_DIR / job.id / Path(frame_path).name
                        for frame_path in extracted_frame_paths or []
                    ]
                    analysis_result = analyze_surf_frames(
                        frame_file_paths,
                        original_filename=job.original_filename,
                        job_id=job.id,
                        **({"language": job.analysis_language} if job.analysis_language else {}),
                    )
                    result_path = fake_video_analysis(input_path)
                    jm.update_job(
                        job.id,
                        status=JobStatus.DONE,
                        result_path=str(result_path),
                        analysis_result=analysis_result,
                        extracted_frame_paths=extracted_frame_paths,
                    )
                    print(f"[Worker] Задача {job.id} завершена. Результат: {result_path}")
                except Exception as e:
                    jm.update_job(job.id, status=JobStatus.FAILED, error_message=str(e))
                    print(f"[Worker] Ошибка в задаче {job.id}: {e}")

            time.sleep(poll_interval)
    except KeyboardInterrupt:
        print("[Worker] Остановлен пользователем.")
        
if __name__ == "__main__":
    process_jobs()
