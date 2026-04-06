"""
Instagram download service — multi-strategy extractor.

Strategy order:
1. snapinsta.app / ssinstagram.com — public web scrapers that work without cookies
2. Instagram embed page scraping (improved patterns, with retry)
3. yt-dlp with cookies (requires instagram.txt in cookies/)
4. yt-dlp without cookies as final fallback

Fixes:
- Instagram embed pages now require login for most content; added external scrapers
- Improved regex patterns to catch current embed HTML structure
- Added retry with different UAs before falling through to yt-dlp
"""

import re
import json
import time
import urllib.parse
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


def _format_size(filesize):
    if not filesize:
        return ''
    mb = filesize / (1024 * 1024)
    return f"{mb:.1f} MB" if mb >= 1 else f"{filesize / 1024:.0f} KB"


def _get_shortcode(url):
    m = re.search(r'/(?:p|reel|tv|videos)/([A-Za-z0-9_-]+)', url)
    return m.group(1) if m else None


# ── Strategy 1: snapinsta.app ────────────────────────────────────────────────
def _try_snapinsta(url):
    """Use snapinsta.app as a free public extractor."""
    try:
        session = _requests.Session()
        session.headers.update({
            'User-Agent': _UA_DESKTOP,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        })

        # Get the home page to pick up cookies + token
        home = session.get('https://snapinsta.app/', timeout=15)
        if home.status_code != 200:
            return []

        # Extract CSRF / hidden token
        token_m = re.search(r'name="_token"\s+value="([^"]+)"', home.text)
        if not token_m:
            # Try alternative token patterns
            token_m = re.search(r'"token"\s*:\s*"([^"]+)"', home.text)
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

        data = resp.json() if resp.headers.get('Content-Type', '').startswith('application/json') else {}
        html_content = data.get('data') or resp.text

        links = []
        seen = set()

        # Video URLs in response
        video_urls = re.findall(
            r'https://[^\s"\'<>]*(?:cdninstagram|fbcdn)[^\s"\'<>]*\.mp4[^\s"\'<>]*',
            html_content
        )
        for vu in video_urls:
            vu = vu.replace('&amp;', '&').replace('\\/', '/').rstrip('"\'')
            if vu not in seen and vu.startswith('http'):
                seen.add(vu)
                h_m = re.search(r'(\d{3,4})p', vu)
                quality = f'{h_m.group(1)}p' if h_m else 'Best Quality'
                links.append({'url': vu, 'quality': quality, 'format': 'mp4', 'size': ''})

        return links[:4]
    except Exception:
        return []


# ── Strategy 2: sssinstagram.com ────────────────────────────────────────────
def _try_sssinstagram(url):
    """Use sssinstagram.com as fallback extractor."""
    try:
        session = _requests.Session()
        session.headers.update({'User-Agent': _UA_DESKTOP})

        home = session.get('https://sssinstagram.com/', timeout=15)
        token_m = re.search(r'name="_token"\s+value="([^"]+)"', home.text)
        token = token_m.group(1) if token_m else ''

        resp = session.post(
            'https://sssinstagram.com/request',
            data={'url': url, '_token': token},
            headers={
                'Referer': 'https://sssinstagram.com/',
                'Origin': 'https://sssinstagram.com',
                'X-Requested-With': 'XMLHttpRequest',
                'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            },
            timeout=20,
        )
        if resp.status_code != 200:
            return []

        try:
            data = resp.json()
        except Exception:
            return []

        links = []
        seen = set()

        # Parse response structure
        items = data.get('items', []) or data.get('data', {}).get('items', [])
        for item in items:
            resources = item.get('resources', []) or [item]
            for res in resources:
                dl_url = res.get('url') or res.get('download_url')
                if dl_url and dl_url not in seen and 'mp4' in dl_url.lower():
                    seen.add(dl_url)
                    quality = res.get('quality') or res.get('resolution') or 'Best Quality'
                    links.append({'url': dl_url, 'quality': str(quality), 'format': 'mp4', 'size': ''})

        return links[:4]
    except Exception:
        return []


# ── Strategy 2b: saveinsta.app ───────────────────────────────────────────────
def _try_saveinsta(url):
    """Use saveinsta.app as another free extractor option."""
    try:
        session = _requests.Session()
        session.headers.update({
            'User-Agent': _UA_DESKTOP,
            'Accept': 'text/html,application/xhtml+xml,*/*;q=0.8',
        })
        home = session.get('https://saveinsta.app/', timeout=15)
        token_m = re.search(r'name="_token"\s+value="([^"]+)"', home.text)
        token = token_m.group(1) if token_m else ''

        resp = session.post(
            'https://saveinsta.app/action.php',
            data={'url': url, 'lang': 'en', 'q': url, 'token': token},
            headers={
                'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                'X-Requested-With': 'XMLHttpRequest',
                'Referer': 'https://saveinsta.app/',
                'Origin': 'https://saveinsta.app',
            },
            timeout=20,
        )
        if resp.status_code != 200:
            return []

        # Parse HTML response for download links
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, 'html.parser')
        links = []
        seen = set()

        # Look for download links
        for a in soup.find_all('a', href=True):
            href = a.get('href', '')
            if ('cdninstagram' in href or 'fbcdn' in href) and href not in seen:
                seen.add(href)
                text = a.get_text().strip()
                quality = text if text else 'Best Quality'
                links.append({'url': href, 'quality': quality, 'format': 'mp4', 'size': ''})

        # Also look for video URLs in the raw HTML
        video_urls = re.findall(
            r'https://[^\s"\'<>]*(?:cdninstagram|fbcdn)[^\s"\'<>]*\.mp4[^\s"\'<>]*',
            resp.text
        )
        for vu in video_urls:
            vu = vu.replace('&amp;', '&').rstrip('"\'')
            if vu not in seen:
                seen.add(vu)
                links.append({'url': vu, 'quality': 'Best Quality', 'format': 'mp4', 'size': ''})

        return links[:4]
    except Exception:
        return []


# ── Strategy 3: Instagram embed page (improved) ──────────────────────────────
def _try_embed_page(url):
    """Scrape Instagram embed page for video URLs."""
    shortcode = _get_shortcode(url)
    if not shortcode:
        return []

    links = []
    seen = set()

    embed_urls = [
        f'https://www.instagram.com/p/{shortcode}/embed/captioned/',
        f'https://www.instagram.com/p/{shortcode}/embed/',
        f'https://www.instagram.com/reel/{shortcode}/embed/',
    ]

    for embed_url in embed_urls:
        for ua in [_UA_MOBILE, _UA_DESKTOP]:
            try:
                headers = {
                    'User-Agent': ua,
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Referer': 'https://www.instagram.com/',
                    'Sec-Fetch-Mode': 'navigate',
                    'Sec-Fetch-Dest': 'iframe',
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
                    r'"src"\s*:\s*"(https://[^"]*(?:cdninstagram|fbcdn)[^"]*\.mp4[^"]*)"',
                    r'\\u0022src\\u0022:\\u0022(https://[^\\]+\.mp4[^\\]*)',
                ]
                for pat in patterns:
                    for vu in re.findall(pat, html):
                        vu = (vu.replace('\\u0026', '&')
                                .replace('\\/', '/')
                                .replace('&amp;', '&')
                                .replace('\\u003C', '<'))
                        if (vu.startswith('http') and vu not in seen and
                                ('cdninstagram' in vu or 'fbcdn' in vu or '.mp4' in vu)):
                            seen.add(vu)
                            hm = re.search(r'(\d{3,4})p', vu)
                            quality = f'{hm.group(1)}p' if hm else 'Best Quality'
                            links.append({'url': vu, 'quality': quality, 'format': 'mp4', 'size': ''})

                if links:
                    return links[:4]
            except Exception:
                continue

    return links


# ── Strategy 4: yt-dlp ───────────────────────────────────────────────────────
def _try_ytdlp(url, cookie_file=None):
    """Use yt-dlp to extract Instagram video. Requires cookies for most content."""
    retry_sets = [
        {
            'http_headers': {'User-Agent': _UA_MOBILE},
        },
        {
            'http_headers': {'User-Agent': _UA_DESKTOP},
        },
        {
            'http_headers': {'User-Agent': _UA_MOBILE},
            'extractor_args': {'instagram': {'api': ['1']}},
        },
    ]

    base_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'noplaylist': True,
        'socket_timeout': 30,
        'extractor_retries': 3,
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[ext=mp4]/best',
    }
    if cookie_file:
        base_opts['cookiefile'] = cookie_file

    info = None
    for retry_set in retry_sets:
        try:
            opts = {**base_opts, **retry_set}
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if info:
                    break
        except Exception:
            continue

    if not info:
        return []

    links = []
    seen = set()
    formats = info.get('formats', [])

    for f in formats:
        f_url = f.get('url')
        if not f_url or f_url in seen:
            continue
        protocol = f.get('protocol', '')
        if protocol in ('m3u8', 'm3u8_native', 'http_dash_segments'):
            continue
        vcodec = f.get('vcodec', 'none')
        acodec = f.get('acodec', 'none')
        has_video = vcodec not in ('none', None)
        has_audio = acodec not in ('none', None)
        if not (has_video and has_audio):
            continue
        height = f.get('height')
        seen.add(f_url)
        label = f"{height}p" if height else f.get('format_note') or 'Best Quality'
        links.append({
            'url': f_url,
            'quality': label,
            'format': f.get('ext', 'mp4'),
            'size': _format_size(f.get('filesize') or f.get('filesize_approx')),
        })

    if not links and info.get('url'):
        h = info.get('height')
        links.append({
            'url': info['url'],
            'quality': f"{h}p" if h else 'Best Quality',
            'format': info.get('ext', 'mp4'),
            'size': _format_size(info.get('filesize') or info.get('filesize_approx')),
        })

    return links[:4]


def extract_instagram(url, cookie_file=None):
    """
    Main Instagram extractor. Tries 4 strategies in order.
    Returns dict with success/links/title/thumbnail.
    """
    # Strategy 1: snapinsta.app
    links = _try_snapinsta(url)
    if links:
        return {
            'success': True,
            'title': 'Instagram Video',
            'thumbnail': '',
            'links': links,
            'platform': 'instagram',
        }

    # Strategy 2: sssinstagram.com
    links = _try_sssinstagram(url)
    if links:
        return {
            'success': True,
            'title': 'Instagram Video',
            'thumbnail': '',
            'links': links,
            'platform': 'instagram',
        }

    # Strategy 2b: saveinsta.app
    links = _try_saveinsta(url)
    if links:
        return {
            'success': True,
            'title': 'Instagram Video',
            'thumbnail': '',
            'links': links,
            'platform': 'instagram',
        }

    # Strategy 3: embed page scraping
    links = _try_embed_page(url)
    if links:
        return {
            'success': True,
            'title': 'Instagram Video',
            'thumbnail': '',
            'links': links,
            'platform': 'instagram',
        }

    # Strategy 4: yt-dlp
    links = _try_ytdlp(url, cookie_file)
    if links:
        return {
            'success': True,
            'title': 'Instagram Video',
            'thumbnail': '',
            'links': links,
            'platform': 'instagram',
        }

    return {
        'success': False,
        'error': (
            'Could not extract Instagram video. '
            'The post may be private or Instagram has updated their restrictions.'
        ),
    }
