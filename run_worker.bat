@echo off
cd /d %~dp0
venv\Scripts\activate
python -m jobs.job_worker
