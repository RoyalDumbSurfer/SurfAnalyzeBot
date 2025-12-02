@echo off
set PYTHONPATH=.
pytest --cov=utils --cov=config --cov=handlers %*
