"""
Instagram download service.

Strategy:
1. snapinsta.app scraper — returns actual CDN URLs (no login needed)
2. instasave.io API fallback
3. yt-dlp without cookies (fastest, works for some public posts)
4. yt-dlp with cookies (if cookies/instagram.txt exists)
5. Instagram embed page scraping

The returned link URL is a direct CDN URL so the proxy can stream it
without re-running yt-dlp (which requires login and is blocked by Instagram).
"""

import os
import re
import time
import json
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
_MAX_RETRIES = 2

_CDN_RE = re.compile(
    r'https://[^\s"\'<>&]+(?:cdninstagram\.com|fbcdn\.net)[^\s"\'<>&]*\.mp4[^\s"\'<>&]*'
)


def _get_shortcode(url):
    m = re.search(r'/(?:p|reel|tv|videos)/([A-Za-z0-9_-]+)', url)
    return m.group(1) if m else None


# ── Strategy 1: snapinsta.app ────────────────────────────────────────────────

def _try_snapinsta(url):
    """
    Scrape snapinsta.app to get direct CDN video URLs.
    Returns a list of {'url': cdn_url, 'quality': ..., 'format': 'mp4', 'size': ''}
    """
    try:
        session = _requests.Session()
        session.headers.update({
            'User-Agent': _UA_DESKTOP,
            'Accept-Language': 'en-US,en;q=0.9',
        })

        # Get CSRF token
        home = session.get('https://snapinsta.app/', timeout=15)
        if home.status_code != 200:
            return []

        token_m = re.search(r'name="_token"\s+value="([^"]+)"', home.text)
        if not token_m:
            token_m = re.search(r'"_token"\s*:\s*"([^"]+)"', home.text)
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
            return []

        ct = resp.headers.get('Content-Type', '')
        if 'json' in ct:
            try:
                data = resp.json()
                html_content = data.get('data', '') or ''
            except Exception:
                html_content = resp.text
        else:
            html_content = resp.text

        # Unescape HTML entities and unicode escapes
        html_content = (html_content
                        .replace('\\u0026', '&')
                        .replace('\\/', '/')
                        .replace('&amp;', '&')
                        .replace('%2F', '/'))

        cdn_urls = _CDN_RE.findall(html_content)

        # Also look for href attributes containing CDN URLs
        href_matches = re.findall(
            r'href=["\']([^"\']*(?:cdninstagram\.com|fbcdn\.net)[^"\']*\.mp4[^"\']*)["\']',
            html_content,
        )
        cdn_urls.extend(href_matches)

        seen = set()
        links = []
        for u in cdn_urls:
            u = u.strip().rstrip('\\').rstrip('"').rstrip("'")
            if u in seen or not u.startswith('http'):
                continue
            seen.add(u)
            links.append({
                'url': u,
                'quality': 'Best Quality',
                'format': 'mp4',
                'size': '',
            })

        return links[:3]

    except Exception:
        return []


# ── Strategy 2: instasave.io ─────────────────────────────────────────────────

def _try_instasave(url):
    """
    Try instasave.io as a fallback scraper.
    Returns a list of CDN link dicts.
    """
    try:
        session = _requests.Session()
        session.headers.update({'User-Agent': _UA_DESKTOP})

        home = session.get('https://instasave.io/', timeout=15)
        if home.status_code != 200:
            return []

        token_m = re.search(r'name="_token"\s+value="([^"]+)"', home.text)
        token = token_m.group(1) if token_m else ''

        resp = session.post(
            'https://instasave.io/download',
            data={'url': url, '_token': token},
            headers={
                'Content-Type': 'application/x-www-form-urlencoded',
                'Referer': 'https://instasave.io/',
                'Origin': 'https://instasave.io',
            },
            timeout=20,
        )

        if resp.status_code != 200:
            return []

        html_content = resp.text.replace('\\/', '/').replace('&amp;', '&')
        cdn_urls = _CDN_RE.findall(html_content)

        seen = set()
        links = []
        for u in cdn_urls:
            u = u.strip()
            if u in seen or not u.startswith('http'):
                continue
            seen.add(u)
            links.append({'url': u, 'quality': 'Best Quality', 'format': 'mp4', 'size': ''})

        return links[:3]

    except Exception:
        return []


# ── Strategy 3: yt-dlp ───────────────────────────────────────────────────────

def _try_ytdlp(url, cookie_file=None):
    """
    Try yt-dlp extraction. Returns (title, thumbnail, cdn_url) on success, or None.
    """
    base_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'noplaylist': True,
        'socket_timeout': 30,
        'extractor_retries': 2,
        'format': _FORMAT,
    }
    if cookie_file and os.path.exists(cookie_file):
        base_opts['cookiefile'] = cookie_file

    for ua in [_UA_MOBILE, _UA_DESKTOP]:
        try:
            opts = {**base_opts, 'http_headers': {'User-Agent': ua}}
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if not info:
                    continue
                title = info.get('title', '') or ''
                thumbnail = info.get('thumbnail', '') or ''

                # Try to get a direct CDN URL
                cdn_url = None
                for f in (info.get('formats') or []):
                    fu = f.get('url', '')
                    if fu and ('cdninstagram' in fu or 'fbcdn' in fu) and fu.startswith('http'):
                        cdn_url = fu
                        break
                if not cdn_url:
                    fu = info.get('url', '')
                    if fu and ('cdninstagram' in fu or 'fbcdn' in fu):
                        cdn_url = fu

                if cdn_url:
                    return title, thumbnail, cdn_url
                elif title:
                    return title, thumbnail, None
        except Exception:
            pass

    return None


# ── Strategy 4: embed page ───────────────────────────────────────────────────

def _try_embed_page(url):
    """
    Scrape the Instagram embed page for CDN video URLs.
    Returns list of link dicts or empty list.
    """
    shortcode = _get_shortcode(url)
    if not shortcode:
        return []

    embed_urls = [
        f'https://www.instagram.com/p/{shortcode}/embed/captioned/',
        f'https://www.instagram.com/p/{shortcode}/embed/',
        f'https://www.instagram.com/reel/{shortcode}/embed/',
    ]

    patterns = [
        r'data-video-url="([^"]+)"',
        r'"videoUrl"\s*:\s*"([^"]+)"',
        r'"video_url"\s*:\s*"([^"]+)"',
        r'<video[^>]+src="([^"]+)"',
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

                links = []
                seen = set()
                for pat in patterns:
                    for vu in re.findall(pat, html):
                        vu = (vu.replace('\\/', '/')
                                .replace('&amp;', '&')
                                .replace('\\u0026', '&'))
                        if vu.startswith('http') and ('cdninstagram' in vu or 'fbcdn' in vu):
                            if vu not in seen:
                                seen.add(vu)
                                links.append({
                                    'url': vu,
                                    'quality': 'Best Quality',
                                    'format': 'mp4',
                                    'size': '',
                                })

                if links:
                    return links[:2]

            except Exception:
                continue

    return []


# ── Main extractor ────────────────────────────────────────────────────────────

def extract_instagram(url, cookie_file=None):
    """
    Extract Instagram video. Tries multiple strategies to get direct CDN URLs
    so the proxy can stream without re-running yt-dlp.
    """

    def _success(links, title='', thumbnail=''):
        return {
            'success': True,
            'title': title or 'Instagram Video',
            'thumbnail': thumbnail or '',
            'platform': 'instagram',
            'links': links,
        }

    # Strategy 1: snapinsta (most reliable for public posts)
    links = _try_snapinsta(url)
    if links:
        return _success(links)

    # Strategy 2: instasave.io fallback
    links = _try_instasave(url)
    if links:
        return _success(links)

    # Strategy 3: yt-dlp (direct CDN URL extraction)
    result = _try_ytdlp(url, cookie_file=None)
    if result is not None:
        title, thumbnail, cdn_url = result
        if cdn_url:
            return _success(
                [{'url': cdn_url, 'quality': 'Best Quality', 'format': 'mp4', 'size': ''}],
                title, thumbnail,
            )

    # Strategy 4: yt-dlp with cookies
    if cookie_file and os.path.exists(cookie_file):
        result = _try_ytdlp(url, cookie_file=cookie_file)
        if result is not None:
            title, thumbnail, cdn_url = result
            if cdn_url:
                return _success(
                    [{'url': cdn_url, 'quality': 'Best Quality', 'format': 'mp4', 'size': ''}],
                    title, thumbnail,
                )

    # Strategy 5: embed page scraping
    links = _try_embed_page(url)
    if links:
        return _success(links)

    return {
        'success': False,
        'error': (
            'Could not extract this Instagram video. '
            'The post may be private or require login. '
            'Try refreshing or add a cookies/instagram.txt file (Netscape format) to enable private post downloads.'
        ),
    }
