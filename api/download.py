"""
NADIR DOWNLOADER - Video Download API
Uses direct page scraping (Facebook, Pinterest) and yt-dlp (other platforms)
to extract video download links from social media platforms.
"""

from http.server import BaseHTTPRequestHandler
import json
import re
import urllib.parse
import yt_dlp
import requests as _requests
from bs4 import BeautifulSoup as _BS


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


def _fetch_pinterest_video(url):
    """
    Extract Pinterest video links via savepin.app — the same service used by
    the reference repo (milancodess/universalDownloader).

    Sends the Pinterest / pin.it URL to savepin.app's download endpoint and
    parses the returned HTML table for direct MP4 CDN links.
    Returns a list of link dicts [{url, quality, format, size}].
    """
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

    # --- Fast platform-specific extraction (Facebook / Pinterest) ---
    # These are tried first because they are faster and more reliable than
    # running yt-dlp for these platforms.
    scraped_links = []
    if platform == 'facebook':
        scraped_links = _fetch_facebook_video(url)
    elif platform == 'pinterest':
        scraped_links = _fetch_pinterest_video(url)

    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'noplaylist': True,
        'socket_timeout': 15,
        'extractor_retries': 2,
    }

    # TikTok needs specific headers to return valid download URLs
    if platform == 'tiktok':
        ydl_opts['http_headers'] = {
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/120.0.0.0 Safari/537.36'
            ),
            'Referer': 'https://www.tiktok.com/',
        }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

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

        # For Pinterest: when only HLS streams are available (no direct
        # muxed formats), construct direct MP4 URLs from Pinterest's CDN.
        # The CDN path mc/720p/<hash>.mp4 serves a muxed file (video+audio)
        # that can be proxied without needing ffmpeg to merge streams.
        # Also include ALL formats (including HLS) in the search so that
        # pin.it short-URL redirects (which produce only HLS entries) are covered.
        if platform == 'pinterest' and not links:
            all_formats = info.get('formats', [])
            _pinterest_direct_mp4(all_formats, links, seen_heights)

        # For Facebook, Instagram, and TikTok: never add video-only
        # formats (they have no audio and would produce silent videos).
        # For other platforms: add video-only as fallback if fewer than 3 muxed.
        if platform not in ('facebook', 'instagram', 'tiktok', 'pinterest') and len(links) < 3:
            video_only.sort(
                key=lambda x: (x['height'] or 0, x['ext'] == 'mp4', x['tbr']),
                reverse=True,
            )
            for vf in video_only:
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
        if not links and platform == 'facebook':
            # Try the direct webpage URLs (sd_url / hd_url) that Facebook
            # sometimes exposes — these are typically muxed.
            for key in ('sd_url', 'hd_url'):
                direct_url = info.get(key)
                if direct_url and direct_url not in seen_urls:
                    links.append({
                        'url': direct_url,
                        'quality': 'HD' if 'hd' in key else 'SD',
                        'format': 'mp4',
                        'size': '',
                    })
                    seen_urls.add(direct_url)

        if not links:
            return {'success': False, 'error': 'No downloadable video formats found.'}

        # Limit to top 6 qualities to keep UI clean
        links = links[:6]

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
        if 'Private' in error_msg or 'private' in error_msg:
            return {'success': False, 'error': 'This video is private or unavailable.'}
        if 'not found' in error_msg.lower() or '404' in error_msg:
            return {'success': False, 'error': 'Video not found. Please check the URL.'}
        return {'success': False, 'error': 'Could not extract video. Please check the URL and try again.'}
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
