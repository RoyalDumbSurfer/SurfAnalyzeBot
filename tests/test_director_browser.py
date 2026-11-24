"""Real browser coverage using a local server and synthetic video only."""
import json
import os
import socket
import subprocess
import threading
import time

import pytest
import uvicorn

from tests.test_video_renderer import render_job
from webapp import main


@pytest.mark.skipif(not os.environ.get('SURFANALYZE_PLAYWRIGHT_MODULE'), reason='Playwright not configured')
def test_director_browser(client, app_state, render_job, tmp_path):
    job, review = render_job
    plan = dict(review['plan'], cues=review['plan']['cues'][:1])
    main.job_manager.save_director_review(job.id, 1, 1, plan)
    async def local_app(scope, receive, send):
        async def local_send(message):
            if message['type'] == 'http.response.start':
                message['headers'] = [(k, v.replace(b'; secure', b'') if k == b'set-cookie' else v)
                                      for k, v in message['headers']]
            await send(message)
        await main.app(scope, receive, local_send)
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        server = uvicorn.Server(uvicorn.Config(local_app, log_level='error'))
        thread = threading.Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
        thread.start()
        try:
            for _ in range(100):
                if server.started:
                    break
                time.sleep(.05)
            assert server.started
            main.app.state.results_dir = app_state[1]
            config = {'baseUrl': f'http://127.0.0.1:{listener.getsockname()[1]}',
                      'jobId': job.id, 'cookie': client.cookies.get('surfanalyze_account'),
                      'output': str(tmp_path)}
            result = subprocess.run(['node', 'tests/director_browser.cjs'], input=json.dumps(config),
                                    capture_output=True, text=True, timeout=180)
            assert result.returncode == 0, result.stdout + result.stderr
        finally:
            server.should_exit = True
            thread.join(timeout=10)
