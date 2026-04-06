"""
NADIR DOWNLOADER - Dedicated Instagram Download Endpoint
/api/ig-download?url=<original_instagram_url>

Extracts a fresh CDN URL via yt-dlp on every request (never cached),
validates it, then streams the video directly to the client with
Content-Disposition: attachment so the browser downloads it immediately.

Fallback chain (up to 3 retries per attempt):
  1. yt-dlp — no cookies, mobile UA
  2. yt-dlp — no cookies, desktop UA
  3. yt-dlp — with cookies (cookies/instagram.txt), mobile UA
  4. yt-dlp — with cookies, desktop UA + extractor_args api=1

No raw CDN URL is ever returned to the frontend — all video bytes are
proxied through this endpoint so the browser never sees an Instagram URL.
"""

from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import os
import re
import time
import json
import yt_dlp
import requests as _req

_UA_MOBILE = (
    'Mozilla/5.0 (Linux; Android 13; SM-G991B) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/124.0.0.0 Mobile Safari/537.36'
)
_UA_DESKTOP = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/124.0.0.0 Safari/537.36'
)

# Prefer a muxed mp4 (no ffmpeg needed on Vercel).
# Fall back to best available if no muxed mp4 exists.
_IG_FORMAT = (
    'best[ext=mp4][vcodec!=none][acodec!=none]'
    '/best[ext=mp4]'
    '/best[vcodec!=none][acodec!=none]'
    '/best'
)

_MAX_RETRIES = 3
_COOKIE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'cookies')
_MAX_STREAM_BYTES = 500 * 1024 * 1024  # 500 MB cap


def _cookie_file():
    p = os.path.join(_COOKIE_DIR, 'instagram.txt')
    return p if os.path.isfile(p) else None


def _extract_cdn_url(ig_url):
    """
    Use yt-dlp (skip_download=True) to get a fresh CDN URL.
    Tries multiple UA / cookie combinations.
    Returns (cdn_url, filename_hint) or raises RuntimeError.
    """
    cookie_file = _cookie_file()

    attempt_configs = [
        # 1. No cookies, mobile UA
        {'http_headers': {'User-Agent': _UA_MOBILE}, 'cookiefile': None},
        # 2. No cookies, desktop UA
        {'http_headers': {'User-Agent': _UA_DESKTOP}, 'cookiefile': None},
        # 3. With cookies, mobile UA
        {'http_headers': {'User-Agent': _UA_MOBILE}, 'cookiefile': cookie_file},
        # 4. With cookies, desktop UA + api extractor arg
        {
            'http_headers': {'User-Agent': _UA_DESKTOP},
            'cookiefile': cookie_file,
            'extractor_args': {'instagram': {'api': ['1']}},
        },
    ]

    last_error = None

    for attempt_num in range(1, _MAX_RETRIES + 1):
        for cfg in attempt_configs:
            opts = {
                'quiet': True,
                'no_warnings': True,
                'skip_download': True,
                'noplaylist': True,
                'socket_timeout': 30,
                'extractor_retries': 2,
                'format': _IG_FORMAT,
                'http_headers': cfg['http_headers'],
            }
            if cfg.get('cookiefile') and os.path.exists(cfg['cookiefile']):
                opts['cookiefile'] = cfg['cookiefile']
            if cfg.get('extractor_args'):
                opts['extractor_args'] = cfg['extractor_args']

            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(ig_url, download=False)
                    if not info:
                        continue

                    cdn_url = info.get('url') or ''
                    title = (info.get('title') or 'instagram_video').strip()
                    # Sanitise title for use in filename
                    safe_title = re.sub(r'[^\w\s\-]', '', title)[:60].strip() or 'instagram_video'

                    if cdn_url and (
                        'cdninstagram' in cdn_url or
                        'fbcdn' in cdn_url or
                        cdn_url.startswith('http')
                    ):
                        return cdn_url, safe_title

                    # Fallback: check requested_formats
                    for rf in (info.get('requested_formats') or []):
                        rf_url = rf.get('url', '')
                        rf_v = rf.get('vcodec', 'none')
                        rf_a = rf.get('acodec', 'none')
                        if rf_url and rf_v != 'none' and rf_a != 'none':
                            return rf_url, safe_title

                    # Last resort: any format with video
                    for f in (info.get('formats') or []):
                        f_url = f.get('url', '')
                        if f_url and f.get('vcodec', 'none') != 'none':
                            return f_url, safe_title

            except yt_dlp.utils.DownloadError as e:
                last_error = str(e)
                # Private / unavailable — no point retrying
                msg = last_error.lower()
                if any(k in msg for k in ('private', 'unavailable', 'not found', '404')):
                    raise RuntimeError(
                        'This Instagram post is private, deleted, or unavailable.'
                    )
            except Exception as e:
                last_error = str(e)

        if attempt_num < _MAX_RETRIES:
            time.sleep(1.5)

    raise RuntimeError(
        last_error or 'Could not extract Instagram video after multiple attempts.'
    )


def _validate_cdn_url(cdn_url):
    """
    HEAD request to check the CDN URL is alive.
    Returns (ok: bool, content_length: str or '').
    """
    try:
        r = _req.head(
            cdn_url,
            headers={
                'User-Agent': _UA_MOBILE,
                'Referer': 'https://www.instagram.com/',
            },
            timeout=10,
            allow_redirects=True,
        )
        if r.status_code >= 400:
            return False, ''
        ct = r.headers.get('Content-Type', '')
        if 'html' in ct or 'xml' in ct or 'json' in ct:
            return False, ''
        cl = r.headers.get('Content-Length', '')
        if cl and int(cl) == 0:
            return False, ''
        return True, cl
    except Exception:
        return False, ''


def stream_instagram(ig_url):
    """
    Main logic: extract CDN URL, validate, then stream.
    Returns (status_code, headers_dict, generator_or_error_body).
    """
    # Retry the full extract+validate cycle up to 3 times
    cdn_url = None
    safe_title = 'instagram_video'
    last_error = 'Unknown extraction error.'

    for cycle in range(1, _MAX_RETRIES + 1):
        try:
            cdn_url, safe_title = _extract_cdn_url(ig_url)
        except RuntimeError as e:
            return (
                502,
                {'Content-Type': 'application/json'},
                json.dumps({'error': str(e)}).encode(),
            )

        ok, content_length = _validate_cdn_url(cdn_url)
        if ok:
            break

        # CDN URL invalid/expired — retry extraction
        cdn_url = None
        last_error = 'CDN URL expired or invalid. Retrying...'
        if cycle < _MAX_RETRIES:
            time.sleep(1)

    if cdn_url is None:
        return (
            502,
            {'Content-Type': 'application/json'},
            json.dumps({'error': 'Instagram CDN link expired. Please try again.'}).encode(),
        )

    # Stream the CDN URL
    try:
        resp = _req.get(
            cdn_url,
            headers={
                'User-Agent': _UA_MOBILE,
                'Referer': 'https://www.instagram.com/',
                'Accept': '*/*',
            },
            timeout=30,
            stream=True,
        )
        if resp.status_code >= 400:
            return (
                502,
                {'Content-Type': 'application/json'},
                json.dumps({'error': f'Instagram CDN returned {resp.status_code}.'}).encode(),
            )

        content_type = resp.headers.get('Content-Type', 'video/mp4')
        if not content_type.startswith('video/') and not content_type.startswith('application/'):
            content_type = 'video/mp4'

        out_headers = {
            'Content-Type': content_type,
            'Content-Disposition': f'attachment; filename="{safe_title}.mp4"',
            'Access-Control-Allow-Origin': '*',
            'Cache-Control': 'no-store',
        }
        if content_length:
            out_headers['Content-Length'] = content_length
        elif resp.headers.get('Content-Length'):
            out_headers['Content-Length'] = resp.headers['Content-Length']

        def _gen():
            total = 0
            for chunk in resp.iter_content(chunk_size=65536):
                if not chunk:
                    continue
                total += len(chunk)
                if total > _MAX_STREAM_BYTES:
                    break
                yield chunk
            resp.close()

        return 200, out_headers, _gen()

    except Exception as e:
        return (
            502,
            {'Content-Type': 'application/json'},
            json.dumps({'error': f'Streaming failed: {str(e)}'}).encode(),
        )


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        ig_url = (params.get('url', [None])[0] or '').strip()

        if not ig_url or not ig_url.startswith('http'):
            self._send_error(400, 'Missing or invalid url parameter')
            return

        # Basic check — must be an Instagram URL
        if not re.search(r'instagram\.com|instagr\.am', ig_url, re.I):
            self._send_error(400, 'URL is not an Instagram link')
            return

        status, headers, body = stream_instagram(ig_url)

        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.end_headers()

        if isinstance(body, (bytes, bytearray)):
            self.wfile.write(body)
        else:
            for chunk in body:
                self.wfile.write(chunk)

    def _send_error(self, status, message):
        body = json.dumps({'error': message}).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass
