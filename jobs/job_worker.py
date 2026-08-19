from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

import cv2

from .job_manager import JobManager
from .job_model import JobStatus


# Папка, куда будут складываться "результаты".
# Пока просто кладём туда тот же файл или фейковый путь.
RESULTS_DIR = Path("videos_processed")
RESULTS_DIR.mkdir(exist_ok=True)
EXTRACTED_FRAMES_DIR = Path("data/extracted_frames")
EXTRACTED_FRAMES_DIR.mkdir(parents=True, exist_ok=True)
VIDEO_EXTENSIONS = {".avi", ".mkv", ".mov", ".mp4", ".webm"}


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


def mock_surf_analysis() -> dict[str, str]:
    return {
        "level": "Intermediate",
        "main_issue": "Your stance becomes too upright during turns.",
        "why_it_matters": "A lower, balanced stance helps you keep control and generate speed.",
        "how_to_fix": "Keep your knees bent and your weight centered over the board through each turn.",
        "drill": "Practice low, controlled bottom turns while focusing on bending at the knees.",
        "coach_note": "You have good wave awareness—focus on staying compact as you transition.",
    }


def extract_representative_frames(input_path: Path, job_id: str) -> list[str]:
    video = cv2.VideoCapture(str(input_path))
    if not video.isOpened():
        raise RuntimeError("Frame extraction failed: unable to open the uploaded video.")

    try:
        frame_count = int(video.get(cv2.CAP_PROP_FRAME_COUNT))
        if frame_count < 1:
            raise RuntimeError("Frame extraction failed: the video contains no readable frames.")

        job_frames_dir = EXTRACTED_FRAMES_DIR / job_id
        job_frames_dir.mkdir(parents=True, exist_ok=True)
        frame_paths = []

        for frame_number in range(5):
            frame_index = round(frame_number * (frame_count - 1) / 4)
            video.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            success, frame = video.read()
            if not success or frame is None:
                raise RuntimeError(
                    f"Frame extraction failed: unable to read frame {frame_number + 1} of 5."
                )

            frame_filename = f"frame_{frame_number + 1:02d}.jpg"
            frame_path = job_frames_dir / frame_filename
            if not cv2.imwrite(str(frame_path), frame):
                raise RuntimeError(
                    f"Frame extraction failed: unable to save frame {frame_number + 1} of 5."
                )

            frame_paths.append(f"/frames/{job_id}/{frame_filename}")

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
                    result_path = fake_video_analysis(input_path)
                    jm.update_job(
                        job.id,
                        status=JobStatus.DONE,
                        result_path=str(result_path),
                        analysis_result=mock_surf_analysis(),
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
