"""Isolated browser acceptance: no production accounts, videos, or API calls."""
import json
import os
import socket
import subprocess
import threading
import time

import pytest
import uvicorn

from tests.test_admin_invites import admin
from webapp import main


@pytest.mark.skipif(not os.environ.get('SURFANALYZE_PLAYWRIGHT_MODULE'), reason='Set SURFANALYZE_PLAYWRIGHT_MODULE for browser tests')
def test_mobile_invite_flow(admin, app_state, tmp_path):
    expired_token = 'local-browser-expired-invitation-1234567'
    identity = app_state[0].create_invite(expired_token, label='Expired fixture')
    with app_state[0].database.connect(write=True) as db:
        db.execute('UPDATE invites SET expires_at=0 WHERE id=?', (identity,))
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
                      'cookie': admin.cookies.get('surfanalyze_account'), 'output': str(tmp_path), 'expiredToken': expired_token}
            result = subprocess.run(['node', 'tests/invite_mobile.cjs'], input=json.dumps(config),
                                    capture_output=True, text=True, timeout=180)
            assert result.returncode == 0, result.stdout + result.stderr
            print(result.stdout)
        finally:
            server.should_exit = True
            thread.join(timeout=10)
