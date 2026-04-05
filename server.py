"""
NADIR DOWNLOADER - Flask Server for Replit
Wraps the Vercel-style API handlers into a unified Flask application
that serves both the static frontend and the Python API endpoints.
"""

import os
import sys
import json
import tempfile
from io import BytesIO
from urllib.parse import urlparse, parse_qs, urlencode
from flask import Flask, request, Response, send_from_directory

# ---------------------------------------------------------------------------
# Flask app setup
# ---------------------------------------------------------------------------
app = Flask(__name__, static_folder='.', static_url_path='')


# ---------------------------------------------------------------------------
# Helper: adapt Vercel-style BaseHTTPRequestHandler to Flask
# ---------------------------------------------------------------------------
class _FakeSocket:
    """Minimal socket-like object to capture handler writes."""
    def __init__(self):
        self._buf = BytesIO()

    def makefile(self, mode='rb'):
        return self._buf

    def sendall(self, data):
        self._buf.write(data)


class _FakeRequest:
    """Minimal request-like object for BaseHTTPRequestHandler."""
    def __init__(self, method, path):
        self.method = method
        self.path = path
        self._sock = _FakeSocket()

    def makefile(self, mode='rb'):
        return BytesIO(b'')


def _run_handler(handler_class, method, path_with_query):
    """
    Instantiate a Vercel-style BaseHTTPRequestHandler, call the appropriate
    do_GET / do_OPTIONS method, and return a Flask Response.
    """
    response_buf = BytesIO()
    headers_sent = []
    status_code = [200]
    headers_done = [False]

    class _StreamingHandler(handler_class):
        def setup(self):
            self.connection = type('conn', (), {
                'makefile': lambda s, *a, **kw: BytesIO(b''),
                'sendall': lambda s, d: None,
            })()
            self.rfile = BytesIO(b'')
            self.wfile = response_buf
            self.server = type('srv', (), {'server_name': 'localhost', 'server_port': 5000})()

        def send_response(self, code, message=None):
            status_code[0] = code

        def send_header(self, keyword, value):
            headers_sent.append((keyword, value))

        def end_headers(self):
            headers_done[0] = True

        def log_message(self, fmt, *args):
            pass

    handler = _StreamingHandler.__new__(_StreamingHandler)
    handler.path = path_with_query
    handler.command = method
    handler.setup()

    try:
        if method == 'GET':
            handler.do_GET()
        elif method == 'OPTIONS':
            handler.do_OPTIONS()
        else:
            handler.send_response(405)
            handler.end_headers()
    except Exception as e:
        response_buf.seek(0)
        response_buf.truncate()
        response_buf.write(json.dumps({'error': str(e)}).encode())
        status_code[0] = 500
        headers_sent.clear()
        headers_sent.append(('Content-Type', 'application/json'))
        headers_sent.append(('Access-Control-Allow-Origin', '*'))

    body = response_buf.getvalue()
    resp = Response(body, status=status_code[0])
    for k, v in headers_sent:
        resp.headers[k] = v
    return resp


# ---------------------------------------------------------------------------
# Import API handlers
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'api'))

from download import handler as DownloadHandler
from proxy import handler as ProxyHandler
from thumbnail import handler as ThumbnailHandler


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------
@app.route('/api/download', methods=['GET', 'OPTIONS'])
def api_download():
    qs = request.query_string.decode()
    path = '/api/download' + ('?' + qs if qs else '')
    return _run_handler(DownloadHandler, request.method, path)


@app.route('/api/proxy', methods=['GET', 'OPTIONS'])
def api_proxy():
    qs = request.query_string.decode()
    path = '/api/proxy' + ('?' + qs if qs else '')
    return _run_handler(ProxyHandler, request.method, path)


@app.route('/api/thumbnail', methods=['GET', 'OPTIONS'])
def api_thumbnail():
    qs = request.query_string.decode()
    path = '/api/thumbnail' + ('?' + qs if qs else '')
    return _run_handler(ThumbnailHandler, request.method, path)


# ---------------------------------------------------------------------------
# Static frontend
# ---------------------------------------------------------------------------
@app.route('/')
def index():
    return send_from_directory('.', 'index.html')


@app.route('/<path:filename>')
def static_files(filename):
    return send_from_directory('.', filename)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
