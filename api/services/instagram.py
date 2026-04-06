"""
Instagram download service.

Strategy order (cookie-first):
1. yt-dlp with cookies (primary — supports Reels + Posts, retried 3 times)
2. snapinsta.app  (public scraper fallback)
3. sssinstagram.com (public scraper fallback)
4. Instagram embed page scraping
5. yt-dlp without cookies (last resort)

All returned URLs are validated (HEAD: status=200, Content-Length>0).
Only verified working links are returned.
"""

import os
import re
import time
import requests as _requests
import yt_dlp
from concurrent.futures import ThreadPoolExecutor, as_completed

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

_MAX_YTDLP_RETRIES = 3


def _format_size(filesize):
    if not filesize:
        return ''
    mb = filesize / (1024 * 1024)
    return f"{mb:.1f} MB" if mb >= 1 else f"{filesize / 1024:.0f} KB"


def _get_shortcode(url):
    m = re.search(r'/(?:p|reel|tv|videos)/([A-Za-z0-9_-]+)', url)
    return m.group(1) if m else None


# ── URL validation ────────────────────────────────────────────────────────────

def _validate_url(url, timeout=5):
    """Return True if URL returns HTTP 200/206 with content (short timeout for serverless)."""
    headers = {'User-Agent': _UA_DESKTOP}
    try:
        r = _requests.head(url, headers=headers, timeout=timeout, allow_redirects=True)
        if r.status_code == 200:
            return int(r.headers.get('Content-Length', 0) or 0) > 0
        if r.status_code in (403, 405, 501):
            headers2 = {**headers, 'Range': 'bytes=0-0'}
            r2 = _requests.get(url, headers=headers2, timeout=timeout,
                               stream=True, allow_redirects=True)
            ok = r2.status_code in (200, 206)
            r2.close()
            return ok
    except Exception:
        pass
    return False


def _validate_links(links, max_workers=6):
    """Run parallel URL validation; return only links that pass."""
    if not links:
        return []
    results = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_validate_url, lnk['url']): i for i, lnk in enumerate(links)}
        for future in as_completed(futures):
            idx = futures[future]
            try:
                results[idx] = future.result()
            except Exception:
                results[idx] = False
    return [links[i] for i in sorted(results) if results[i]]


# ── Strategy 1: yt-dlp (primary, with cookies) ───────────────────────────────

def _ytdlp_links_from_info(info):
    """Parse yt-dlp info dict into link list."""
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


def _try_ytdlp(url, cookie_file=None):
    """
    yt-dlp extraction with retry (up to _MAX_YTDLP_RETRIES).
    Returns validated links only.
    """
    ua_list = [_UA_MOBILE, _UA_DESKTOP]

    base_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'noplaylist': True,
        'socket_timeout': 30,
        'extractor_retries': 3,
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[ext=mp4]/best',
    }
    if cookie_file and os.path.exists(cookie_file):
        base_opts['cookiefile'] = cookie_file

    for attempt in range(1, _MAX_YTDLP_RETRIES + 1):
        for ua in ua_list:
            try:
                opts = {**base_opts, 'http_headers': {'User-Agent': ua}}
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    if not info:
                        continue
                    candidates = _ytdlp_links_from_info(info)
                    if candidates:
                        valid = _validate_links(candidates)
                        if valid:
                            return valid, info.get('title', ''), info.get('thumbnail', '')
            except Exception:
                pass

        if attempt < _MAX_YTDLP_RETRIES:
            time.sleep(1)

    return [], '', ''


# ── Strategy 2: snapinsta.app ─────────────────────────────────────────────────

def _try_snapinsta(url):
    try:
        session = _requests.Session()
        session.headers.update({'User-Agent': _UA_DESKTOP})
        home = session.get('https://snapinsta.app/', timeout=15)
        if home.status_code != 200:
            return []
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
            return []
        ct = resp.headers.get('Content-Type', '')
        data = resp.json() if 'json' in ct else {}
        html_content = data.get('data') or resp.text

        links = []
        seen = set()
        video_urls = re.findall(
            r'https://[^\s"\'<>]*(?:cdninstagram|fbcdn)[^\s"\'<>]*\.mp4[^\s"\'<>]*',
            html_content,
        )
        for vu in video_urls:
            vu = vu.replace('&amp;', '&').replace('\\/', '/').rstrip('"\'')
            if vu not in seen and vu.startswith('http'):
                seen.add(vu)
                hm = re.search(r'(\d{3,4})p', vu)
                quality = f'{hm.group(1)}p' if hm else 'Best Quality'
                links.append({'url': vu, 'quality': quality, 'format': 'mp4', 'size': ''})
        return links[:4]
    except Exception:
        return []


# ── Strategy 3: sssinstagram.com ─────────────────────────────────────────────

def _try_sssinstagram(url):
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


# ── Strategy 4: Instagram embed page ─────────────────────────────────────────

def _try_embed_page(url):
    shortcode = _get_shortcode(url)
    if not shortcode:
        return []

    embed_urls = [
        f'https://www.instagram.com/p/{shortcode}/embed/captioned/',
        f'https://www.instagram.com/p/{shortcode}/embed/',
        f'https://www.instagram.com/reel/{shortcode}/embed/',
    ]
    links = []
    seen = set()

    for embed_url in embed_urls:
        for ua in (_UA_MOBILE, _UA_DESKTOP):
            try:
                headers = {
                    'User-Agent': ua,
                    'Accept': 'text/html,application/xhtml+xml,*/*;q=0.8',
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
                                .replace('&amp;', '&'))
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


# ── Main entry point ──────────────────────────────────────────────────────────

def extract_instagram(url, cookie_file=None):
    """
    Extract Instagram video/reel. Returns only validated working links.
    Strategy order: yt-dlp (with cookies) -> snapinsta -> sssinstagram -> embed page -> yt-dlp (no cookies)
    """

    # Strategy 1: yt-dlp with cookies (primary)
    valid, title, thumb = _try_ytdlp(url, cookie_file)
    if valid:
        return {
            'success': True,
            'title': title or 'Instagram Video',
            'thumbnail': thumb,
            'links': valid,
            'platform': 'instagram',
        }

    # Strategy 2: snapinsta.app
    candidates = _try_snapinsta(url)
    if candidates:
        valid = _validate_links(candidates)
        if valid:
            return {
                'success': True,
                'title': 'Instagram Video',
                'thumbnail': '',
                'links': valid,
                'platform': 'instagram',
            }

    # Strategy 3: sssinstagram.com
    candidates = _try_sssinstagram(url)
    if candidates:
        valid = _validate_links(candidates)
        if valid:
            return {
                'success': True,
                'title': 'Instagram Video',
                'thumbnail': '',
                'links': valid,
                'platform': 'instagram',
            }

    # Strategy 4: embed page scraping
    candidates = _try_embed_page(url)
    if candidates:
        valid = _validate_links(candidates)
        if valid:
            return {
                'success': True,
                'title': 'Instagram Video',
                'thumbnail': '',
                'links': valid,
                'platform': 'instagram',
            }

    # Strategy 5: yt-dlp without cookies (last resort, no validation retry)
    valid, title, thumb = _try_ytdlp(url, cookie_file=None)
    if valid:
        return {
            'success': True,
            'title': title or 'Instagram Video',
            'thumbnail': thumb,
            'links': valid,
            'platform': 'instagram',
        }

    return {
        'success': False,
        'error': (
            'No valid download links found. '
            'The post may be private, or Instagram is blocking server access. '
            'Add a cookies/instagram.txt file (Netscape format) to enable downloads.'
        ),
    }
