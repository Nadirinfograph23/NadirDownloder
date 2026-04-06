"""
NADIR DOWNLOADER - Flask Server for Replit
Calls API functions directly for clean, reliable routing.
"""

import os
import sys
import json
import re
import tempfile
import threading
from urllib.parse import urlparse, parse_qs

from flask import Flask, request, Response, send_from_directory, stream_with_context

# Add api/ to path so we can import modules directly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'api'))

from download import extract_video_info, detect_platform
import proxy as _proxy_module
import thumbnail as _thumb_module
import ig_download as _ig_dl_module
import requests as _requests
import yt_dlp

app = Flask(__name__, static_folder='.', static_url_path='')

# ─────────────────────────────────────────────────────────────────────────────
# yt-dlp auto-update — runs once in the background on every server startup.
# Extractors for TikTok / Instagram / Pinterest / Twitter go stale when platforms
# change their APIs.  Keeping yt-dlp current is the single most effective
# mitigation for "temporarily broken" extraction.
# ─────────────────────────────────────────────────────────────────────────────
_ytdlp_update_status = {'done': False, 'updated': False, 'error': None}

def _auto_update_ytdlp():
    """
    Use yt-dlp's own built-in self-update mechanism (works in NixOS/Replit).
    Falls back to  pip install --user  on failure.
    """
    import subprocess, importlib
    before = yt_dlp.version.__version__

    def _reload_version():
        try:
            importlib.reload(yt_dlp.version)
        except Exception:
            pass

    # Strategy 1: yt-dlp --update (the tool updates its own binary)
    try:
        res = subprocess.run(
            [sys.executable, '-m', 'yt_dlp', '--update'],
            capture_output=True, text=True, timeout=120,
        )
        _reload_version()
        after = yt_dlp.version.__version__
        if before != after:
            _ytdlp_update_status.update({'done': True, 'updated': True, 'from': before, 'to': after})
            print(f'[yt-dlp] Updated  {before} → {after}')
            return
        # Already current — strategy 1 was fine, just no new version
        _ytdlp_update_status.update({'done': True, 'updated': False, 'from': before, 'to': after})
        print(f'[yt-dlp] Already current ({after})')
        return
    except Exception:
        pass

    # Strategy 2: pip install --user (user-level, no system write needed)
    try:
        res = subprocess.run(
            [sys.executable, '-m', 'pip', 'install', '--user', '-U', '--quiet', 'yt-dlp'],
            capture_output=True, text=True, timeout=120,
        )
        _reload_version()
        after = yt_dlp.version.__version__
        _ytdlp_update_status.update({'done': True, 'updated': before != after, 'from': before, 'to': after})
        print(f'[yt-dlp] pip --user update: {before} → {after}')
        return
    except Exception as exc:
        _ytdlp_update_status.update({'done': True, 'error': str(exc)})
        print(f'[yt-dlp] Auto-update failed: {exc}')

threading.Thread(target=_auto_update_ytdlp, daemon=True).start()

# ─────────────────────────────────────────────────────────────────────────────
# /api/status — lightweight health + version check for debugging
# ─────────────────────────────────────────────────────────────────────────────
@app.route('/api/status')
def api_status():
    import os as _os
    cookie_dir = _os.path.join(_os.path.dirname(__file__), 'cookies')
    cookie_files = [f for f in _os.listdir(cookie_dir) if f.endswith('.txt') and f != 'README.txt'] if _os.path.isdir(cookie_dir) else []
    payload = {
        'ytdlp_version': yt_dlp.version.__version__,
        'ytdlp_update': _ytdlp_update_status,
        'cookie_files_loaded': cookie_files,
    }
    resp = Response(json.dumps(payload), content_type='application/json')
    resp.headers['Access-Control-Allow-Origin'] = '*'
    return resp

# ─────────────────────────────────────────────────────────────────────────────
# /api/download  — extract video info and return download links as JSON
# Accepts both POST (JSON body) and GET (query param) for flexibility.
# ─────────────────────────────────────────────────────────────────────────────
@app.route('/api/download', methods=['GET', 'POST', 'OPTIONS'])
def api_download():
    if request.method == 'OPTIONS':
        return _cors_ok()

    if request.method == 'POST':
        body = request.get_json(silent=True) or {}
        url = (body.get('url') or '').strip()
    else:
        url = (request.args.get('url') or '').strip()

    if not url:
        return _json_error(400, 'Missing url parameter')

    try:
        result = extract_video_info(url)
        resp = Response(json.dumps(result), status=200,
                        content_type='application/json')
        resp.headers['Access-Control-Allow-Origin'] = '*'
        return resp
    except Exception as e:
        return _json_error(500, str(e))


# ─────────────────────────────────────────────────────────────────────────────
# /api/proxy  — proxy / download video server-side
# ─────────────────────────────────────────────────────────────────────────────
@app.route('/api/proxy', methods=['GET', 'OPTIONS'])
def api_proxy():
    if request.method == 'OPTIONS':
        return _cors_ok()

    video_url  = (request.args.get('url')       or '').strip()
    platform   = (request.args.get('platform')  or '').strip()
    filename   = (request.args.get('filename')  or 'video').strip()
    fmt        = (request.args.get('format')    or 'mp4').strip()
    format_id  = (request.args.get('format_id') or '').strip() or None

    if not video_url or not platform:
        return _json_error(400, 'Missing url or platform parameter')

    if platform not in _proxy_module.PLATFORM_CONFIG:
        return _json_error(400, 'Unsupported platform')

    safe_name = _proxy_module._sanitise_filename(filename)
    disposition = f'{safe_name}.{fmt}'

    # Platforms that always re-extract fresh via yt-dlp at download time
    if platform in _proxy_module.YTDLP_PLATFORMS:
        return _ytdlp_download(video_url, platform, format_id, disposition, fmt)

    # Direct proxy for Facebook etc.
    return _direct_proxy(video_url, platform, disposition, fmt)


def _ytdlp_download(video_url, platform, format_id, disposition, fmt):
    """Re-extract and stream via yt-dlp (merges video+audio with ffmpeg)."""
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=f'.{fmt}', dir='/tmp')
    os.close(tmp_fd)

    try:
        ydl_opts = _proxy_module._ydl_opts_for_platform(platform, format_id, tmp_path)
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])

        # yt-dlp may rename the output file
        actual = tmp_path
        if not os.path.exists(actual) or os.path.getsize(actual) == 0:
            for ext in ('mp4', 'mkv', 'webm', 'mp4.mp4'):
                candidate = tmp_path + '.' + ext
                if os.path.exists(candidate) and os.path.getsize(candidate) > 0:
                    actual = candidate
                    break
            else:
                return _json_error(502, 'yt-dlp produced no output')

        file_size = os.path.getsize(actual)

        def generate():
            try:
                with open(actual, 'rb') as f:
                    while True:
                        chunk = f.read(65536)
                        if not chunk:
                            break
                        yield chunk
            finally:
                for p in (tmp_path, actual):
                    try:
                        if os.path.exists(p):
                            os.unlink(p)
                    except Exception:
                        pass

        headers = {
            'Content-Type': 'video/mp4',
            'Content-Length': str(file_size),
            'Content-Disposition': f'attachment; filename="{disposition}"',
            'Access-Control-Allow-Origin': '*',
            'Cache-Control': 'no-store',
        }
        return Response(stream_with_context(generate()), status=200, headers=headers)

    except yt_dlp.utils.DownloadError as e:
        _cleanup(tmp_path)
        return _json_error(502, f'Download failed: {e}')
    except Exception as e:
        _cleanup(tmp_path)
        return _json_error(502, f'Failed to download video: {e}')


def _direct_proxy(video_url, platform, disposition, fmt):
    """Stream a CDN URL directly with platform-specific headers."""
    config = _proxy_module.PLATFORM_CONFIG[platform]

    try:
        resp = _requests.get(
            video_url,
            headers=config['headers'],
            timeout=25,
            stream=True,
            allow_redirects=True,
        )
        resp.raise_for_status()
    except _requests.exceptions.HTTPError as e:
        return _json_error(e.response.status_code, f'Upstream error: {e.response.status_code}')
    except Exception as e:
        return _json_error(502, f'Failed to fetch video: {e}')

    if not _proxy_module._is_url_allowed(resp.url, platform):
        resp.close()
        return _json_error(403, 'URL domain not allowed for this platform')

    # Peek at first chunk to detect CDN error pages
    first_chunk = b''
    for chunk in resp.iter_content(chunk_size=512):
        first_chunk = chunk
        break

    if first_chunk:
        peek = first_chunk.lstrip()
        if peek.startswith((b'<?xml', b'<Error', b'<!DOCTYPE', b'<html')):
            resp.close()
            return _json_error(502, 'CDN returned an error page. The link may have expired.')

    upstream_ct = resp.headers.get('Content-Type', 'video/mp4')
    content_type = 'video/mp4' if not upstream_ct.startswith('video/') else upstream_ct
    content_length = resp.headers.get('Content-Length', '')

    def generate():
        total = len(first_chunk)
        if first_chunk:
            yield first_chunk
        for chunk in resp.iter_content(chunk_size=65536):
            if not chunk:
                continue
            total += len(chunk)
            if total > _proxy_module.MAX_PROXY_BYTES:
                break
            yield chunk
        resp.close()

    headers = {
        'Content-Type': content_type,
        'Content-Disposition': f'attachment; filename="{disposition}"',
        'Access-Control-Allow-Origin': '*',
        'Cache-Control': 'no-store',
    }
    if content_length:
        headers['Content-Length'] = content_length

    return Response(stream_with_context(generate()), status=200, headers=headers)


# ─────────────────────────────────────────────────────────────────────────────
# /api/thumbnail  — proxy thumbnail images to bypass CORS / Referer checks
# ─────────────────────────────────────────────────────────────────────────────
@app.route('/api/thumbnail', methods=['GET', 'OPTIONS'])
def api_thumbnail():
    if request.method == 'OPTIONS':
        return _cors_ok()

    thumb_url = (request.args.get('url')      or '').strip()
    platform  = (request.args.get('platform') or '').strip().lower()

    if not thumb_url or not thumb_url.startswith('http'):
        return _json_error(400, 'Missing or invalid url')

    if not _thumb_module._domain_allowed(thumb_url, platform):
        return _json_error(403, 'Domain not allowed')

    headers = {
        'User-Agent': _thumb_module._UA,
        'Accept': 'image/avif,image/webp,image/apng,image/*,*/*;q=0.8',
    }
    referer = _thumb_module._PLATFORM_REFERERS.get(platform)
    if referer:
        headers['Referer'] = referer

    try:
        resp = _requests.get(thumb_url, headers=headers, timeout=10, stream=True)
        resp.raise_for_status()

        ct = resp.headers.get('Content-Type', 'image/jpeg')
        if not ct.startswith('image/'):
            resp.close()
            return _json_error(502, 'Not an image')

        def generate():
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    yield chunk
            resp.close()

        out_headers = {
            'Content-Type': ct,
            'Cache-Control': 'public, max-age=3600',
            'Access-Control-Allow-Origin': '*',
        }
        cl = resp.headers.get('Content-Length', '')
        if cl:
            out_headers['Content-Length'] = cl

        return Response(stream_with_context(generate()), status=200, headers=out_headers)

    except Exception as e:
        return _json_error(502, f'Failed to proxy thumbnail: {e}')


# ─────────────────────────────────────────────────────────────────────────────
# /api/ig-download  — dedicated Instagram download (extract + stream fresh CDN)
# ─────────────────────────────────────────────────────────────────────────────
@app.route('/api/ig-download', methods=['GET', 'OPTIONS'])
def api_ig_download():
    if request.method == 'OPTIONS':
        return _cors_ok()

    ig_url = (request.args.get('url') or '').strip()

    if not ig_url or not ig_url.startswith('http'):
        return _json_error(400, 'Missing or invalid url parameter')

    import re as _re
    if not _re.search(r'instagram\.com|instagr\.am', ig_url, _re.I):
        return _json_error(400, 'URL is not an Instagram link')

    status, headers_dict, body = _ig_dl_module.stream_instagram(ig_url)

    if isinstance(body, (bytes, bytearray)):
        resp = Response(body, status=status)
    else:
        resp = Response(stream_with_context(body), status=status)

    for k, v in headers_dict.items():
        resp.headers[k] = v

    return resp


# ─────────────────────────────────────────────────────────────────────────────
# Static frontend
# ─────────────────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/favicon.ico')
def favicon():
    return Response(status=204)

@app.route('/<path:filename>')
def static_files(filename):
    return send_from_directory('.', filename)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _cors_ok():
    r = Response(status=200)
    r.headers['Access-Control-Allow-Origin'] = '*'
    r.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    r.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return r

def _json_error(status, message):
    r = Response(json.dumps({'error': message}), status=status,
                 content_type='application/json')
    r.headers['Access-Control-Allow-Origin'] = '*'
    return r

def _cleanup(*paths):
    for p in paths:
        try:
            if p and os.path.exists(p):
                os.unlink(p)
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
