"""
NADIR DOWNLOADER - Thumbnail Proxy API
Proxies thumbnail images server-side to avoid CORS / Referer restrictions
on Instagram, TikTok, Twitter, and other CDN URLs.
"""

from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import re
import requests as _req

_UA = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/124.0.0.0 Safari/537.36'
)

_PLATFORM_REFERERS = {
    'instagram': 'https://www.instagram.com/',
    'tiktok':    'https://www.tiktok.com/',
    'twitter':   'https://twitter.com/',
    'facebook':  'https://www.facebook.com/',
    'pinterest': 'https://www.pinterest.com/',
    'youtube':   'https://www.youtube.com/',
}

# Security: only allow thumbnail domains we trust per platform
_ALLOWED_DOMAINS = {
    'youtube':   [r'(^|\.)ytimg\.com$', r'(^|\.)ggpht\.com$', r'(^|\.)googleusercontent\.com$'],
    'tiktok':    [r'(^|\.)tiktokcdn\.com$', r'(^|\.)tiktokcdn-us\.com$', r'(^|\.)ibytedtos\.com$', r'(^|\.)ibyteimg\.com$'],
    'instagram': [r'(^|\.)cdninstagram\.com$', r'(^|\.)fbcdn\.net$'],
    'twitter':   [r'(^|\.)twimg\.com$', r'(^|\.)pbs\.twimg\.com$'],
    'facebook':  [r'(^|\.)fbcdn\.net$', r'(^|\.)fbsbx\.com$'],
    'pinterest': [r'(^|\.)pinimg\.com$'],
}


def _domain_allowed(url, platform):
    patterns = _ALLOWED_DOMAINS.get(platform, [])
    host = urlparse(url).hostname or ''
    return any(re.search(p, host) for p in patterns)


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        thumb_url = (params.get('url', [None])[0] or '').strip()
        platform = (params.get('platform', [''])[0] or '').strip().lower()

        if not thumb_url or not thumb_url.startswith('http'):
            self._send_error(400, 'Missing or invalid url')
            return

        if not _domain_allowed(thumb_url, platform):
            self._send_error(403, 'Domain not allowed')
            return

        headers = {
            'User-Agent': _UA,
            'Accept': 'image/avif,image/webp,image/apng,image/*,*/*;q=0.8',
        }
        referer = _PLATFORM_REFERERS.get(platform)
        if referer:
            headers['Referer'] = referer

        try:
            resp = _req.get(thumb_url, headers=headers, timeout=10, stream=True)
            resp.raise_for_status()

            ct = resp.headers.get('Content-Type', 'image/jpeg')
            if not ct.startswith('image/'):
                resp.close()
                self._send_error(502, 'Not an image')
                return

            content_length = resp.headers.get('Content-Length', '')

            self.send_response(200)
            self.send_header('Content-Type', ct)
            if content_length:
                self.send_header('Content-Length', content_length)
            self.send_header('Cache-Control', 'public, max-age=3600')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()

            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    self.wfile.write(chunk)
            resp.close()

        except Exception as e:
            self._send_error(502, f'Failed to proxy thumbnail: {str(e)}')

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def _send_error(self, status, message):
        import json
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps({'error': message}).encode('utf-8'))

    def log_message(self, fmt, *args):
        pass
