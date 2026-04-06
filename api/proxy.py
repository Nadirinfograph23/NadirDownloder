"""
NADIR DOWNLOADER - Video Proxy API
Proxies video downloads through the server so that platform-specific
headers / cookies are sent correctly.  The browser cannot attach these
headers when clicking a plain <a href="..."> link, so this endpoint
fetches the video server-side and streams it back to the client.
"""

from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import re
import os
import tempfile
import yt_dlp
import requests as _req

# Maximum response size we will proxy (bytes).
MAX_PROXY_BYTES = 200 * 1024 * 1024  # 200 MB cap

# Platforms that ALWAYS use yt-dlp to re-extract and download at proxy time.
# - tiktok:    CDN URLs require fresh cookies at download time
# - instagram: CDN URLs expire within 1-5 minutes after extraction
# - twitter:   CDN URLs expire similarly fast
# - pinterest: CDN links are unreliable; fresh yt-dlp is better
# NOTE: youtube is NOT here — it now uses process4.me direct links via ytdown.to API
YTDLP_PLATFORMS = {'tiktok', 'instagram', 'twitter', 'pinterest'}

# Platforms whose CDN URLs require server-side headers to download.
# Domain patterns are anchored so that e.g. "evil-tiktokcdn.com" won't match.
PLATFORM_CONFIG = {
    'tiktok': {
        'domain_patterns': [
            r'(^|\.)tiktokcdn\.com$',
            r'(^|\.)tiktok\.com$',
            r'(^|\.)tiktokv\.com$',
            r'(^|\.)tiktokcdn-us\.com$',
            r'(^|\.)musical\.ly$',
            r'(^|\.)byteoversea\.com$',
            r'(^|\.)ibytedtos\.com$',
            r'(^|\.)ibyteimg\.com$',
        ],
        'headers': {
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/120.0.0.0 Safari/537.36'
            ),
            'Referer': 'https://www.tiktok.com/',
            'Accept': '*/*',
        },
    },
    'facebook': {
        'domain_patterns': [
            r'(^|\.)fbcdn\.net$',
            r'(^|\.)facebook\.com$',
            r'(^|\.)fbcdn\.com$',
            r'(^|\.)fb\.com$',
            r'(^|\.)fbsbx\.com$',
            r'(^|\.)fbpigeon\.com$',
        ],
        'headers': {
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/124.0.0.0 Safari/537.36'
            ),
            'Referer': 'https://www.facebook.com/',
            'Accept': 'video/mp4,video/*;q=0.9,*/*;q=0.8',
            'Range': 'bytes=0-',
        },
    },
    'instagram': {
        'domain_patterns': [
            r'(^|\.)cdninstagram\.com$',
            r'(^|\.)instagram\.com$',
            r'(^|\.)fbcdn\.net$',
        ],
        'headers': {
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/120.0.0.0 Safari/537.36'
            ),
        },
    },
    'pinterest': {
        'domain_patterns': [
            r'(^|\.)pinimg\.com$',
            r'(^|\.)pinterest\.com$',
            r'(^|\.)pinimg\.net$',
        ],
        'headers': {
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/124.0.0.0 Safari/537.36'
            ),
            'Referer': 'https://www.pinterest.com/',
            'Accept': 'video/mp4,video/*;q=0.9,*/*;q=0.8',
        },
    },
    'twitter': {
        'domain_patterns': [
            r'(^|\.)twimg\.com$',
            r'(^|\.)twitter\.com$',
            r'(^|\.)x\.com$',
            r'(^|\.)video\.twimg\.com$',
        ],
        'headers': {
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/120.0.0.0 Safari/537.36'
            ),
        },
    },
    # YouTube: now uses process4.me direct links (via ytdown.to API).
    # Direct streaming — no yt-dlp needed.
    'youtube': {
        'domain_patterns': [
            r'^s\d+\.process4\.me$',
            r'(^|\.)process4\.me$',
            r'(^|\.)googlevideo\.com$',
            r'(^|\.)youtube\.com$',
        ],
        'headers': {
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/124.0.0.0 Safari/537.36'
            ),
            'Referer': 'https://app.ytdown.to/',
            'Accept': 'video/mp4,video/*;q=0.9,*/*;q=0.8',
        },
    },
}


def _is_url_allowed(url, platform):
    """Check that the URL's domain matches the expected CDN for the platform."""
    config = PLATFORM_CONFIG.get(platform)
    if not config:
        return False
    parsed = urlparse(url)
    host = parsed.hostname or ''
    for pattern in config['domain_patterns']:
        if re.search(pattern, host):
            return True
    return False


def _sanitise_filename(name):
    """Remove characters that are unsafe in a Content-Disposition filename."""
    return re.sub(r'[^\w\s\-.]', '', name).strip() or 'video'


_COOKIE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'cookies')


def _cookie_file(platform):
    path = os.path.join(_COOKIE_DIR, f'{platform}.txt')
    return path if os.path.isfile(path) else None


def _ydl_opts_for_platform(platform, format_id, tmp_path):
    """Build yt-dlp options for a given platform download."""
    _UA = (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/120.0.0.0 Safari/537.36'
    )
    _UA_MOBILE = (
        'Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) '
        'AppleWebKit/605.1.15 (KHTML, like Gecko) '
        'Version/17.4 Mobile/15E148 Safari/604.1'
    )
    base = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': False,
        'noplaylist': True,
        'socket_timeout': 30,
        'extractor_retries': 3,
        'outtmpl': tmp_path,
        'overwrites': True,
        'prefer_ffmpeg': True,
        'merge_output_format': 'mp4',
    }

    if platform == 'tiktok':
        base['format'] = format_id or 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best'
        base['http_headers'] = {'User-Agent': _UA, 'Referer': 'https://www.tiktok.com/'}

    elif platform == 'instagram':
        base['format'] = format_id or 'best[ext=mp4]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/best'
        base['http_headers'] = {'User-Agent': _UA_MOBILE}
        cf = _cookie_file('instagram')
        if cf:
            base['cookiefile'] = cf

    elif platform == 'twitter':
        base['format'] = format_id or 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[ext=mp4]/best'
        base['http_headers'] = {'User-Agent': _UA}

    elif platform == 'youtube':
        base['format'] = format_id or 'best[ext=mp4]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/best'
        base['http_headers'] = {'User-Agent': _UA}
        base['extractor_args'] = {
            'youtube': {
                'player_client': ['tv_embedded', 'ios', 'android_vr'],
                'player_skip': ['configs', 'webpage'],
            }
        }
        base['age_limit'] = 99
        cf = _cookie_file('youtube')
        if cf:
            base['cookiefile'] = cf

    elif platform == 'pinterest':
        base['format'] = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[ext=mp4]/best[ext!=webm]/best'
        base['http_headers'] = {
            'User-Agent': _UA,
            'Referer': 'https://www.pinterest.com/',
            'Accept-Language': 'en-US,en;q=0.9',
        }
        base['hls_use_mpegts'] = True
        base['concurrent_fragment_downloads'] = 4

    else:
        base['format'] = format_id or 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best'
        base['http_headers'] = {'User-Agent': _UA, 'Referer': f'https://www.{platform}.com/'}

    return base


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        video_url = params.get('url', [None])[0]
        platform = params.get('platform', [None])[0]
        filename = params.get('filename', ['video'])[0]
        fmt = params.get('format', ['mp4'])[0]
        format_id = params.get('format_id', [None])[0]

        if not video_url or not platform:
            self._send_error(400, 'Missing url or platform parameter')
            return

        if platform not in PLATFORM_CONFIG:
            self._send_error(400, 'Unsupported platform')
            return

        # Platforms that always re-extract fresh URLs via yt-dlp at download time.
        # This prevents stale CDN URL failures (Instagram/Twitter expire in minutes).
        if platform in YTDLP_PLATFORMS:
            self._handle_ytdlp_download(video_url, platform, format_id, filename, fmt)
            return

        config = PLATFORM_CONFIG[platform]

        try:
            resp = _req.get(
                video_url,
                headers=config['headers'],
                timeout=25,
                stream=True,
                allow_redirects=True,
            )
            resp.raise_for_status()
        except _req.exceptions.HTTPError as e:
            self._send_error(e.response.status_code,
                             f'Upstream error: {e.response.status_code}')
            return
        except Exception as e:
            self._send_error(502, f'Failed to fetch video: {str(e)}')
            return

        # Safety check on the FINAL URL (after all redirects).
        if not _is_url_allowed(resp.url, platform):
            resp.close()
            self._send_error(403, 'URL domain not allowed for this platform')
            return

        # Detect XML / HTML error pages returned by CDNs.
        first_chunk = b''
        for chunk in resp.iter_content(chunk_size=512):
            first_chunk = chunk
            break

        if first_chunk:
            peek = first_chunk.lstrip()
            if peek.startswith(b'<?xml') or peek.startswith(b'<Error') or peek.startswith(b'<!DOCTYPE') or peek.startswith(b'<html'):
                resp.close()
                self._send_error(502, 'CDN returned an error page. The link may have expired.')
                return

        upstream_ct = resp.headers.get('Content-Type', 'video/mp4')
        content_type = 'video/mp4' if not upstream_ct.startswith('video/') else upstream_ct
        content_length = resp.headers.get('Content-Length', '')

        safe_name = _sanitise_filename(filename)
        disposition_name = f'{safe_name}.{fmt}'

        self.send_response(200)
        self.send_header('Content-Type', content_type)
        if content_length:
            self.send_header('Content-Length', content_length)
        self.send_header('Content-Disposition', f'attachment; filename="{disposition_name}"')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()

        if first_chunk:
            self.wfile.write(first_chunk)
        total = len(first_chunk)
        for chunk in resp.iter_content(chunk_size=65536):
            if not chunk:
                continue
            total += len(chunk)
            if total > MAX_PROXY_BYTES:
                break
            self.wfile.write(chunk)

        resp.close()

    def _handle_ytdlp_download(self, video_url, platform, format_id, filename, fmt):
        """Re-extract and download via yt-dlp at download time for fresh CDN URLs."""
        tmp_path = None
        try:
            tmp_fd, tmp_path = tempfile.mkstemp(suffix=f'.{fmt}', dir='/tmp')
            os.close(tmp_fd)

            ydl_opts = _ydl_opts_for_platform(platform, format_id, tmp_path)

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([video_url])

            # yt-dlp may merge streams and produce a file with a different extension
            if not os.path.exists(tmp_path) or os.path.getsize(tmp_path) == 0:
                # Try to find the actual output file (yt-dlp may have added ext)
                base = tmp_path
                for ext in ('mp4', 'mkv', 'webm'):
                    candidate = base + '.' + ext if not base.endswith('.' + ext) else base
                    if os.path.exists(candidate) and os.path.getsize(candidate) > 0:
                        tmp_path = candidate
                        break
                else:
                    self._send_error(502, 'yt-dlp produced no output')
                    return

            file_size = os.path.getsize(tmp_path)
            safe_name = _sanitise_filename(filename)
            disposition_name = f'{safe_name}.{fmt}'

            self.send_response(200)
            self.send_header('Content-Type', 'video/mp4')
            self.send_header('Content-Length', str(file_size))
            self.send_header('Content-Disposition',
                             f'attachment; filename="{disposition_name}"')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()

            with open(tmp_path, 'rb') as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    self.wfile.write(chunk)

        except yt_dlp.utils.DownloadError as e:
            self._send_error(502, f'Download failed: {str(e)}')
        except Exception as e:
            self._send_error(502, f'Failed to download video: {str(e)}')
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def _send_error(self, status, message):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        import json
        self.wfile.write(json.dumps({'error': message}).encode('utf-8'))

    def log_message(self, fmt, *args):
        """Suppress default logging."""
        pass
