"""
NADIR DOWNLOADER - Instagram Download via RapidAPI
/api/ig-download?url=<original_instagram_url>

Uses the Instagram Downloader RapidAPI service to get a fresh video URL,
then streams the video bytes directly to the client.

Requires: RAPIDAPI_KEY environment variable
Fallback: yt-dlp (for public posts when RapidAPI key is absent)
"""

from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, quote
import os
import re
import json
import requests as _req

_UA_MOBILE = (
    'Mozilla/5.0 (Linux; Android 13; SM-G991B) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/124.0.0.0 Mobile Safari/537.36'
)

_RAPIDAPI_HOST = (
    'instagram-downloader-download-instagram-videos-stories1'
    '.p.rapidapi.com'
)
_RAPIDAPI_ENDPOINT = f'https://{_RAPIDAPI_HOST}/get-info-rapidapi'

_MAX_STREAM_BYTES = 500 * 1024 * 1024  # 500 MB cap


# ─────────────────────────────────────────────────────────────────────────────
# RapidAPI extraction
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_via_rapidapi(ig_url):
    """
    Call the RapidAPI Instagram Downloader service.
    Returns (download_url, safe_title) or raises RuntimeError.
    """
    api_key = os.environ.get('RAPIDAPI_KEY', '').strip()
    if not api_key:
        raise RuntimeError('__no_key__')

    encoded_url = quote(ig_url, safe='')
    try:
        resp = _req.get(
            f'{_RAPIDAPI_ENDPOINT}?url={encoded_url}',
            headers={
                'x-rapidapi-key': api_key,
                'x-rapidapi-host': _RAPIDAPI_HOST,
            },
            timeout=20,
        )
    except Exception as e:
        raise RuntimeError(f'RapidAPI request failed: {e}')

    if resp.status_code in (401, 403):
        raise RuntimeError('RapidAPI key is invalid or expired.')
    if resp.status_code == 429:
        raise RuntimeError('RapidAPI rate limit reached. Please try again later.')
    if resp.status_code >= 400:
        raise RuntimeError(f'RapidAPI returned status {resp.status_code}.')

    try:
        data = resp.json()
    except Exception:
        raise RuntimeError('RapidAPI returned an invalid JSON response.')

    download_url = (
        data.get('download_url')
        or data.get('video_url')
        or data.get('url')
        or ''
    )

    if not download_url:
        medias = data.get('medias') or data.get('media') or []
        if isinstance(medias, list):
            for m in medias:
                if isinstance(m, dict):
                    u = m.get('url') or m.get('download_url') or ''
                    if u and u.startswith('http'):
                        download_url = u
                        break

    if not download_url:
        for v in data.values():
            if isinstance(v, str) and v.startswith('http') and (
                'mp4' in v or 'video' in v.lower() or 'cdn' in v.lower()
            ):
                download_url = v
                break

    if not download_url:
        raise RuntimeError(
            'Could not extract video URL from Instagram. '
            'The post may be private or not a video.'
        )

    raw_title = (
        data.get('title')
        or data.get('caption')
        or data.get('shortcode')
        or 'instagram_video'
    )
    safe_title = re.sub(r'[^\w\s\-]', '', str(raw_title))[:60].strip() or 'instagram_video'

    return download_url, safe_title


# ─────────────────────────────────────────────────────────────────────────────
# yt-dlp fallback (no-auth, public posts only)
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_via_ytdlp(ig_url):
    """
    Fallback: try yt-dlp without cookies. Works only for some public posts.
    Returns (download_url, safe_title) or raises RuntimeError.
    """
    try:
        import yt_dlp
    except ImportError:
        raise RuntimeError('yt-dlp is not available.')

    opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'noplaylist': True,
        'socket_timeout': 25,
        'extractor_retries': 1,
        'format': (
            'best[ext=mp4][vcodec!=none][acodec!=none]'
            '/best[ext=mp4]/best[vcodec!=none][acodec!=none]/best'
        ),
        'http_headers': {'User-Agent': _UA_MOBILE},
    }

    # Use cookies from env if available
    session_id = os.environ.get('IG_SESSION_ID', '').strip()
    if session_id:
        import tempfile
        cookie_content = '\n'.join([
            '# Netscape HTTP Cookie File',
            f'.instagram.com\tTRUE\t/\tTRUE\t9999999999\tsessionid\t{session_id}',
        ]) + '\n'
        tf = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', dir='/tmp', delete=False)
        tf.write(cookie_content)
        tf.close()
        opts['cookiefile'] = tf.name

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(ig_url, download=False)

    if not info:
        raise RuntimeError('yt-dlp returned no info.')

    url = info.get('url') or ''
    title = (info.get('title') or 'instagram_video').strip()
    safe_title = re.sub(r'[^\w\s\-]', '', title)[:60].strip() or 'instagram_video'

    if url and url.startswith('http'):
        return url, safe_title

    for rf in (info.get('requested_formats') or []):
        u = rf.get('url', '')
        if u and rf.get('vcodec', 'none') != 'none' and rf.get('acodec', 'none') != 'none':
            return u, safe_title

    for f in (info.get('formats') or []):
        u = f.get('url', '')
        if u and f.get('vcodec', 'none') != 'none':
            return u, safe_title

    raise RuntimeError('yt-dlp could not find a playable stream.')


# ─────────────────────────────────────────────────────────────────────────────
# Main stream function
# ─────────────────────────────────────────────────────────────────────────────

def stream_instagram(ig_url):
    """
    1. Try RapidAPI (requires RAPIDAPI_KEY env var).
    2. Fall back to yt-dlp for public posts.
    Returns (status_code, headers_dict, body_bytes_or_generator).
    """
    cdn_url = None
    safe_title = 'instagram_video'

    # Step 1: RapidAPI
    try:
        cdn_url, safe_title = _fetch_via_rapidapi(ig_url)
    except RuntimeError as e:
        if str(e) != '__no_key__':
            return (
                502,
                {'Content-Type': 'application/json'},
                json.dumps({'error': str(e)}).encode(),
            )
        # No key — fall through to yt-dlp
        cdn_url = None

    # Step 2: yt-dlp fallback
    if cdn_url is None:
        try:
            cdn_url, safe_title = _fetch_via_ytdlp(ig_url)
        except Exception as e:
            err_msg = str(e)
            if 'login' in err_msg.lower() or 'empty media' in err_msg.lower() or 'authentication' in err_msg.lower():
                err_msg = (
                    'Instagram requires authentication to download this video. '
                    'Please configure RAPIDAPI_KEY to enable Instagram downloads.'
                )
            return (
                502,
                {'Content-Type': 'application/json'},
                json.dumps({'error': err_msg}).encode(),
            )

    # Stream the video
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
            allow_redirects=True,
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
        if resp.headers.get('Content-Length'):
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


# ─────────────────────────────────────────────────────────────────────────────
# Vercel serverless handler
# ─────────────────────────────────────────────────────────────────────────────

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
