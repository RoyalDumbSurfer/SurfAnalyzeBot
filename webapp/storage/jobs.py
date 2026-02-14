JOBS = {}


def create_job(job_data: dict):
    JOBS[job_data["job_id"]] = job_data


def get_job(job_id: str):
    return JOBS.get(job_id)


def get_jobs_by_user(user_id: str):
    return [
        job for job in JOBS.values()
        if job["user_id"] == user_id
    ]
