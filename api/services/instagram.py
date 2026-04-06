"""
Instagram download service.

Strategy:
1. yt-dlp without cookies (fastest, works for many public posts)
2. yt-dlp with cookies (if cookies/instagram.txt exists)
3. snapinsta.app scraper fallback
4. Instagram embed page scraping

The returned link URL is the ORIGINAL Instagram URL so the proxy
re-extracts a fresh CDN URL at download time (avoids expiry on Vercel).

Returns ONE working download link. No URL validation (CDN URLs expire fast).
Retries up to 3 times per strategy.
"""

import os
import re
import time
import requests as _requests
import yt_dlp

_UA_DESKTOP = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/124.0.0.0 Safari/537.36'
)
_UA_MOBILE = (
    'Mozilla/5.0 (Linux; Android 13; SM-G991B) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/124.0.0.0 Mobile Safari/537.36'
)

_FORMAT = 'best[ext=mp4]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/best'
_MAX_RETRIES = 3


def _get_shortcode(url):
    m = re.search(r'/(?:p|reel|tv|videos)/([A-Za-z0-9_-]+)', url)
    return m.group(1) if m else None


def _try_ytdlp(url, cookie_file=None):
    """
    Try yt-dlp extraction. Returns (title, thumbnail) on success, or None on failure.
    Does NOT validate CDN URLs — they expire too quickly on serverless.
    """
    base_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'noplaylist': True,
        'socket_timeout': 30,
        'extractor_retries': 3,
        'format': _FORMAT,
    }
    if cookie_file and os.path.exists(cookie_file):
        base_opts['cookiefile'] = cookie_file

    ua_list = [_UA_MOBILE, _UA_DESKTOP]

    for attempt in range(1, _MAX_RETRIES + 1):
        for ua in ua_list:
            try:
                opts = {**base_opts, 'http_headers': {'User-Agent': ua}}
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    if info:
                        title = info.get('title', '') or ''
                        thumbnail = info.get('thumbnail', '') or ''
                        return title, thumbnail
            except Exception:
                pass

        if attempt < _MAX_RETRIES:
            time.sleep(1)

    return None


def _try_snapinsta(url):
    """Try snapinsta.app as a scraper fallback. Returns True if video likely exists."""
    try:
        session = _requests.Session()
        session.headers.update({'User-Agent': _UA_DESKTOP})
        home = session.get('https://snapinsta.app/', timeout=15)
        if home.status_code != 200:
            return False
        token_m = re.search(r'name="_token"\s+value="([^"]+)"', home.text)
        token = token_m.group(1) if token_m else ''
        resp = session.post(
            'https://snapinsta.app/action.php',
            data={'url': url, 'lang': 'en', 'q': url, 'token': token},
            headers={
                'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                'X-Requested-With': 'XMLHttpRequest',
                'Referer': 'https://snapinsta.app/',
                'Origin': 'https://snapinsta.app',
            },
            timeout=20,
        )
        if resp.status_code != 200:
            return False
        ct = resp.headers.get('Content-Type', '')
        data = resp.json() if 'json' in ct else {}
        html_content = data.get('data') or resp.text
        video_urls = re.findall(
            r'https://[^\s"\'<>]*(?:cdninstagram|fbcdn)[^\s"\'<>]*\.mp4[^\s"\'<>]*',
            html_content,
        )
        return len(video_urls) > 0
    except Exception:
        return False


def _try_embed_page(url):
    """
    Check if the embed page reveals a video (public post detection).
    Returns True if a video URL is found in the embed HTML.
    """
    shortcode = _get_shortcode(url)
    if not shortcode:
        return False

    embed_urls = [
        f'https://www.instagram.com/p/{shortcode}/embed/captioned/',
        f'https://www.instagram.com/p/{shortcode}/embed/',
        f'https://www.instagram.com/reel/{shortcode}/embed/',
    ]

    for embed_url in embed_urls:
        for ua in (_UA_MOBILE, _UA_DESKTOP):
            try:
                headers = {
                    'User-Agent': ua,
                    'Accept': 'text/html,application/xhtml+xml,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Referer': 'https://www.instagram.com/',
                }
                resp = _requests.get(embed_url, headers=headers, timeout=15)
                if resp.status_code not in (200, 304):
                    continue
                html = resp.text
                patterns = [
                    r'data-video-url="([^"]+)"',
                    r'"videoUrl"\s*:\s*"([^"]+)"',
                    r'"video_url"\s*:\s*"([^"]+)"',
                    r'<video[^>]+src="([^"]+)"',
                ]
                for pat in patterns:
                    for vu in re.findall(pat, html):
                        vu = vu.replace('\\/', '/').replace('&amp;', '&')
                        if vu.startswith('http') and ('cdninstagram' in vu or 'fbcdn' in vu):
                            return True
            except Exception:
                continue
    return False


def extract_instagram(url, cookie_file=None):
    """
    Extract Instagram video. Returns ONE download link pointing to the original URL.
    The proxy re-extracts a fresh CDN URL at download time (avoids expiry on Vercel).
    """

    def _success(title=''):
        return {
            'success': True,
            'title': title or 'Instagram Video',
            'thumbnail': '',
            'platform': 'instagram',
            'links': [
                {
                    'url': url,
                    'quality': 'Best Quality',
                    'format': 'mp4',
                    'size': '',
                    'format_id': _FORMAT,
                }
            ],
        }

    # Strategy 1: yt-dlp without cookies (works for many public posts)
    result = _try_ytdlp(url, cookie_file=None)
    if result is not None:
        title, thumbnail = result
        resp = _success(title)
        resp['thumbnail'] = thumbnail
        return resp

    # Strategy 2: yt-dlp with cookies (if cookie file exists)
    if cookie_file and os.path.exists(cookie_file):
        result = _try_ytdlp(url, cookie_file=cookie_file)
        if result is not None:
            title, thumbnail = result
            resp = _success(title)
            resp['thumbnail'] = thumbnail
            return resp

    # Strategy 3: snapinsta.app confirms video exists
    if _try_snapinsta(url):
        return _success()

    # Strategy 4: embed page confirms video exists
    if _try_embed_page(url):
        return _success()

    return {
        'success': False,
        'error': (
            'Could not extract this Instagram video. '
            'The post may be private or require login. '
            'Add a cookies/instagram.txt file (Netscape format) to enable private post downloads.'
        ),
    }
