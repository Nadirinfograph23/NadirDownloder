"""
NADIR DOWNLOADER - Video Proxy API
Proxies video downloads through the server so that platform-specific
headers / cookies are sent correctly.  The browser cannot attach these
headers when clicking a plain <a href="..."> link, so this endpoint
fetches the video server-side and streams it back to the client.
"""

from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import urllib.request
import re

# Maximum response size we will proxy (bytes).
# Vercel Serverless Functions have a 4.5 MB response-body limit on the
# Hobby plan.  We cap slightly below that to leave room for headers.
MAX_PROXY_BYTES = 50 * 1024 * 1024  # 50 MB generous cap; Vercel will enforce its own limit

# Platforms whose CDN URLs require server-side headers to download.
# Only these platforms are proxied; others use direct links.
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
                'Chrome/120.0.0.0 Safari/537.36'
            ),
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
        ],
        'headers': {
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/120.0.0.0 Safari/537.36'
            ),
        },
    },
    'twitter': {
        'domain_patterns': [
            r'(^|\.)twimg\.com$',
            r'(^|\.)twitter\.com$',
            r'(^|\.)x\.com$',
        ],
        'headers': {
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/120.0.0.0 Safari/537.36'
            ),
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


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        video_url = params.get('url', [None])[0]
        platform = params.get('platform', [None])[0]
        filename = params.get('filename', ['video'])[0]
        fmt = params.get('format', ['mp4'])[0]

        if not video_url or not platform:
            self._send_error(400, 'Missing url or platform parameter')
            return

        if platform not in PLATFORM_CONFIG:
            self._send_error(400, 'Unsupported platform')
            return

        if not _is_url_allowed(video_url, platform):
            self._send_error(403, 'URL domain not allowed for this platform')
            return

        config = PLATFORM_CONFIG[platform]
        req = urllib.request.Request(video_url, headers=config['headers'])

        try:
            resp = urllib.request.urlopen(req, timeout=25)
        except urllib.error.HTTPError as e:
            self._send_error(e.code, f'Upstream error: {e.code}')
            return
        except Exception as e:
            self._send_error(502, f'Failed to fetch video: {str(e)}')
            return

        content_type = resp.headers.get('Content-Type', 'video/mp4')
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

        # Stream in 64 KB chunks
        total = 0
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_PROXY_BYTES:
                break
            self.wfile.write(chunk)

        resp.close()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def _send_error(self, status, message):
        self.send_response(status)
        self.send_header('Content-Type', 'text/plain')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(message.encode('utf-8'))

    def log_message(self, fmt, *args):
        """Suppress default logging."""
        pass
