"""
Pinterest download service — yt-dlp primary + improved direct scraping.

Strategy order:
1. yt-dlp (Pinterest natively supported, most reliable)
2. Direct page scraping with improved patterns (pinimg.com CDN URLs)
3. Pinterest v3 internal API
4. savepin.app fallback

Fixes:
- yt-dlp is now the primary (most reliable for Pinterest)
- Improved HLS→direct MP4 conversion with updated regex
- Better page scraping patterns for the new Pinterest HTML structure
- Added multiple quality levels from the pinimg CDN path structure
"""

import re
import json
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
import requests as _requests
from bs4 import BeautifulSoup as _BS
import yt_dlp

_UA_DESKTOP = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/124.0.0.0 Safari/537.36'
)
_UA_MOBILE = (
    'Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) '
    'AppleWebKit/605.1.15 (KHTML, like Gecko) '
    'Version/17.4 Mobile/15E148 Safari/604.1'
)


def _format_size(filesize):
    if not filesize:
        return ''
    mb = filesize / (1024 * 1024)
    return f"{mb:.1f} MB" if mb >= 1 else f"{filesize / 1024:.0f} KB"


def _test_url(url, timeout=5):
    """HEAD-check a URL; return False if it returns 4xx/5xx or XML/HTML content."""
    try:
        r = _requests.head(
            url,
            headers={
                'User-Agent': _UA_DESKTOP,
                'Referer': 'https://www.pinterest.com/',
            },
            timeout=timeout,
            allow_redirects=True,
        )
        if r.status_code >= 400:
            return False
        ct = r.headers.get('Content-Type', '').lower()
        if 'xml' in ct or 'html' in ct or 'text/' in ct:
            return False
        return True
    except Exception:
        return False


def _filter_working_links(links):
    """Test all links in parallel and keep only those that return valid video."""
    if not links:
        return links

    def _check(link):
        return _test_url(link['url']), link

    with ThreadPoolExecutor(max_workers=min(6, len(links))) as ex:
        results = list(ex.map(_check, links))

    working = [link for ok, link in results if ok]
    return working


def _resolve_short_url(url):
    """Expand pin.it short links to full pinterest.com/pin/... URLs."""
    if 'pin.it' not in url.lower():
        return url
    try:
        r = _requests.get(
            url,
            headers={'User-Agent': _UA_DESKTOP, 'Accept': 'text/html'},
            timeout=12,
            allow_redirects=True,
        )
        for resp in list(r.history) + [r]:
            m = re.search(r'/pin/(\d+)', resp.url)
            if m:
                return f'https://www.pinterest.com/pin/{m.group(1)}/'
    except Exception:
        pass
    return url


def _hls_to_direct_mp4(m3u8_url, quality='720p'):
    """
    Convert a Pinterest HLS manifest URL to a direct MP4 CDN URL.

    Known patterns (from yt-dlp):
      https://v1.pinimg.com/videos/mc/hls/12/83/f0/<hash>_720w.m3u8
      → https://v1.pinimg.com/videos/mc/720p/12/83/f0/<hash>.mp4

      https://v1.pinimg.com/videos/iht/hls/<hash>_720w.m3u8
      → https://v1.pinimg.com/videos/mc/720p/<hash>.mp4
    """
    # Pattern: .../hls/<path...>/<hash>[_<bitrate>w].m3u8
    m = re.match(
        r'(https://[^/]*pinimg\.com)/videos/(?:mc|iht)/hls/((?:[^/]+/)*[^/_?#]+?)(?:_\d+w)?\.m3u8',
        m3u8_url
    )
    if m:
        cdn_base, video_path = m.group(1), m.group(2)
        return f'{cdn_base}/videos/mc/{quality}/{video_path}.mp4'

    # Pattern: .../iht/<res>/<hash>.m3u8
    m2 = re.match(
        r'(https://[^/]*pinimg\.com)/videos/iht/\d+p/((?:[^/]+/)*[^/?#]+?)\.m3u8',
        m3u8_url
    )
    if m2:
        cdn_base, video_path = m2.group(1), m2.group(2)
        return f'{cdn_base}/videos/mc/{quality}/{video_path}.mp4'

    return None


def _extract_quality_variants(base_mp4_url):
    """
    Given a pinimg.com MP4 URL, derive multiple quality variants.
    e.g. .../videos/mc/720p/<hash>.mp4 → also try 1080p, 480p, 360p
    """
    qualities = ['1080p', '720p', '480p', '360p']
    variants = []
    seen = set()

    for q in qualities:
        variant = re.sub(r'/mc/\d+p/', f'/mc/{q}/', base_mp4_url)
        # Also try path with iht prefix
        variant2 = re.sub(r'/iht/\d+p/', f'/iht/{q}/', base_mp4_url)
        for v in [variant, variant2]:
            if v not in seen:
                seen.add(v)
                variants.append({'url': v, 'quality': q, 'format': 'mp4', 'size': ''})

    return variants


def _build_links_from_mp4_urls(mp4_urls, m3u8_urls):
    """Convert raw URL sets into link entries with quality labels."""
    links = []
    seen = set()

    for mp4_url in mp4_urls:
        mp4_url = mp4_url.replace('\\/', '/').replace('\\u002F', '/')
        if mp4_url in seen:
            continue
        seen.add(mp4_url)
        quality = 'HD'
        for q in ['1080p', '720p', '480p', '360p']:
            if q.lower() in mp4_url.lower() or q in mp4_url:
                quality = q
                break
        # If we found a 720p URL, try to derive other qualities
        if '720p' in mp4_url or '/mc/' in mp4_url:
            variants = _extract_quality_variants(mp4_url)
            for v in variants:
                if v['url'] not in seen:
                    seen.add(v['url'])
                    links.append(v)
        else:
            links.append({'url': mp4_url, 'quality': quality, 'format': 'mp4', 'size': ''})

    for m3u8_url in m3u8_urls:
        m3u8_url = m3u8_url.replace('\\/', '/').replace('\\u002F', '/')
        mp4_url = _hls_to_direct_mp4(m3u8_url)
        if mp4_url and mp4_url not in seen:
            seen.add(mp4_url)
            quality = '720p'
            links.append({'url': mp4_url, 'quality': quality, 'format': 'mp4', 'size': ''})
            # Derive other qualities
            for vq in ['1080p', '480p', '360p']:
                vurl = re.sub(r'/mc/\d+p/', f'/mc/{vq}/', mp4_url)
                if vurl not in seen:
                    seen.add(vurl)
                    links.append({'url': vurl, 'quality': vq, 'format': 'mp4', 'size': ''})

    return links


def _parse_any_json_for_videos(json_obj):
    """Recursively search a JSON object for pinimg.com video URLs."""
    text = json.dumps(json_obj)
    mp4_urls = re.findall(r'https://v\d+\.pinimg\.com/videos/[^"\'\\&\s]+\.mp4', text)
    m3u8_urls = re.findall(r'https://v\d+\.pinimg\.com/videos/[^"\'\\&\s]+\.m3u8', text)
    mp4_urls = [u.replace('\\/', '/') for u in mp4_urls]
    m3u8_urls = [u.replace('\\/', '/') for u in m3u8_urls]
    return _build_links_from_mp4_urls(mp4_urls, m3u8_urls)


# ── Strategy 1: yt-dlp ───────────────────────────────────────────────────────
def _try_ytdlp(url, cookie_file=None):
    """
    Use yt-dlp to extract Pinterest video.

    yt-dlp returns HLS (m3u8_native) formats + one direct mp4 as the top format.
    We use the direct mp4 URL from info['url'] and derive multiple quality
    variants from the HLS manifest URL pattern.
    """
    retry_sets = [
        {'http_headers': {'User-Agent': _UA_DESKTOP, 'Referer': 'https://www.pinterest.com/'}},
        {'http_headers': {'User-Agent': _UA_MOBILE}},
    ]

    base_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'noplaylist': True,
        'socket_timeout': 30,
        'extractor_retries': 3,
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
        return [], '', ''

    title = info.get('title', 'Pinterest Video')
    thumbnail = info.get('thumbnail', '')
    formats = info.get('formats', [])
    links = []
    seen = set()

    # Collect direct mp4 URLs (protocol=https) first — these are highest quality
    for f in formats:
        f_url = f.get('url')
        if not f_url or f_url in seen:
            continue
        protocol = f.get('protocol', '')
        if protocol == 'https' and f_url.endswith('.mp4') and 'pinimg' in f_url:
            seen.add(f_url)
            # Extract quality from URL path (e.g. /mc/720p/) — more reliable than pixel height
            q_m = re.search(r'/mc/(\d+p)/', f_url)
            quality = q_m.group(1) if q_m else '720p'
            links.append({'url': f_url, 'quality': quality, 'format': 'mp4', 'size': ''})

    # Derive quality variants from the direct mp4 URL base
    if links:
        base_url = links[0]['url']
        # Extract base path: .../mc/720p/12/83/f0/<hash>.mp4
        base_m = re.match(r'(https://[^/]*pinimg\.com/videos/mc)/\d+p/(.*\.mp4)', base_url)
        if base_m:
            cdn_prefix = base_m.group(1)
            video_path = base_m.group(2)
            seen_q = {links[0]['quality']}
            for q_label, q_path in [('1080p', '1080p'), ('720p', '720p'), ('480p', '480p'), ('360p', '360p')]:
                if q_label not in seen_q:
                    variant_url = f'{cdn_prefix}/{q_path}/{video_path}'
                    if variant_url not in seen:
                        seen.add(variant_url)
                        links.append({'url': variant_url, 'quality': q_label, 'format': 'mp4', 'size': ''})

    # Convert HLS formats to direct mp4 if we don't have direct URLs
    if not links:
        for f in formats:
            f_url = f.get('url')
            if not f_url or f_url in seen:
                continue
            protocol = f.get('protocol', '')
            height = f.get('height')
            if protocol in ('m3u8', 'm3u8_native') and 'pinimg' in f_url:
                # Map HLS height to standard quality label
                quality_map = {424: '480p', 640: '480p', 852: '480p',
                               1136: '720p', 1280: '720p', 1920: '1080p'}
                q_label = quality_map.get(height, f"{height}p" if height else '720p')
                # Convert to direct mp4
                q_path = q_label  # e.g. "720p"
                mp4_url = _hls_to_direct_mp4(f_url, quality=q_path)
                if mp4_url and mp4_url not in seen:
                    seen.add(mp4_url)
                    links.append({'url': mp4_url, 'quality': q_label, 'format': 'mp4', 'size': ''})

    # Use info['url'] as final fallback
    if not links and info.get('url'):
        direct = info['url']
        if '.m3u8' in direct:
            mp4_url = _hls_to_direct_mp4(direct)
            if mp4_url:
                direct = mp4_url
        seen.add(direct)
        h = info.get('height')
        links.append({'url': direct, 'quality': f"{h}p" if h else 'Best Quality', 'format': 'mp4', 'size': ''})

    return links[:6], title, thumbnail


# ── Strategy 2: Direct page scraping ────────────────────────────────────────
def _try_page_scrape(url):
    """Scrape Pinterest page HTML for embedded video URLs."""
    headers = {
        'User-Agent': _UA_DESKTOP,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Referer': 'https://www.pinterest.com/',
    }
    try:
        resp = _requests.get(url, headers=headers, timeout=20, allow_redirects=True)
        if resp.status_code != 200:
            return []
        html = resp.text

        mp4_urls = re.findall(r'https://v\d+\.pinimg\.com/videos/[^"\'\\&\s]+\.mp4', html)
        m3u8_urls = re.findall(r'https://v\d+\.pinimg\.com/videos/[^"\'\\&\s]+\.m3u8', html)

        links = _build_links_from_mp4_urls(mp4_urls, m3u8_urls)

        if not links:
            # Try JSON blobs in <script> tags
            soup = _BS(html, 'html.parser')
            for script in soup.find_all('script'):
                content = script.string or script.get_text() or ''
                if 'pinimg.com' not in content:
                    continue
                extra_mp4 = re.findall(r'https://v\d+\.pinimg\.com/videos/[^"\'\\&\s]+\.mp4', content)
                extra_m3u8 = re.findall(r'https://v\d+\.pinimg\.com/videos/[^"\'\\&\s]+\.m3u8', content)
                if extra_mp4 or extra_m3u8:
                    links.extend(_build_links_from_mp4_urls(extra_mp4, extra_m3u8))

        if not links:
            # Try all embedded JSON blobs
            for pat in [
                r'<script[^>]+id="__NEXT_DATA__"[^>]*>\s*(\{.*?\})\s*</script>',
                r'__PWS_INITIAL_PROPS__\s*=\s*(\{.*?\})\s*;',
                r'__PWS_DATA__\s*=\s*(\{.*?\})\s*;',
                r'P\.start\.start\(\s*(\{.*?\})\s*\)',
            ]:
                m = re.search(pat, html, re.DOTALL)
                if m:
                    try:
                        json_data = json.loads(m.group(1))
                        extra = _parse_any_json_for_videos(json_data)
                        links.extend(extra)
                    except Exception:
                        pass

        # Deduplicate
        seen = set()
        deduped = []
        for l in links:
            if l['url'] not in seen:
                seen.add(l['url'])
                deduped.append(l)
        return deduped[:6]

    except Exception:
        return []


# ── Strategy 3: Pinterest v3 API ─────────────────────────────────────────────
def _try_api_v3(url):
    """Use Pinterest's internal JSON API."""
    m = re.search(r'/pin/(\d+)', url)
    if not m:
        return []
    pin_id = m.group(1)

    endpoints = [
        f'https://www.pinterest.com/resource/PinResource/get/?source_url=/pin/{pin_id}/&data={{"options":{{"id":"{pin_id}","field_set_key":"detailed"}}}}',
        f'https://www.pinterest.com/resource/VideoResource/get/?source_url=/pin/{pin_id}/&data={{"options":{{"id":"{pin_id}"}}}}',
    ]
    headers = {
        'User-Agent': _UA_DESKTOP,
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
            links = _parse_any_json_for_videos(data)
            if links:
                return links
        except Exception:
            continue
    return []


# ── Strategy 4: savepin.app ──────────────────────────────────────────────────
def _try_savepin(url):
    """Fallback: savepin.app."""
    encoded_url = urllib.parse.quote(url, safe='')
    api_url = f'https://www.savepin.app/download.php?url={encoded_url}&lang=en&type=redirect'
    headers = {
        'User-Agent': _UA_DESKTOP,
        'Accept': 'text/html,application/xhtml+xml,*/*;q=0.8',
        'Referer': 'https://www.savepin.app/',
    }
    try:
        resp = _requests.get(api_url, headers=headers, timeout=20, allow_redirects=True)
        soup = _BS(resp.text, 'html.parser')
        links = []
        seen = set()
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
            if direct_url and direct_url.startswith('http') and direct_url not in seen:
                seen.add(direct_url)
                links.append({'url': direct_url, 'quality': quality, 'format': fmt or 'mp4', 'size': ''})
        return links[:4]
    except Exception:
        return []


def extract_pinterest(url, cookie_file=None):
    """
    Main Pinterest extractor. Tries 4 strategies in order.
    Returns dict with success/links/title/thumbnail.
    """
    url = _resolve_short_url(url)

    # Strategy 1: yt-dlp (most reliable)
    try:
        result = _try_ytdlp(url, cookie_file)
        if isinstance(result, tuple):
            links, title, thumbnail = result
        else:
            links, title, thumbnail = result, 'Pinterest Video', ''

        if links:
            links = _filter_working_links(links)
            if links:
                links.sort(
                    key=lambda x: int(x['quality'].replace('p', '')) if x['quality'].endswith('p') else 0,
                    reverse=True,
                )
                return {
                    'success': True,
                    'title': title or 'Pinterest Video',
                    'thumbnail': thumbnail or '',
                    'links': links,
                    'platform': 'pinterest',
                }
    except Exception:
        pass

    # Strategy 2: direct page scraping
    links = _try_page_scrape(url)
    if links:
        links = _filter_working_links(links)
        if links:
            links.sort(
                key=lambda x: int(x['quality'].replace('p', '')) if x['quality'].endswith('p') else 0,
                reverse=True,
            )
            return {
                'success': True,
                'title': 'Pinterest Video',
                'thumbnail': '',
                'links': links,
                'platform': 'pinterest',
            }

    # Strategy 3: Pinterest v3 API
    links = _try_api_v3(url)
    if links:
        links = _filter_working_links(links)
        if links:
            return {
                'success': True,
                'title': 'Pinterest Video',
                'thumbnail': '',
                'links': links,
                'platform': 'pinterest',
            }

    # Strategy 4: savepin.app
    links = _try_savepin(url)
    if links:
        links = _filter_working_links(links)
        if links:
            return {
                'success': True,
                'title': 'Pinterest Video',
                'thumbnail': '',
                'links': links,
                'platform': 'pinterest',
            }

    return {
        'success': False,
        'error': (
            'Could not extract Pinterest video. '
            'Make sure the pin is public and contains a video.'
        ),
    }
