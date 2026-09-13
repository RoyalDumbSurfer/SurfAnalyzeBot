"""Optional real-browser regression; see tests/coach_mobile_ux.cjs for setup."""
import json
import os
import socket
import subprocess
import threading
import time

import cv2
import numpy as np
import pytest
import uvicorn

from tests.test_coach_review import completed, reviewer, endpoint, payload
from webapp import main


@pytest.mark.skipif(not os.environ.get('SURFANALYZE_PLAYWRIGHT_MODULE'), reason='Set SURFANALYZE_PLAYWRIGHT_MODULE for mobile browser tests')
def test_mobile_saved_summary_and_viewport_modal(reviewer, completed, tmp_path):
    frames = main.EXTRACTED_FRAMES_DIR / completed.id
    frames.mkdir(parents=True)
    for i in range(1, 16):
        image = np.full((360, 640, 3), (65, 40, 20), dtype=np.uint8)
        cv2.putText(image, f'TEST FRAME {i}', (50, 180), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
        cv2.imwrite(str(frames / f'frame_{i:02}.jpg'), image)
    data = payload(general_comment='Saved comment without field corrections', frame_notes=[{'frame_index':8,'note':'Frame eight'}, {'frame_index':12,'note':'Frame twelve'}])
    assert reviewer.post(endpoint(completed), json=data).status_code == 200
    async def local_http_app(scope, receive, send):
        async def local_send(message):
            if message['type'] == 'http.response.start':
                # Only this loopback HTTP fixture relaxes the transport flag;
                # WebKit otherwise drops renewed Secure cookies over HTTP.
                # Production SessionMiddleware and auth checks are unchanged.
                message['headers'] = [(key, value.replace(b'; secure', b'') if key == b'set-cookie' else value)
                                      for key, value in message['headers']]
            await send(message)
        await main.app(scope, receive, local_send)
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(local_http_app, log_level='error'))
        thread = threading.Thread(target=server.run, kwargs={'sockets':[listener]}, daemon=True)
        thread.start()
        try:
            for _ in range(100):
                if server.started:
                    break
                time.sleep(.05)
            assert server.started
            config = {'baseUrl':f'http://127.0.0.1:{port}', 'jobId':completed.id,
                      'cookie':reviewer.cookies.get('surfanalyze_account'), 'output':str(tmp_path)}
            result = subprocess.run(['node', 'tests/coach_mobile_ux.cjs'], input=json.dumps(config),
                                    capture_output=True, text=True, timeout=180)
            assert result.returncode == 0, result.stdout + result.stderr
        finally:
            server.should_exit = True
            thread.join(timeout=10)
