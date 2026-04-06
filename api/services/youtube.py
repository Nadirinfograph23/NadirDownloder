"""
YouTube download service — yt-dlp with URL validation.

- Multi-client retry chain: mweb -> tv_embedded -> ios/android_vr -> android_vr
- Each extracted URL is validated (HEAD request: status=200, Content-Length>0)
- Broken / expired / 403 URLs are removed before returning
- Extraction retried up to 3 times across client chain if no valid links found
"""

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
    'Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) '
    'AppleWebKit/605.1.15 (KHTML, like Gecko) '
    'Version/17.4 Mobile/15E148 Safari/604.1'
)
_UA_ANDROID = 'com.google.android.youtube/19.09.37 (Linux; U; Android 11) gzip'

_YT_CLIENT_SETS = [
    {
        'http_headers': {'User-Agent': _UA_MOBILE},
        'extractor_args': {'youtube': {'player_client': ['mweb']}},
        'age_limit': 99,
    },
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
    {
        'http_headers': {'User-Agent': _UA_ANDROID},
        'extractor_args': {'youtube': {'player_client': ['android_vr']}},
        'age_limit': 99,
    },
]

_MAX_EXTRACT_RETRIES = 3


def _format_size(filesize):
    if not filesize:
        return ''
    mb = filesize / (1024 * 1024)
    return f"{mb:.1f} MB" if mb >= 1 else f"{filesize / 1024:.0f} KB"


def _validate_url(url, timeout=8):
    """
    Return True if the URL is reachable and has content.
    Uses HEAD first; falls back to GET with stream=True if HEAD returns
    a non-standard status (some CDNs return 403 on HEAD but 200 on GET).
    """
    headers = {'User-Agent': _UA_DESKTOP}
    try:
        r = _requests.head(url, headers=headers, timeout=timeout, allow_redirects=True)
        if r.status_code == 200:
            cl = int(r.headers.get('Content-Length', 0) or 0)
            return cl > 0
        if r.status_code in (403, 405, 501):
            # Try GET with stream to avoid downloading the body
            r2 = _requests.get(url, headers=headers, timeout=timeout,
                               stream=True, allow_redirects=True)
            if r2.status_code == 200:
                cl = int(r2.headers.get('Content-Length', 0) or 0)
                r2.close()
                return cl > 0
            r2.close()
    except Exception:
        pass
    return False


def _validate_links_parallel(links, max_workers=6):
    """Validate a list of link dicts in parallel; return only valid ones."""
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


def _extract_info_once(url, base_opts, client_set):
    opts = {**base_opts, **client_set}
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)


def _build_links(info):
    """Parse yt-dlp info dict into a list of candidate link dicts."""
    formats = info.get('formats', [])
    muxed = []
    video_only = []
    seen_urls = set()

    for f in formats:
        f_url = f.get('url')
        if not f_url or f_url in seen_urls:
            continue
        protocol = f.get('protocol', '')
        if protocol in ('m3u8', 'm3u8_native', 'http_dash_segments', 'dash'):
            continue

        vcodec = f.get('vcodec', 'none')
        acodec = f.get('acodec', 'none')
        has_video = vcodec not in ('none', None)
        has_audio = acodec not in ('none', None)
        height = f.get('height')
        seen_urls.add(f_url)

        entry = {
            'url': f_url,
            'height': height,
            'ext': f.get('ext', 'mp4'),
            'filesize': f.get('filesize') or f.get('filesize_approx'),
            'has_audio': has_audio,
            'has_video': has_video,
            'tbr': f.get('tbr') or 0,
            'format_id': f.get('format_id', ''),
            'format_note': f.get('format_note', ''),
            'abr': f.get('abr') or 0,
        }

        if has_video and has_audio:
            muxed.append(entry)
        elif has_video and not has_audio:
            video_only.append(entry)

    muxed.sort(key=lambda x: (x['height'] or 0, x['tbr']), reverse=True)
    links = []
    seen_heights = set()

    for vf in muxed:
        h = vf['height']
        if h in seen_heights:
            continue
        seen_heights.add(h)
        label = f"{h}p" if h else vf.get('format_note') or 'Video'
        entry = {
            'url': vf['url'],
            'quality': label,
            'format': 'mp4',
            'size': _format_size(vf['filesize']),
        }
        if vf.get('format_id'):
            entry['format_id'] = vf['format_id']
        links.append(entry)

    # HD video-only + best audio (for 1080p / 4K)
    if video_only:
        best_audio = None
        for f in formats:
            is_audio = (
                f.get('acodec', 'none') not in ('none', None) and
                f.get('vcodec', 'none') in ('none', None)
            )
            if is_audio and f.get('ext', '') in ('m4a', 'mp4', 'webm'):
                if best_audio is None or (f.get('abr') or 0) > (best_audio.get('abr') or 0):
                    best_audio = f

        if best_audio:
            audio_id = best_audio.get('format_id', '')
            audio_size = best_audio.get('filesize') or best_audio.get('filesize_approx') or 0
            yt_mp4 = sorted(
                [f for f in video_only if f.get('ext') == 'mp4'],
                key=lambda x: x['height'] or 0, reverse=True
            )
            for vf in yt_mp4:
                h = vf['height']
                if not h or h in seen_heights:
                    continue
                seen_heights.add(h)
                vid_id = vf.get('format_id', '')
                merged_id = f'{vid_id}+{audio_id}' if vid_id and audio_id else vid_id
                total_size = (vf.get('filesize') or 0) + audio_size
                links.append({
                    'url': vf['url'],
                    'quality': f'{h}p',
                    'format': 'mp4',
                    'size': _format_size(total_size) if total_size else '',
                    'format_id': merged_id,
                })

    if not links and info.get('url'):
        h = info.get('height')
        links.append({
            'url': info['url'],
            'quality': f"{h}p" if h else 'Best Quality',
            'format': info.get('ext', 'mp4'),
            'size': _format_size(info.get('filesize') or info.get('filesize_approx')),
        })

    links.sort(
        key=lambda x: int(x['quality'].replace('p', '')) if x['quality'].endswith('p') else 0,
        reverse=True,
    )
    return links[:6]


def extract_youtube(url, cookie_file=None):
    """
    Extract YouTube video. Returns only validated (status=200, Content-Length>0) links.
    Retries extraction up to _MAX_EXTRACT_RETRIES times across client chain.
    """
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

    last_exc = None

    for attempt in range(1, _MAX_EXTRACT_RETRIES + 1):
        info = None

        for client_set in _YT_CLIENT_SETS:
            try:
                info = _extract_info_once(url, base_opts, client_set)
                if info:
                    break
            except yt_dlp.utils.DownloadError as e:
                last_exc = e
                msg = str(e).lower()
                if 'private video' in msg or 'video unavailable' in msg:
                    return {'success': False, 'error': 'This video is private or unavailable.'}
                continue
            except Exception as e:
                last_exc = e
                continue

        if not info:
            if attempt < _MAX_EXTRACT_RETRIES:
                time.sleep(1)
            continue

        # Build candidate links
        candidates = _build_links(info)

        if not candidates:
            if attempt < _MAX_EXTRACT_RETRIES:
                time.sleep(1)
            continue

        # Validate each URL — remove broken / 403 / expired ones
        valid_links = _validate_links_parallel(candidates)

        if valid_links:
            result = {
                'success': True,
                'title': info.get('title', 'YouTube Video'),
                'thumbnail': info.get('thumbnail', ''),
                'links': valid_links,
                'platform': 'youtube',
            }
            dur = info.get('duration')
            if dur:
                result['duration'] = f"{int(dur // 60)}:{int(dur % 60):02d}"
            return result

        # All links failed validation — retry extraction
        if attempt < _MAX_EXTRACT_RETRIES:
            time.sleep(1)

    # All attempts exhausted
    err = str(last_exc) if last_exc else ''
    if 'sign in' in err.lower() or 'bot' in err.lower() or 'login' in err.lower():
        return {
            'success': False,
            'error': 'YouTube is temporarily blocking this server. Please try again in a few seconds.',
        }
    if 'private' in err.lower() or 'unavailable' in err.lower():
        return {'success': False, 'error': 'This video is private or unavailable.'}

    return {'success': False, 'error': 'No valid download links found. Please try again.'}
