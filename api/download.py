"""
NADIR DOWNLOADER - Video Download API
Uses direct page scraping (Facebook, Pinterest) and yt-dlp (other platforms)
to extract video download links from social media platforms.

Radical resilience strategy
────────────────────────────
1. Cookie files  — place Netscape-format cookies in  cookies/<platform>.txt
                   (instagram.txt, tiktok.txt, twitter.txt, youtube.txt, facebook.txt)
2. Multi-option yt-dlp retry chain — each platform is tried with progressively
   different yt-dlp option sets so that temporary extractor quirks are bypassed.
3. Platform-specific alternative extraction paths run BEFORE yt-dlp.
4. yt-dlp is auto-updated on server startup so extractors stay current.
"""

from http.server import BaseHTTPRequestHandler
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import re
import urllib.parse
import yt_dlp
import requests as _requests
from bs4 import BeautifulSoup as _BS

# ── Cookie-file support ───────────────────────────────────────────────────────
# Place Netscape/Mozilla cookie files (exported by browser extensions like
# "Get cookies.txt LOCALLY") in the  cookies/  directory at the project root.
_COOKIE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'cookies')

def _cookie_file(platform: str):
    """Return path to the cookie file for *platform* if it exists, else None."""
    path = os.path.join(_COOKIE_DIR, f'{platform}.txt')
    return path if os.path.isfile(path) else None


def detect_platform(url):
    """Detect the social media platform from the URL."""
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
    """Format file size into a human-readable string."""
    if not filesize:
        return ''
    size_mb = filesize / (1024 * 1024)
    if size_mb >= 1:
        return f"{size_mb:.1f} MB"
    size_kb = filesize / 1024
    return f"{size_kb:.0f} KB"


def _pinterest_direct_mp4(formats, links, seen_heights):
    """Build direct MP4 download links for Pinterest videos.

    Pinterest's CDN hosts muxed (video+audio) MP4 files at a predictable
    path derived from the HLS manifest URL::

        HLS:    https://v1.pinimg.com/videos/iht/hls/<hash>_<width>w.m3u8
        Direct: https://v1.pinimg.com/videos/mc/720p/<hash>.mp4

    The mc/720p MP4 already contains both video and audio, so it can
    be proxied directly without needing ffmpeg to merge separate streams.
    This function also tries v2 CDN path variants and multiple resolutions.
    """
    # More flexible regex: matches any pinimg.com subdomain and any HLS path variant.
    HLS_RE = re.compile(
        r'(https://[^/]*\.pinimg\.com)/videos/(?:[^/]+/)*hls/(.+?)_\w+\.m3u8'
    )

    cdn_base = None
    video_hash = None
    best_height = None

    for f in formats:
        f_url = f.get('url', '')
        m = HLS_RE.match(f_url)
        if m:
            cdn_base = m.group(1)  # e.g. https://v1.pinimg.com
            video_hash = m.group(2)
            h = f.get('height')
            if h and (best_height is None or h > best_height):
                best_height = h

    if not video_hash:
        return

    # Default base if not found from HLS URL
    if not cdn_base:
        cdn_base = 'https://v1.pinimg.com'

    # Offer multiple resolutions; the CDN serves 720p and v2/720p variants.
    resolutions = [
        ('720p', f'{cdn_base}/videos/mc/720p/{video_hash}.mp4'),
        ('480p', f'{cdn_base}/videos/mc/480p/{video_hash}.mp4'),
        ('v2/720p', f'{cdn_base}/videos/mc/v2/720p/{video_hash}.mp4'),
    ]

    added = False
    for label, url in resolutions:
        res_num = int(label.split('/')[-1].replace('p', '')) if label[-1] == 'p' else 720
        if res_num not in seen_heights:
            seen_heights.add(res_num)
            links.append({
                'url': url,
                'quality': label,
                'format': 'mp4',
                'size': '',
            })
            added = True

    # If nothing was added (all heights already seen), force-add the 720p variant.
    if not added:
        links.append({
            'url': f'{cdn_base}/videos/mc/720p/{video_hash}.mp4',
            'quality': '720p',
            'format': 'mp4',
            'size': '',
        })


_BROWSER_UA = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/124.0.0.0 Safari/537.36'
)

# Platform-specific headers used when testing CDN URLs for validity
_PLATFORM_TEST_HEADERS = {
    'facebook':  {'User-Agent': _BROWSER_UA, 'Referer': 'https://www.facebook.com/'},
    'instagram': {'User-Agent': _BROWSER_UA, 'Referer': 'https://www.instagram.com/'},
    'pinterest': {'User-Agent': _BROWSER_UA, 'Referer': 'https://www.pinterest.com/'},
    'twitter':   {'User-Agent': _BROWSER_UA, 'Referer': 'https://twitter.com/'},
    'youtube':   {'User-Agent': _BROWSER_UA},
}


def _test_url(url, headers=None, timeout=5):
    """
    Quick HEAD request to check whether a CDN URL is alive and serves video.

    Returns True  → URL looks valid (keep it).
    Returns False → URL returned an explicit 4xx/5xx or an XML/HTML error page.
    Returns True  → on timeout or network error (give benefit of the doubt).
    """
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
        # Reject XML / HTML error pages (e.g. AWS S3 AccessDenied)
        if 'xml' in ct or 'html' in ct:
            return False
        return True
    except Exception:
        # Timeout or connection error — keep the link (don't punish slow CDNs)
        return True


def _filter_working_links(links, platform):
    """
    Test each CDN URL concurrently and remove broken ones.

    TikTok is excluded: its proxy always re-downloads via yt-dlp using the
    original page URL, so the extracted CDN URLs are never used directly.

    If every URL fails the test the original list is returned unchanged
    (better to show something than an empty result set).
    """
    if platform == 'tiktok' or not links:
        return links

    headers = _PLATFORM_TEST_HEADERS.get(platform, {'User-Agent': _BROWSER_UA})

    def _check(link):
        return _test_url(link['url'], headers), link

    with ThreadPoolExecutor(max_workers=min(6, len(links))) as ex:
        results = list(ex.map(_check, links))

    working = [link for ok, link in results if ok]
    return working if working else links  # fallback: keep all if all failed


def _fetch_facebook_video(url):
    """
    Extract Facebook video links via fdown.net.

    Flow:
      1. Seed session cookies from fdown.net homepage.
      2. POST the Facebook URL to fdown.net/download.php.
      3. Parse the returned HTML for HD / SD download anchors.
    Returns a list of link dicts [{url, quality, format, size}].
    """
    session = _requests.Session()
    base_headers = {
        'User-Agent': _BROWSER_UA,
        'Accept-Language': 'en-US,en;q=0.9',
    }

    # Step 1 — seed cookies
    try:
        session.get('https://fdown.net/', headers=base_headers, timeout=10)
    except Exception:
        pass

    # Step 2 — POST URL to fdown.net
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

    # Step 3 — parse anchors for SD / HD links
    soup = _BS(resp.text, 'html.parser')
    links = []
    seen = set()

    for a in soup.find_all('a', href=True):
        href = a.get('href', '')
        text = a.get_text(separator=' ').strip()
        if not href or href in seen:
            continue
        # fdown.net labels: "Download Video in Normal Quality" (SD) and "Download Video in HD Quality" (HD)
        text_upper = text.upper()
        is_sd = 'NORMAL' in text_upper or ('DOWNLOAD' in text_upper and 'QUALITY' in text_upper and 'HD' not in text_upper)
        is_hd = 'HD' in text_upper and 'DOWNLOAD' in text_upper
        if (is_sd or is_hd) and ('fbcdn' in href or 'facebook' in href or href.startswith('https://')):
            seen.add(href)
            quality = 'HD' if is_hd else 'SD'
            links.append({'url': href, 'quality': quality, 'format': 'mp4', 'size': ''})

    # Fallback: any fbcdn.net anchor on the page
    if not links:
        for a in soup.find_all('a', href=True):
            href = a.get('href', '')
            if 'fbcdn' in href and href not in seen:
                seen.add(href)
                quality = 'HD' if 'hd' in href.lower() else 'SD'
                links.append({'url': href, 'quality': quality, 'format': 'mp4', 'size': ''})

    return links[:4]


def _resolve_pinterest_url(url):
    """
    Resolve a pin.it short URL to a clean pinterest.com/pin/<id>/ URL.
    pin.it redirects through Pinterest's API, so we follow the chain and
    extract the numeric pin ID from whichever hop contains it.
    Non-pin.it URLs are returned unchanged.
    """
    if 'pin.it' not in url.lower():
        return url
    try:
        r = _requests.get(
            url,
            headers={'User-Agent': _BROWSER_UA, 'Accept': 'text/html'},
            timeout=12,
            allow_redirects=True,
        )
        # Walk the redirect chain (including the final response URL)
        for resp in list(r.history) + [r]:
            m = re.search(r'/pin/(\d+)/', resp.url)
            if m:
                return f'https://www.pinterest.com/pin/{m.group(1)}/'
    except Exception:
        pass
    return url


def _fetch_pinterest_video(url):
    """
    Extract Pinterest video links via savepin.app — the same service used by
    the reference repo (milancodess/universalDownloader).

    pin.it short URLs are resolved to a full pinterest.com/pin/<id>/ URL
    before calling savepin.app, because savepin.app cannot handle short URLs.
    Returns a list of link dicts [{url, quality, format, size}].
    """
    url = _resolve_pinterest_url(url)
    encoded_url = urllib.parse.quote(url, safe='')
    api_url = (
        f'https://www.savepin.app/download.php'
        f'?url={encoded_url}&lang=en&type=redirect'
    )
    headers = {
        'User-Agent': _BROWSER_UA,
        'Accept': (
            'text/html,application/xhtml+xml,application/xml;'
            'q=0.9,image/avif,image/webp,*/*;q=0.8'
        ),
        'Accept-Language': 'en-US,en;q=0.9',
        'Referer': 'https://www.savepin.app/',
        'sec-ch-ua': '"Not)A;Brand";v="8", "Chromium";v="124"',
        'sec-ch-ua-mobile': '?0',
        'sec-fetch-dest': 'document',
        'sec-fetch-mode': 'navigate',
        'sec-fetch-site': 'same-origin',
        'upgrade-insecure-requests': '1',
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
            # savepin.app wraps links as force-save.php?url=<encoded_direct_url>
            # or /download?url=<encoded_direct_url>
            parsed = urllib.parse.urlparse(href)
            qs = urllib.parse.parse_qs(parsed.query)
            direct_url = qs.get('url', [href])[0]

            quality_el = row.select_one('.video-quality')
            quality = (quality_el.text.strip() if quality_el
                       else (tds[0].text.strip() if tds else 'Unknown'))
            fmt = tds[1].text.strip().lower() if len(tds) > 1 else 'mp4'

            # Skip image-only entries (thumbnail rows) — only keep video formats
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


def extract_video_info(url):
    """
    Extract video info and download links.
    Facebook and Pinterest use direct page-scraping (more reliable).
    All other platforms (and as fallback) use yt-dlp.
    """
    platform = detect_platform(url)

    # Resolve pin.it short URLs to a clean pinterest.com/pin/<id>/ URL so
    # that both the scraping path and yt-dlp receive a canonical URL.
    if platform == 'pinterest':
        url = _resolve_pinterest_url(url)

    # --- Scraping for Facebook (fdown.net) and Pinterest ---
    # Facebook: use fdown.net which returns direct fbcdn.net CDN URLs that
    # the proxy can stream immediately — no yt-dlp needed in the proxy.
    # Pinterest: use savepin.app for fast, reliable CDN URLs.
    scraped_links = []
    if platform == 'facebook':
        scraped_links = _fetch_facebook_video(url)
    elif platform == 'pinterest':
        scraped_links = _fetch_pinterest_video(url)

    # ── Base yt-dlp options ───────────────────────────────────────────────────
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

    base_ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'noplaylist': True,
        'socket_timeout': 20,
        'extractor_retries': 3,
        'http_headers': {'User-Agent': _UA_DESKTOP},
    }

    # Attach cookie file if available (enables auth for Instagram, Twitter, etc.)
    cf = _cookie_file(platform)
    if cf:
        base_ydl_opts['cookiefile'] = cf

    # ── Per-platform retry option sets ───────────────────────────────────────
    # Each set is tried in order; the first that succeeds wins.
    # This handles temporary extractor quirks, header changes, and soft IP blocks.
    _PLATFORM_RETRY_SETS = {
        'tiktok': [
            # Attempt 1: mobile API endpoint (bypasses some IP bans)
            {
                'http_headers': {'User-Agent': _UA_MOBILE, 'Referer': 'https://www.tiktok.com/'},
                'extractor_args': {'tiktok': {'api_hostname': ['api16-normal-c-useast1a.tiktokv.com']}},
            },
            # Attempt 2: desktop + different app name
            {
                'http_headers': {'User-Agent': _UA_DESKTOP, 'Referer': 'https://www.tiktok.com/'},
                'extractor_args': {'tiktok': {'app_name': ['musical_ly'], 'app_version': ['34.1.2']}},
            },
            # Attempt 3: bare desktop, let yt-dlp decide
            {'http_headers': {'User-Agent': _UA_DESKTOP}},
        ],
        'instagram': [
            # Attempt 1: mobile UA (Instagram sometimes serves public content to mobile)
            {'http_headers': {'User-Agent': _UA_MOBILE}},
            # Attempt 2: desktop
            {'http_headers': {'User-Agent': _UA_DESKTOP}},
        ],
        'twitter': [
            {'http_headers': {'User-Agent': _UA_DESKTOP}},
            {'http_headers': {'User-Agent': _UA_MOBILE}},
        ],
        'pinterest': [
            {'http_headers': {'User-Agent': _UA_DESKTOP, 'Referer': 'https://www.pinterest.com/'}},
            {'http_headers': {'User-Agent': _UA_MOBILE}},
        ],
        'youtube': [
            {'http_headers': {'User-Agent': _UA_DESKTOP}},
        ],
        'facebook': [
            {'http_headers': {'User-Agent': _UA_DESKTOP, 'Referer': 'https://www.facebook.com/'}},
        ],
    }

    def _ydlp_extract_chain(url, platform):
        """Try each option set for the platform; return info dict on first success."""
        retry_sets = _PLATFORM_RETRY_SETS.get(platform, [{'http_headers': {'User-Agent': _UA_DESKTOP}}])
        last_exc = None
        for extra in retry_sets:
            opts = {**base_ydl_opts, **extra}
            # Per-set cookie override keeps the cookie file even if extra overrides headers
            if cf and 'cookiefile' not in opts:
                opts['cookiefile'] = cf
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    if info:
                        return info
            except yt_dlp.utils.DownloadError as exc:
                last_exc = exc
                # If it's a hard auth/cookie error, no point retrying with same platform
                msg = str(exc).lower()
                if 'login' in msg or 'private' in msg or 'unavailable' in msg:
                    break
                continue
            except Exception as exc:
                last_exc = exc
                continue
        if last_exc:
            raise last_exc
        return None

    # Facebook: fdown.net already gave us direct fbcdn.net CDN URLs.
    # yt-dlp cannot parse Facebook pages from server environments, so skip it.
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

    try:
        info = _ydlp_extract_chain(url, platform)

        if not info:
            # yt-dlp returned nothing — if scraping worked use those links
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

        # --- If scraping already found links, combine with yt-dlp metadata ---
        if scraped_links:
            result = {
                'success': True,
                'title': title,
                'thumbnail': thumbnail,
                'links': scraped_links[:6],
                'original_url': url,
            }
            if duration:
                minutes = int(duration // 60)
                seconds = int(duration % 60)
                result['duration'] = f"{minutes}:{seconds:02d}"
            return result

        # Separate formats into categories
        muxed_formats = []   # has both video + audio
        video_only = []      # video only (no audio)
        seen_urls = set()

        for f in formats:
            f_url = f.get('url')
            if not f_url or f_url in seen_urls:
                continue

            protocol = f.get('protocol', '')
            if protocol in ('m3u8', 'm3u8_native', 'http_dash_segments'):
                continue
            # Allow dash protocol for Facebook and Instagram to capture more formats
            if protocol == 'dash' and platform not in ('facebook', 'instagram', 'tiktok', 'pinterest'):
                continue

            vcodec = f.get('vcodec', 'none')
            acodec = f.get('acodec', 'none')

            ext = f.get('ext', 'mp4')
            height = f.get('height')
            filesize = f.get('filesize') or f.get('filesize_approx')
            has_audio = acodec != 'none'
            has_video = vcodec != 'none'

            # Pinterest V_720P format reports vcodec=None / acodec=None
            # but is actually a muxed direct MP4.  Treat it as muxed.
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
            }
            seen_urls.add(f_url)

            if has_video and has_audio:
                muxed_formats.append(entry)
            elif has_video and not has_audio:
                video_only.append(entry)

        # Build links: prefer muxed (audio+video) formats
        links = []

        # Sort muxed formats by resolution descending, prefer mp4
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

        # ── YouTube HD quality tiers via merged format strings ──────────────────
        # YouTube's HD formats (720p+) are always video-only streams.
        # We pair each mp4 video stream with the best m4a audio stream and
        # store the combined format_id (e.g. "399+140"). At download time the
        # proxy calls yt-dlp which uses ffmpeg to merge them into a single mp4.
        if platform == 'youtube' and video_only:
            # Find the best m4a audio-only format for clean mp4 output
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

                # Only mp4 video streams → clean mp4 output after ffmpeg merge
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
                        'url': vf['url'],       # unused — proxy uses original_url
                        'quality': f'{h}p',
                        'format': 'mp4',
                        'size': _format_size(total_size) if total_size else '',
                        'format_id': merged_id,
                    })

        # ── Pinterest: ensure at least one link via yt-dlp re-extract ────────
        # Pinterest downloads are always re-extracted server-side at click time,
        # so CDN URL accuracy here doesn't matter — we just need display entries.
        if platform == 'pinterest' and not links:
            all_formats = info.get('formats', [])
            _pinterest_direct_mp4(all_formats, links, seen_heights)
            # Last resort: single "Best Quality" entry — proxy handles fresh dl
            if not links:
                links.append({
                    'url': url,
                    'quality': 'Best Quality',
                    'format': 'mp4',
                    'size': '',
                    'format_id': None,
                })

        # Re-sort all links by resolution descending
        links.sort(
            key=lambda x: int(x['quality'].replace('p', '')) if x['quality'].endswith('p') else 0,
            reverse=True,
        )

        # Fallback: use the main URL if no formats were extracted
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

        # Fallback: try requested_formats (used by yt-dlp for merged formats)
        if not links and info.get('requested_formats'):
            for rf in info['requested_formats']:
                rf_url = rf.get('url')
                if not rf_url:
                    continue
                rf_vcodec = rf.get('vcodec', 'none')
                rf_acodec = rf.get('acodec', 'none')
                rf_has_video = rf_vcodec != 'none'
                rf_has_audio = rf_acodec != 'none'
                # Skip audio-only or video-only streams for Instagram;
                # only include formats that have both video and audio.
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

        # Instagram-specific fallback: use the main video URL which is usually muxed.
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
                seen_urls.add(main_url)

        # TikTok-specific fallback: the main URL from yt-dlp is usually a
        # muxed (video+audio) stream that works well for direct download.
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
                seen_urls.add(main_url)

        # Pinterest-specific fallback: if the main URL is a direct MP4, use it.
        # If it is an HLS manifest, try to derive a direct CDN MP4 URL from it.
        if not links and platform == 'pinterest':
            main_url = info.get('url', '')
            if main_url and main_url not in seen_urls:
                HLS_RE = re.compile(
                    r'(https://[^/]*\.pinimg\.com)/videos/(?:[^/]+/)*hls/(.+?)_\w+\.m3u8'
                )
                hls_m = HLS_RE.match(main_url)
                if hls_m:
                    cdn_base = hls_m.group(1)
                    video_hash = hls_m.group(2)
                    direct_url = f'{cdn_base}/videos/mc/720p/{video_hash}.mp4'
                    links.append({
                        'url': direct_url,
                        'quality': '720p',
                        'format': 'mp4',
                        'size': '',
                    })
                    seen_urls.add(direct_url)
                elif not main_url.endswith('.m3u8'):
                    height = info.get('height')
                    label = f"{height}p" if height else 'Best Quality'
                    pin_entry = {
                        'url': main_url,
                        'quality': label,
                        'format': info.get('ext', 'mp4'),
                        'size': _format_size(info.get('filesize') or info.get('filesize_approx')),
                    }
                    if info.get('format_id'):
                        pin_entry['format_id'] = info['format_id']
                    links.append(pin_entry)
                    seen_urls.add(main_url)

        # Facebook-specific fallback: try direct SD/HD URLs from info dict.
        # Include a format_id so the proxy can re-download via yt-dlp at
        # click time (avoiding CDN URL expiration that causes proxy.txt).
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
                    seen_urls.add(direct_url)

        if not links:
            return {'success': False, 'error': 'No downloadable video formats found.'}

        # Limit to top 6 qualities to keep UI clean
        links = links[:6]

        # Test each CDN URL concurrently and remove broken/expired ones.
        # This prevents XML error pages from reaching the user's browser.
        links = _filter_working_links(links, platform)

        if not links:
            return {'success': False, 'error': 'No working download links found for this video. Please try again.'}

        result = {
            'success': True,
            'title': title,
            'thumbnail': thumbnail,
            'links': links,
            'original_url': url,
        }

        if duration:
            minutes = int(duration // 60)
            seconds = int(duration % 60)
            result['duration'] = f"{minutes}:{seconds:02d}"

        return result

    except yt_dlp.utils.DownloadError as e:
        # If scraping already found links, use those despite yt-dlp failing
        if scraped_links:
            return {
                'success': True, 'title': 'Video', 'thumbnail': '',
                'links': scraped_links[:6], 'original_url': url,
            }
        error_msg = str(e)
        # Platform-specific human-readable errors
        if 'IP address is blocked' in error_msg or 'IP is blocked' in error_msg:
            return {'success': False, 'error': 'TikTok has blocked access from this server. Try again later or use a different network.'}
        if 'cookies' in error_msg.lower() or 'login' in error_msg.lower() or 'empty media response' in error_msg.lower():
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
            return {'success': False, 'error': 'Pinterest has blocked access from this server. Try opening the video in your browser and downloading it directly.'}
        if '404' in error_msg or 'not found' in error_msg.lower():
            return {'success': False, 'error': 'Video not found. The post may be private, deleted, or region-restricted.'}
        return {'success': False, 'error': 'Could not extract video. The post may be private or the platform blocked access.'}
    except Exception as e:
        if scraped_links:
            return {
                'success': True, 'title': 'Video', 'thumbnail': '',
                'links': scraped_links[:6], 'original_url': url,
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
        """Suppress default logging."""
        pass
