"""Isolated browser acceptance: no production accounts, videos, or API calls."""
import json
import os
import socket
import subprocess
import threading
import time

import pytest
import uvicorn

from tests.test_private_demo import video_bytes
from webapp import main


@pytest.mark.skipif(not os.environ.get('SURFANALYZE_PLAYWRIGHT_MODULE'), reason='Set SURFANALYZE_PLAYWRIGHT_MODULE for browser tests')
def test_desktop_mobile_upload(client, video_bytes, tmp_path):
    for name, size in [('normal.avi', len(video_bytes)), ('boundary.avi', 100 * 1024 * 1024), ('oversized.avi', 100 * 1024 * 1024 + 1)]:
        with (tmp_path / name).open('wb') as video:
            video.write(video_bytes)
            video.truncate(size)
    async def local_app(scope, receive, send):
        async def local_send(message):
            if message['type'] == 'http.response.start':
                # HTTP loopback fixture only; production cookies remain Secure.
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
            config = {'baseUrl': f'http://127.0.0.1:{listener.getsockname()[1]}',
                      'cookie': client.cookies.get('surfanalyze_account'), 'output': str(tmp_path)}
            result = subprocess.run(['node', 'tests/upload_browser.cjs'], input=json.dumps(config),
                                    capture_output=True, text=True, encoding='utf-8', timeout=300)
            assert result.returncode == 0, result.stdout + result.stderr
            print(result.stdout)
        finally:
            server.should_exit = True
            thread.join(timeout=10)
