from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from .job_manager import JobManager
from .job_model import JobStatus


# Папка, куда будут складываться "результаты".
# Пока просто кладём туда тот же файл или фейковый путь.
RESULTS_DIR = Path("videos_processed")
RESULTS_DIR.mkdir(exist_ok=True)


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
                    result_path = fake_video_analysis(input_path)
                    jm.update_job(job.id, status=JobStatus.DONE, result_path=str(result_path))
                    print(f"[Worker] Задача {job.id} завершена. Результат: {result_path}")
                except Exception as e:
                    jm.update_job(job.id, status=JobStatus.FAILED, error_message=str(e))
                    print(f"[Worker] Ошибка в задаче {job.id}: {e}")

            time.sleep(poll_interval)
    except KeyboardInterrupt:
        print("[Worker] Остановлен пользователем.")
        
if __name__ == "__main__":
    process_jobs()
