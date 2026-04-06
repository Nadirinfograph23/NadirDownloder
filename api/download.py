"""
NADIR DOWNLOADER - Video Download API
Uses direct page scraping (Facebook, Pinterest) and yt-dlp (other platforms)
to extract video download links from social media platforms.

Radical resilience strategy
────────────────────────────
1. Cookie files  — place Netscape-format cookies in  cookies/<platform>.txt
                   (instagram.txt, tiktok.txt, twitter.txt, youtube.txt, facebook.txt)
2. Per-platform service modules for YouTube, Instagram, Pinterest with
   multi-strategy retry chains (see api/services/).
3. yt-dlp is auto-updated on server startup so extractors stay current.
"""

from http.server import BaseHTTPRequestHandler
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import re
import sys
import urllib.parse
import yt_dlp
import requests as _requests
from bs4 import BeautifulSoup as _BS

# Import dedicated service modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from services.youtube import extract_youtube
from services.instagram import extract_instagram
from services.pinterest import extract_pinterest

# ── Cookie-file support ───────────────────────────────────────────────────────
_COOKIE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'cookies')

def _cookie_file(platform: str):
    path = os.path.join(_COOKIE_DIR, f'{platform}.txt')
    return path if os.path.isfile(path) else None


def detect_platform(url):
    normalized = url.lower()
    if re.search(r'facebook\.com|fb\.com|fb\.watch|fbcdn\.net', normalized):
        return 'facebook'
    if re.search(r'tiktok\.com|vm\.tiktok\.com', normalized):
        return 'tiktok'
    if re.search(r'youtube\.com|youtu\.be|yt\.be', normalized):
        return 'youtube'
    if re.search(r'instagram\.com|instagr\.am', normalized):
        return 'instagram'
    if re.search(r'pinterest\.com|pin\.it', normalized):
        return 'pinterest'
    if re.search(r'twitter\.com|x\.com|t\.co', normalized):
        return 'twitter'
    return None


def _format_size(filesize):
    if not filesize:
        return ''
    size_mb = filesize / (1024 * 1024)
    if size_mb >= 1:
        return f"{size_mb:.1f} MB"
    size_kb = filesize / 1024
    return f"{size_kb:.0f} KB"


_BROWSER_UA = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/124.0.0.0 Safari/537.36'
)

_PLATFORM_TEST_HEADERS = {
    'facebook':  {'User-Agent': _BROWSER_UA, 'Referer': 'https://www.facebook.com/'},
    'instagram': {'User-Agent': _BROWSER_UA, 'Referer': 'https://www.instagram.com/'},
    'pinterest': {'User-Agent': _BROWSER_UA, 'Referer': 'https://www.pinterest.com/'},
    'twitter':   {'User-Agent': _BROWSER_UA, 'Referer': 'https://twitter.com/'},
    'youtube':   {'User-Agent': _BROWSER_UA},
}


def _test_url(url, headers=None, timeout=5):
    try:
        r = _requests.head(
            url,
            headers=headers or {'User-Agent': _BROWSER_UA},
            timeout=timeout,
            allow_redirects=True,
        )
        if r.status_code >= 400:
            return False
        ct = r.headers.get('Content-Type', '').lower()
        if 'xml' in ct or 'html' in ct:
            return False
        return True
    except Exception:
        return True


def _filter_working_links(links, platform):
    if platform == 'tiktok' or not links:
        return links

    headers = _PLATFORM_TEST_HEADERS.get(platform, {'User-Agent': _BROWSER_UA})

    def _check(link):
        return _test_url(link['url'], headers), link

    with ThreadPoolExecutor(max_workers=min(6, len(links))) as ex:
        results = list(ex.map(_check, links))

    working = [link for ok, link in results if ok]
    return working if working else links


# ─────────────────────────────────────────────────────────────────────────────
# Pinterest Scraper — direct page extraction (primary method)
# ─────────────────────────────────────────────────────────────────────────────
def _resolve_pinterest_url(url):
    if 'pin.it' not in url.lower():
        return url
    try:
        r = _requests.get(
            url,
            headers={'User-Agent': _BROWSER_UA, 'Accept': 'text/html'},
            timeout=12,
            allow_redirects=True,
        )
        for resp in list(r.history) + [r]:
            m = re.search(r'/pin/(\d+)/', resp.url)
            if m:
                return f'https://www.pinterest.com/pin/{m.group(1)}/'
    except Exception:
        pass
    return url


def _extract_pin_id(url):
    m = re.search(r'/pin/(\d+)', url)
    return m.group(1) if m else None


def _fetch_pinterest_video(url):
    """
    Multi-strategy Pinterest video extractor.

    Strategy 1: Pinterest internal API (v3/pins endpoint) — fastest, most reliable.
    Strategy 2: Scrape the page HTML and extract pinimg.com mp4 / m3u8 URLs.
    Strategy 3: savepin.app fallback.
    """
    url = _resolve_pinterest_url(url)
    pin_id = _extract_pin_id(url)

    # ── Strategy 1: Pinterest v3 API ────────────────────────────────────────
    if pin_id:
        links = _pinterest_api_v3(pin_id)
        if links:
            return links

    # ── Strategy 2: Direct page scraping ────────────────────────────────────
    links = _pinterest_page_scrape(url)
    if links:
        return links

    # ── Strategy 3: savepin.app ──────────────────────────────────────────────
    return _fetch_pinterest_savepin(url)


def _pinterest_api_v3(pin_id):
    """Use Pinterest's internal JSON API to get video URLs."""
    endpoints = [
        f'https://www.pinterest.com/resource/PinResource/get/?source_url=/pin/{pin_id}/&data={{"options":{{"id":"{pin_id}","field_set_key":"detailed"}}}}',
        f'https://www.pinterest.com/resource/VideoResource/get/?source_url=/pin/{pin_id}/&data={{"options":{{"id":"{pin_id}"}}}}',
    ]

    headers = {
        'User-Agent': _BROWSER_UA,
        'Accept': 'application/json, text/javascript, */*; q=0.01',
        'X-Requested-With': 'XMLHttpRequest',
        'Referer': f'https://www.pinterest.com/pin/{pin_id}/',
    }

    for endpoint in endpoints:
        try:
            resp = _requests.get(endpoint, headers=headers, timeout=15)
            if resp.status_code != 200:
                continue
            data = resp.json()
            links = _parse_pinterest_api_response(data)
            if links:
                return links
        except Exception:
            continue
    return []


def _parse_pinterest_api_response(data):
    """Recursively search Pinterest API JSON for video URLs."""
    links = []
    text = json.dumps(data)

    # Extract direct pinimg mp4 URLs
    mp4_urls = re.findall(r'https://v\d+\.pinimg\.com/videos/[^"\'\\]+\.mp4', text)
    m3u8_urls = re.findall(r'https://v\d+\.pinimg\.com/videos/[^"\'\\]+\.m3u8', text)

    seen = set()

    for mp4_url in mp4_urls:
        mp4_url = mp4_url.replace('\\/', '/')
        if mp4_url in seen:
            continue
        seen.add(mp4_url)
        quality = '720p'
        if '1080p' in mp4_url:
            quality = '1080p'
        elif '480p' in mp4_url:
            quality = '480p'
        elif '360p' in mp4_url:
            quality = '360p'
        elif 'V_720P' in mp4_url or '720p' in mp4_url:
            quality = '720p'
        links.append({'url': mp4_url, 'quality': quality, 'format': 'mp4', 'size': ''})

    # Convert HLS manifest URLs to direct MP4
    for m3u8_url in m3u8_urls:
        m3u8_url = m3u8_url.replace('\\/', '/')
        mp4_url = _hls_to_direct_mp4(m3u8_url)
        if mp4_url and mp4_url not in seen:
            seen.add(mp4_url)
            quality = '720p'
            if '480p' in mp4_url:
                quality = '480p'
            links.append({'url': mp4_url, 'quality': quality, 'format': 'mp4', 'size': ''})

    return links


def _hls_to_direct_mp4(m3u8_url):
    """
    Pinterest HLS manifests follow this pattern:
      https://v1.pinimg.com/videos/iht/hls/<hash>_720w.m3u8
    The muxed MP4 is at:
      https://v1.pinimg.com/videos/mc/720p/<hash>.mp4
    """
    HLS_RE = re.compile(
        r'(https://[^/]*\.pinimg\.com)/videos/(?:[^/]+/)*hls/(.+?)(?:_\w+)?\.m3u8'
    )
    m = HLS_RE.match(m3u8_url)
    if not m:
        return None
    cdn_base = m.group(1)
    video_hash = m.group(2)
    # Remove trailing resolution suffix like _720w if still present
    video_hash = re.sub(r'_\d+w$', '', video_hash)
    return f'{cdn_base}/videos/mc/720p/{video_hash}.mp4'


def _pinterest_page_scrape(url):
    """Scrape the Pinterest page HTML and extract video URLs from embedded JS data."""
    headers = {
        'User-Agent': _BROWSER_UA,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Referer': 'https://www.pinterest.com/',
    }
    try:
        resp = _requests.get(url, headers=headers, timeout=15, allow_redirects=True)
        if resp.status_code != 200:
            return []

        html = resp.text
        links = []
        seen = set()

        # Look for pinimg.com video URLs directly in the page
        mp4_urls = re.findall(r'https://v\d+\.pinimg\.com/videos/[^"\'\\&\s]+\.mp4', html)
        m3u8_urls = re.findall(r'https://v\d+\.pinimg\.com/videos/[^"\'\\&\s]+\.m3u8', html)

        for mp4_url in mp4_urls:
            mp4_url = mp4_url.replace('\\u002F', '/').replace('\\/', '/')
            if mp4_url in seen:
                continue
            seen.add(mp4_url)
            quality = 'HD'
            for q in ['1080p', '720p', '480p', '360p']:
                if q in mp4_url:
                    quality = q
                    break
            links.append({'url': mp4_url, 'quality': quality, 'format': 'mp4', 'size': ''})

        for m3u8_url in m3u8_urls:
            m3u8_url = m3u8_url.replace('\\u002F', '/').replace('\\/', '/')
            mp4_url = _hls_to_direct_mp4(m3u8_url)
            if mp4_url and mp4_url not in seen:
                seen.add(mp4_url)
                links.append({'url': mp4_url, 'quality': '720p', 'format': 'mp4', 'size': ''})

        # ── Extract from Next.js __NEXT_DATA__ embedded JSON ────────────────
        next_data_m = re.search(
            r'<script[^>]+id="__NEXT_DATA__"[^>]*>\s*(\{.*?\})\s*</script>',
            html, re.DOTALL
        )
        if next_data_m:
            try:
                next_json = json.loads(next_data_m.group(1))
                nd_links = _parse_pinterest_api_response(next_json)
                for l in nd_links:
                    if l['url'] not in seen:
                        seen.add(l['url'])
                        links.append(l)
            except Exception:
                pass

        # ── Extract from __PWS_INITIAL_PROPS__ or __PWS_DATA__ ───────────────
        for pws_pat in [
            r'__PWS_INITIAL_PROPS__\s*=\s*(\{.*?\})\s*;',
            r'__PWS_DATA__\s*=\s*(\{.*?\})\s*;',
            r'P\.start\.start\(\s*(\{.*?\})\s*\)',
        ]:
            pws_m = re.search(pws_pat, html, re.DOTALL)
            if pws_m:
                try:
                    pws_json = json.loads(pws_m.group(1))
                    pws_links = _parse_pinterest_api_response(pws_json)
                    for l in pws_links:
                        if l['url'] not in seen:
                            seen.add(l['url'])
                            links.append(l)
                except Exception:
                    pass

        # ── Also look inside all <script> tags for pinimg.com URLs ───────────
        soup = _BS(html, 'html.parser')
        for script in soup.find_all('script'):
            content = script.string or ''
            if 'pinimg.com' not in content:
                continue
            extra_mp4 = re.findall(r'https://v\d+\.pinimg\.com/videos/[^"\'\\&\s]+\.mp4', content)
            extra_m3u8 = re.findall(r'https://v\d+\.pinimg\.com/videos/[^"\'\\&\s]+\.m3u8', content)
            for u in extra_mp4:
                u = u.replace('\\/', '/')
                if u not in seen:
                    seen.add(u)
                    q = '720p'
                    for res in ['1080p', '720p', '480p', '360p']:
                        if res in u:
                            q = res
                            break
                    links.append({'url': u, 'quality': q, 'format': 'mp4', 'size': ''})
            for u in extra_m3u8:
                u = u.replace('\\/', '/')
                mp4_url = _hls_to_direct_mp4(u)
                if mp4_url and mp4_url not in seen:
                    seen.add(mp4_url)
                    links.append({'url': mp4_url, 'quality': '720p', 'format': 'mp4', 'size': ''})

        return links
    except Exception:
        return []


def _fetch_pinterest_savepin(url):
    """Fallback: extract Pinterest video via savepin.app."""
    encoded_url = urllib.parse.quote(url, safe='')
    api_url = (
        f'https://www.savepin.app/download.php'
        f'?url={encoded_url}&lang=en&type=redirect'
    )
    headers = {
        'User-Agent': _BROWSER_UA,
        'Accept': 'text/html,application/xhtml+xml,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Referer': 'https://www.savepin.app/',
    }

    try:
        resp = _requests.get(api_url, headers=headers, timeout=20, allow_redirects=True)
        soup = _BS(resp.text, 'html.parser')
        links = []
        _IMAGE_FMTS = {'jpg', 'jpeg', 'png', 'gif', 'webp', 'avif'}

        for row in soup.select('tbody tr'):
            tds = row.find_all('td')
            a_el = row.select_one('a[href]')
            if not a_el:
                continue
            href = a_el.get('href', '')
            parsed = urllib.parse.urlparse(href)
            qs = urllib.parse.parse_qs(parsed.query)
            direct_url = qs.get('url', [href])[0]
            quality_el = row.select_one('.video-quality')
            quality = (quality_el.text.strip() if quality_el
                       else (tds[0].text.strip() if tds else 'Unknown'))
            fmt = tds[1].text.strip().lower() if len(tds) > 1 else 'mp4'
            if fmt in _IMAGE_FMTS or quality.lower() in ('thumbnail', 'image'):
                continue
            if direct_url and direct_url.startswith('http'):
                links.append({
                    'url': direct_url,
                    'quality': quality,
                    'format': fmt or 'mp4',
                    'size': '',
                })
        return links[:4]
    except Exception:
        return []


# ─────────────────────────────────────────────────────────────────────────────
# Instagram Scraper — embed page extraction (public content, no login needed)
# ─────────────────────────────────────────────────────────────────────────────
def _fetch_instagram_video(url):
    """
    Multi-strategy Instagram video extractor for public posts (no cookies needed).

    Strategy 1: Scrape the /embed/captioned/ page — Instagram renders video URLs
                in the embed HTML even without a logged-in session.
    Strategy 2: Scrape meta tags (og:video) from the main post page.
    Strategy 3: Extract from JSON-LD or inline JSON in the page source.
    """
    m = re.search(r'/(?:p|reel|tv|videos)/([A-Za-z0-9_-]+)', url)
    if not m:
        return []
    shortcode = m.group(1)

    headers_embed = {
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/124.0.0.0 Safari/537.36'
        ),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Referer': 'https://www.instagram.com/',
        'Sec-Fetch-Mode': 'navigate',
    }

    links = []
    seen = set()

    # ── Strategy 1: embed page ───────────────────────────────────────────────
    for embed_url in [
        f'https://www.instagram.com/p/{shortcode}/embed/captioned/',
        f'https://www.instagram.com/p/{shortcode}/embed/',
    ]:
        try:
            resp = _requests.get(embed_url, headers=headers_embed, timeout=15)
            if resp.status_code != 200:
                continue
            html = resp.text

            # Various patterns Instagram uses in the embed HTML
            patterns = [
                r'data-video-url="([^"]+)"',
                r'"videoUrl"\s*:\s*"([^"]+)"',
                r'"video_url"\s*:\s*"([^"]+)"',
                r'<video[^>]+src="([^"]+)"',
                r'\\u0022src\\u0022:\\u0022(https://[^\\]+\.mp4[^\\]*)',
                r'"src":"(https://[^"]+\.mp4[^"]*)"',
            ]
            for pat in patterns:
                for vu in re.findall(pat, html):
                    vu = (vu.replace('\\u0026', '&')
                            .replace('\\/', '/')
                            .replace('&amp;', '&')
                            .replace('\\u003C', '<'))
                    if vu.startswith('http') and vu not in seen and (
                            'cdninstagram' in vu or 'fbcdn' in vu or '.mp4' in vu):
                        seen.add(vu)
                        hm = re.search(r'(\d{3,4})p', vu)
                        quality = f'{hm.group(1)}p' if hm else 'Best Quality'
                        links.append({'url': vu, 'quality': quality,
                                      'format': 'mp4', 'size': ''})

            if links:
                return links[:4]
        except Exception:
            continue

    # ── Strategy 2: og:video meta tag from main page ─────────────────────────
    for post_url in [
        f'https://www.instagram.com/p/{shortcode}/',
        f'https://www.instagram.com/reel/{shortcode}/',
    ]:
        try:
            resp = _requests.get(post_url, headers=headers_embed, timeout=15)
            if resp.status_code != 200:
                continue
            html = resp.text

            # og:video meta tags
            for vu in re.findall(
                    r'<meta[^>]+property="og:video(?::secure_url)?"[^>]+content="([^"]+)"', html):
                vu = vu.replace('&amp;', '&')
                if vu.startswith('http') and vu not in seen:
                    seen.add(vu)
                    links.append({'url': vu, 'quality': 'Best Quality',
                                  'format': 'mp4', 'size': ''})

            # Inline JSON: look for video_url in page source
            for vu in re.findall(r'"video_url"\s*:\s*"(https://[^"]+)"', html):
                vu = vu.replace('\\/', '/').replace('&amp;', '&')
                if vu not in seen and ('cdninstagram' in vu or 'fbcdn' in vu):
                    seen.add(vu)
                    links.append({'url': vu, 'quality': 'Best Quality',
                                  'format': 'mp4', 'size': ''})

            if links:
                return links[:4]
        except Exception:
            continue

    return links


# ─────────────────────────────────────────────────────────────────────────────
# Facebook Scraper
# ─────────────────────────────────────────────────────────────────────────────
def _fetch_facebook_video(url):
    session = _requests.Session()
    base_headers = {
        'User-Agent': _BROWSER_UA,
        'Accept-Language': 'en-US,en;q=0.9',
    }
    try:
        session.get('https://fdown.net/', headers=base_headers, timeout=10)
    except Exception:
        pass
    try:
        resp = session.post(
            'https://fdown.net/download.php',
            data={'URLz': url},
            headers={
                **base_headers,
                'Content-Type': 'application/x-www-form-urlencoded',
                'Referer': 'https://fdown.net/',
                'Origin': 'https://fdown.net',
                'Accept': 'text/html,application/xhtml+xml,*/*;q=0.8',
            },
            timeout=20,
            allow_redirects=True,
        )
    except Exception:
        return []
    if resp.status_code != 200:
        return []
    soup = _BS(resp.text, 'html.parser')
    links = []
    seen = set()
    for a in soup.find_all('a', href=True):
        href = a.get('href', '')
        text = a.get_text(separator=' ').strip()
        if not href or href in seen:
            continue
        text_upper = text.upper()
        is_sd = 'NORMAL' in text_upper or ('DOWNLOAD' in text_upper and 'QUALITY' in text_upper and 'HD' not in text_upper)
        is_hd = 'HD' in text_upper and 'DOWNLOAD' in text_upper
        if (is_sd or is_hd) and ('fbcdn' in href or 'facebook' in href or href.startswith('https://')):
            seen.add(href)
            quality = 'HD' if is_hd else 'SD'
            links.append({'url': href, 'quality': quality, 'format': 'mp4', 'size': ''})
    if not links:
        for a in soup.find_all('a', href=True):
            href = a.get('href', '')
            if 'fbcdn' in href and href not in seen:
                seen.add(href)
                quality = 'HD' if 'hd' in href.lower() else 'SD'
                links.append({'url': href, 'quality': quality, 'format': 'mp4', 'size': ''})
    return links[:4]


# ─────────────────────────────────────────────────────────────────────────────
# Main extraction
# ─────────────────────────────────────────────────────────────────────────────
def extract_video_info(url):
    platform = detect_platform(url)

    # ── Route to dedicated service modules for YouTube / Instagram / Pinterest ──
    cf = _cookie_file(platform) if platform else None

    if platform == 'youtube':
        return extract_youtube(url, cookie_file=cf)

    if platform == 'instagram':
        return extract_instagram(url, cookie_file=cf)

    if platform == 'pinterest':
        return extract_pinterest(url, cookie_file=cf)
    # ─────────────────────────────────────────────────────────────────────────

    scraped_links = []
    if platform == 'facebook':
        scraped_links = _fetch_facebook_video(url)

    _UA_DESKTOP = (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/124.0.0.0 Safari/537.36'
    )
    _UA_MOBILE = (
        'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) '
        'AppleWebKit/605.1.15 (KHTML, like Gecko) '
        'Version/17.0 Mobile/15E148 Safari/604.1'
    )
    _UA_ANDROID = (
        'com.google.android.youtube/19.09.37 (Linux; U; Android 11) gzip'
    )

    base_ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'noplaylist': True,
        'socket_timeout': 25,
        'extractor_retries': 3,
        'http_headers': {'User-Agent': _UA_DESKTOP},
    }

    cf = _cookie_file(platform)
    if cf:
        base_ydl_opts['cookiefile'] = cf

    # ── Per-platform retry option sets ───────────────────────────────────────
    # YouTube: tv_embedded is the most reliable client — it doesn't need a
    # PO token, bypasses bot-detection, and returns full HD format lists.
    # ios gives direct CDN URLs. android_vr + web_safari as final fallback.
    _PLATFORM_RETRY_SETS = {
        'youtube': [
            # Attempt 1: tv_embedded — most reliable without PO token
            {
                'http_headers': {'User-Agent': _UA_DESKTOP},
                'extractor_args': {
                    'youtube': {
                        'player_client': ['tv_embedded'],
                        'player_skip': ['configs', 'webpage'],
                    }
                },
                'age_limit': 99,
            },
            # Attempt 2: ios + android_vr — direct CDN URLs, no signature needed
            {
                'http_headers': {'User-Agent': _UA_MOBILE},
                'extractor_args': {
                    'youtube': {
                        'player_client': ['ios', 'android_vr'],
                        'player_skip': ['configs'],
                    }
                },
                'age_limit': 99,
            },
            # Attempt 3: android_vr + web_safari (original proven combo)
            {
                'http_headers': {'User-Agent': _UA_ANDROID},
                'extractor_args': {
                    'youtube': {
                        'player_client': ['android_vr', 'web_safari'],
                        'player_skip': ['configs'],
                    }
                },
                'age_limit': 99,
            },
            # Attempt 4: bare default (yt-dlp selects best available client)
            {
                'http_headers': {'User-Agent': _UA_DESKTOP},
                'age_limit': 99,
            },
        ],
        'tiktok': [
            {
                'http_headers': {'User-Agent': _UA_MOBILE, 'Referer': 'https://www.tiktok.com/'},
                'extractor_args': {'tiktok': {'api_hostname': ['api16-normal-c-useast1a.tiktokv.com']}},
            },
            {
                'http_headers': {'User-Agent': _UA_DESKTOP, 'Referer': 'https://www.tiktok.com/'},
                'extractor_args': {'tiktok': {'app_name': ['musical_ly'], 'app_version': ['34.1.2']}},
            },
            {'http_headers': {'User-Agent': _UA_DESKTOP}},
        ],
        'instagram': [
            # Mobile UA — Instagram prefers mobile requests for embed content
            {'http_headers': {'User-Agent': _UA_MOBILE}},
            # Desktop UA fallback
            {'http_headers': {'User-Agent': _UA_DESKTOP}},
            # Try with app API flag
            {
                'http_headers': {'User-Agent': _UA_MOBILE},
                'extractor_args': {'instagram': {'api': ['1']}},
            },
        ],
        'twitter': [
            {'http_headers': {'User-Agent': _UA_DESKTOP}},
            {'http_headers': {'User-Agent': _UA_MOBILE}},
        ],
        'pinterest': [
            {
                'http_headers': {'User-Agent': _UA_DESKTOP, 'Referer': 'https://www.pinterest.com/'},
                'extractor_args': {'pinterest': {}},
            },
            {'http_headers': {'User-Agent': _UA_MOBILE}},
        ],
        'facebook': [
            {'http_headers': {'User-Agent': _UA_DESKTOP, 'Referer': 'https://www.facebook.com/'}},
        ],
    }

    def _ydlp_extract_chain(url, platform):
        retry_sets = _PLATFORM_RETRY_SETS.get(platform, [{'http_headers': {'User-Agent': _UA_DESKTOP}}])
        last_exc = None
        for extra in retry_sets:
            opts = {**base_ydl_opts, **extra}
            if cf and 'cookiefile' not in opts:
                opts['cookiefile'] = cf
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    if info:
                        return info
            except yt_dlp.utils.DownloadError as exc:
                last_exc = exc
                msg = str(exc).lower()
                # For YouTube, always try all clients — 'login' from one client
                # doesn't mean all clients will fail (Android/iOS often succeed
                # where the web client gets bot-detected and asks for sign-in).
                if platform != 'youtube':
                    if 'private' in msg or 'unavailable' in msg:
                        break
                continue
            except Exception as exc:
                last_exc = exc
                continue
        if last_exc:
            raise last_exc
        return None

    # Facebook: fdown.net already gave us direct fbcdn.net CDN URLs.
    if platform == 'facebook':
        if scraped_links:
            working = _filter_working_links(scraped_links, platform)
            return {
                'success': True,
                'title': 'Facebook Video',
                'thumbnail': '',
                'links': working or scraped_links,
                'original_url': url,
                'platform': platform,
            }
        return {'success': False, 'error': 'Could not extract Facebook video. The video may be private or unavailable.'}

    # Pinterest: if direct scraping worked, return immediately without yt-dlp
    if platform == 'pinterest' and scraped_links:
        return {
            'success': True,
            'title': 'Pinterest Video',
            'thumbnail': '',
            'links': scraped_links[:6],
            'original_url': url,
            'platform': platform,
        }

    # Instagram: if embed-page scraping found links, use them (avoids auth wall)
    # Still fall through to yt-dlp if scraping found nothing (e.g. private posts)
    if platform == 'instagram' and scraped_links:
        working = _filter_working_links(scraped_links, platform)
        if working:
            return {
                'success': True,
                'title': 'Instagram Video',
                'thumbnail': '',
                'links': working[:4],
                'original_url': url,
                'platform': platform,
            }

    try:
        info = _ydlp_extract_chain(url, platform)

        if not info:
            if scraped_links:
                return {
                    'success': True, 'title': 'Video', 'thumbnail': '',
                    'links': scraped_links, 'original_url': url,
                    'platform': platform,
                }
            return {'success': False, 'error': 'Could not extract video information.'}

        title = info.get('title', 'Video')
        thumbnail = info.get('thumbnail', '')
        duration = info.get('duration')
        formats = info.get('formats', [])

        if scraped_links:
            result = {
                'success': True,
                'title': title,
                'thumbnail': thumbnail,
                'links': scraped_links[:6],
                'original_url': url,
                'platform': platform,
            }
            if duration:
                minutes = int(duration // 60)
                seconds = int(duration % 60)
                result['duration'] = f"{minutes}:{seconds:02d}"
            return result

        muxed_formats = []
        video_only = []
        seen_urls = set()

        for f in formats:
            f_url = f.get('url')
            if not f_url or f_url in seen_urls:
                continue

            protocol = f.get('protocol', '')
            # For Pinterest, allow HLS/m3u8 formats so we can convert them
            if protocol in ('m3u8', 'm3u8_native', 'http_dash_segments') and platform != 'pinterest':
                continue
            if protocol == 'dash' and platform not in ('facebook', 'instagram', 'tiktok', 'pinterest'):
                continue

            vcodec = f.get('vcodec', 'none')
            acodec = f.get('acodec', 'none')
            ext = f.get('ext', 'mp4')
            height = f.get('height')
            filesize = f.get('filesize') or f.get('filesize_approx')
            has_audio = acodec != 'none'
            has_video = vcodec != 'none'

            if not has_video and not has_audio and ext == 'mp4' and height:
                has_video = True
                has_audio = True

            entry = {
                'url': f_url,
                'height': height,
                'ext': ext,
                'filesize': filesize,
                'has_audio': has_audio,
                'has_video': has_video,
                'format_note': f.get('format_note', ''),
                'tbr': f.get('tbr') or 0,
                'abr': f.get('abr') or 0,
                'format_id': f.get('format_id', ''),
                'protocol': protocol,
            }
            seen_urls.add(f_url)

            if has_video and has_audio:
                muxed_formats.append(entry)
            elif has_video and not has_audio:
                video_only.append(entry)

        # Pinterest: convert HLS m3u8 entries to direct mp4 CDN URLs
        if platform == 'pinterest':
            converted = []
            seen_mp4 = set()
            for f in muxed_formats:
                if f.get('protocol') in ('m3u8', 'm3u8_native'):
                    mp4_url = _hls_to_direct_mp4(f['url'])
                    if mp4_url and mp4_url not in seen_mp4:
                        seen_mp4.add(mp4_url)
                        f2 = dict(f)
                        f2['url'] = mp4_url
                        f2['protocol'] = 'https'
                        converted.append(f2)
                else:
                    if f['url'] not in seen_mp4:
                        seen_mp4.add(f['url'])
                        converted.append(f)
            muxed_formats = converted

        links = []
        muxed_formats.sort(
            key=lambda x: (x['height'] or 0, x['ext'] == 'mp4', x['tbr']),
            reverse=True,
        )

        seen_heights = set()
        for vf in muxed_formats:
            h = vf['height']
            if h in seen_heights:
                continue
            seen_heights.add(h)

            label = f"{h}p" if h else vf['format_note'] or 'Video'
            link_entry = {
                'url': vf['url'],
                'quality': label,
                'format': vf['ext'] if vf['ext'] in ('mp4', 'webm', 'mkv') else 'mp4',
                'size': _format_size(vf['filesize']),
            }
            if vf.get('format_id'):
                link_entry['format_id'] = vf['format_id']
            links.append(link_entry)

        # ── YouTube HD quality tiers via merged format strings ──────────────
        if platform == 'youtube' and video_only:
            best_audio = None
            for f in formats:
                is_audio_only = (f.get('acodec', 'none') != 'none'
                                 and f.get('vcodec', 'none') == 'none')
                if is_audio_only and f.get('ext', '') == 'm4a':
                    if best_audio is None or (f.get('abr') or 0) > (best_audio.get('abr') or 0):
                        best_audio = f

            if best_audio:
                audio_id = best_audio.get('format_id', '')
                audio_size = (best_audio.get('filesize')
                              or best_audio.get('filesize_approx') or 0)

                yt_video_mp4 = [f for f in video_only if f.get('ext') == 'mp4']
                yt_video_mp4.sort(key=lambda x: (x['height'] or 0), reverse=True)

                for vf in yt_video_mp4:
                    h = vf['height']
                    if not h or h in seen_heights:
                        continue
                    seen_heights.add(h)

                    vid_id = vf.get('format_id', '')
                    merged_id = f'{vid_id}+{audio_id}' if vid_id and audio_id else vid_id
                    total_size = (vf.get('filesize') or vf.get('filesize_approx') or 0) + audio_size

                    links.append({
                        'url': vf['url'],
                        'quality': f'{h}p',
                        'format': 'mp4',
                        'size': _format_size(total_size) if total_size else '',
                        'format_id': merged_id,
                    })

        # ── Pinterest fallback: last resort entry ─────────────────────────────
        if platform == 'pinterest' and not links:
            all_formats = info.get('formats', [])
            # Try to derive direct mp4 URLs from any HLS in formats
            for f in all_formats:
                f_url = f.get('url', '')
                if '.m3u8' in f_url:
                    mp4_url = _hls_to_direct_mp4(f_url)
                    if mp4_url:
                        links.append({
                            'url': mp4_url,
                            'quality': '720p',
                            'format': 'mp4',
                            'size': '',
                        })
                        break
            if not links:
                links.append({
                    'url': url,
                    'quality': 'Best Quality',
                    'format': 'mp4',
                    'size': '',
                    'format_id': None,
                })

        links.sort(
            key=lambda x: int(x['quality'].replace('p', '')) if x['quality'].endswith('p') else 0,
            reverse=True,
        )

        if not links and info.get('url'):
            fallback_entry = {
                'url': info['url'],
                'quality': 'Best Quality',
                'format': info.get('ext', 'mp4'),
                'size': '',
            }
            if info.get('format_id'):
                fallback_entry['format_id'] = info['format_id']
            links.append(fallback_entry)

        if not links and info.get('requested_formats'):
            for rf in info['requested_formats']:
                rf_url = rf.get('url')
                if not rf_url:
                    continue
                rf_vcodec = rf.get('vcodec', 'none')
                rf_acodec = rf.get('acodec', 'none')
                rf_has_video = rf_vcodec != 'none'
                rf_has_audio = rf_acodec != 'none'
                if platform in ('instagram', 'tiktok', 'pinterest') and not (rf_has_video and rf_has_audio):
                    continue
                if rf_has_video:
                    label = f"{rf.get('height')}p" if rf.get('height') else 'Best'
                    rf_entry = {
                        'url': rf_url,
                        'quality': label,
                        'format': rf.get('ext', 'mp4'),
                        'size': _format_size(rf.get('filesize') or rf.get('filesize_approx')),
                    }
                    if rf.get('format_id'):
                        rf_entry['format_id'] = rf['format_id']
                    links.append(rf_entry)

        if not links and platform == 'instagram' and info.get('url'):
            main_url = info['url']
            if main_url not in seen_urls:
                height = info.get('height')
                label = f"{height}p" if height else 'Best Quality'
                links.append({
                    'url': main_url,
                    'quality': label,
                    'format': info.get('ext', 'mp4'),
                    'size': _format_size(info.get('filesize') or info.get('filesize_approx')),
                })

        if not links and platform == 'tiktok' and info.get('url'):
            main_url = info['url']
            if main_url not in seen_urls:
                height = info.get('height')
                label = f"{height}p" if height else 'Best Quality'
                tk_entry = {
                    'url': main_url,
                    'quality': label,
                    'format': info.get('ext', 'mp4'),
                    'size': _format_size(info.get('filesize') or info.get('filesize_approx')),
                }
                if info.get('format_id'):
                    tk_entry['format_id'] = info['format_id']
                links.append(tk_entry)

        if not links and platform == 'facebook':
            for key in ('hd_url', 'sd_url'):
                direct_url = info.get(key)
                if direct_url and direct_url not in seen_urls:
                    quality = 'HD' if 'hd' in key else 'SD'
                    fmt_id = 'hd' if 'hd' in key else 'sd'
                    links.append({
                        'url': direct_url,
                        'quality': quality,
                        'format': 'mp4',
                        'size': '',
                        'format_id': fmt_id,
                    })

        if not links:
            return {'success': False, 'error': 'No downloadable video formats found.'}

        links = links[:6]
        links = _filter_working_links(links, platform)

        if not links:
            return {'success': False, 'error': 'No working download links found for this video. Please try again.'}

        result = {
            'success': True,
            'title': title,
            'thumbnail': thumbnail,
            'links': links,
            'original_url': url,
            'platform': platform,
        }

        if duration:
            minutes = int(duration // 60)
            seconds = int(duration % 60)
            result['duration'] = f"{minutes}:{seconds:02d}"

        return result

    except yt_dlp.utils.DownloadError as e:
        if scraped_links:
            return {
                'success': True, 'title': 'Video', 'thumbnail': '',
                'links': scraped_links[:6], 'original_url': url,
                'platform': platform,
            }
        error_msg = str(e)
        if 'IP address is blocked' in error_msg or 'IP is blocked' in error_msg:
            return {'success': False, 'error': 'TikTok has blocked access from this server. Try again later or use a different network.'}
        if 'cookies' in error_msg.lower() or 'login' in error_msg.lower() or 'empty media response' in error_msg.lower():
            # YouTube bot-detection is a server-side issue, not a user cookie issue
            if platform == 'youtube':
                return {'success': False, 'error': 'YouTube is temporarily blocking this server. Please try again in a few seconds, or try a different video link.'}
            return {'success': False, 'error': (
                'This platform requires authentication. '
                'Export your browser cookies to cookies/' + (platform or 'platform') + '.txt '
                'to enable authenticated downloads.'
            )}
        if 'No video could be found' in error_msg:
            return {'success': False, 'error': 'No video found in this post. Make sure the link contains a video.'}
        if 'Private' in error_msg or 'private' in error_msg:
            return {'success': False, 'error': 'This video is private or unavailable.'}
        if platform == 'pinterest' and ('404' in error_msg or 'not found' in error_msg.lower()):
            return {'success': False, 'error': 'Pinterest pin not found. Check that the link is correct and the pin is public.'}
        if '404' in error_msg or 'not found' in error_msg.lower():
            return {'success': False, 'error': 'Video not found. The post may be private, deleted, or region-restricted.'}
        return {'success': False, 'error': 'Could not extract video. The post may be private or the platform blocked access.'}
    except Exception as e:
        if scraped_links:
            return {
                'success': True, 'title': 'Video', 'thumbnail': '',
                'links': scraped_links[:6], 'original_url': url,
                'platform': platform,
            }
        return {'success': False, 'error': f'Download service error: {str(e)}'}


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_POST(self):
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            data = json.loads(body) if body else {}
        except (json.JSONDecodeError, ValueError):
            self._send_json(400, {'success': False, 'error': 'Invalid request body'})
            return

        url = data.get('url', '').strip()
        if not url:
            self._send_json(400, {'success': False, 'error': 'URL is required'})
            return

        platform = detect_platform(url)
        if not platform:
            self._send_json(400, {'success': False, 'error': 'Unsupported platform'})
            return

        result = extract_video_info(url)
        result['platform'] = platform

        status = 200 if result.get('success') else 422
        self._send_json(status, result)

    def _send_json(self, status, data):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))

    def log_message(self, format, *args):
        pass
