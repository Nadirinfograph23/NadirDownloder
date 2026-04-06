"""
YouTube download service — yt-dlp based, multi-client retry chain.

Key fixes:
- Uses mweb client first: no PO token needed, works on server IPs
- Skips HEAD-check validation on YouTube (googlevideo URLs fail HEAD requests
  without proper signed query params — they are valid but look broken)
- Proper merged format_id strings for video+audio HD qualities
- Handles nsig signature errors by falling back to alternate clients
"""

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
_UA_ANDROID = 'com.google.android.youtube/19.09.37 (Linux; U; Android 11) gzip'

# Ordered list of yt-dlp option sets to try for YouTube.
# mweb is first — it requires no PO token and is least affected by bot-detection
# on server-side IPs. tv_embedded is second. ios/android_vr third.
_YT_RETRY_SETS = [
    # 1. mweb — best for server-IPs, no PO token, direct CDN URLs
    {
        'http_headers': {'User-Agent': _UA_MOBILE},
        'extractor_args': {
            'youtube': {
                'player_client': ['mweb'],
            }
        },
        'age_limit': 99,
    },
    # 2. tv_embedded — bypasses bot-detection, skips most webpage checks
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
    # 3. ios + android_vr — direct CDN URLs, no signature needed
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
    # 4. android_vr alone — final fallback
    {
        'http_headers': {'User-Agent': _UA_ANDROID},
        'extractor_args': {
            'youtube': {
                'player_client': ['android_vr'],
            }
        },
        'age_limit': 99,
    },
]


def _format_size(filesize):
    if not filesize:
        return ''
    size_mb = filesize / (1024 * 1024)
    if size_mb >= 1:
        return f"{size_mb:.1f} MB"
    return f"{filesize / 1024:.0f} KB"


def extract_youtube(url, cookie_file=None):
    """
    Extract YouTube video info. Returns dict with success/links/title/thumbnail.
    Tries multiple yt-dlp client strategies in order.
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

    info = None
    last_exc = None

    for retry_set in _YT_RETRY_SETS:
        opts = {**base_opts, **retry_set}
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if info:
                    break
        except yt_dlp.utils.DownloadError as e:
            last_exc = e
            msg = str(e).lower()
            # If the video is genuinely unavailable/private, stop retrying
            if 'private video' in msg or 'video unavailable' in msg:
                break
            continue
        except Exception as e:
            last_exc = e
            continue

    if not info:
        err = str(last_exc) if last_exc else 'Could not extract YouTube video.'
        if 'sign in' in err.lower() or 'bot' in err.lower() or 'login' in err.lower():
            return {
                'success': False,
                'error': 'YouTube is temporarily blocking this server. Please try again in a few seconds.',
            }
        if 'private' in err.lower() or 'unavailable' in err.lower():
            return {'success': False, 'error': 'This video is private or unavailable.'}
        return {'success': False, 'error': 'Could not extract YouTube video. Please try again.'}

    title = info.get('title', 'YouTube Video')
    thumbnail = info.get('thumbnail', '')
    duration = info.get('duration')
    formats = info.get('formats', [])

    muxed = []      # formats with both video + audio
    video_only = [] # video-only formats (for HD merging)
    seen_urls = set()

    for f in formats:
        f_url = f.get('url')
        if not f_url or f_url in seen_urls:
            continue
        protocol = f.get('protocol', '')
        # Skip HLS/DASH manifests — we want direct CDN URLs
        if protocol in ('m3u8', 'm3u8_native', 'http_dash_segments', 'dash'):
            continue

        vcodec = f.get('vcodec', 'none')
        acodec = f.get('acodec', 'none')
        has_video = vcodec not in ('none', None)
        has_audio = acodec not in ('none', None)
        height = f.get('height')
        ext = f.get('ext', 'mp4')

        seen_urls.add(f_url)

        entry = {
            'url': f_url,
            'height': height,
            'ext': ext,
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

    # Build links from muxed formats (sorted best-first)
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
            'format': 'mp4' if vf['ext'] in ('mp4', 'webm', 'mkv') else 'mp4',
            'size': _format_size(vf['filesize']),
        }
        if vf.get('format_id'):
            entry['format_id'] = vf['format_id']
        links.append(entry)

    # Add HD video-only formats merged with best audio (for 1080p / 4K)
    if video_only:
        best_audio = None
        for f in formats:
            is_audio_only = (
                f.get('acodec', 'none') not in ('none', None) and
                f.get('vcodec', 'none') in ('none', None)
            )
            if is_audio_only and f.get('ext', '') in ('m4a', 'mp4', 'webm'):
                if best_audio is None or (f.get('abr') or 0) > (best_audio.get('abr') or 0):
                    best_audio = f

        if best_audio:
            audio_id = best_audio.get('format_id', '')
            audio_size = (best_audio.get('filesize') or best_audio.get('filesize_approx') or 0)

            yt_mp4 = [f for f in video_only if f.get('ext') == 'mp4']
            yt_mp4.sort(key=lambda x: x['height'] or 0, reverse=True)

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

    # Final fallback: use yt-dlp's best single URL
    if not links and info.get('url'):
        h = info.get('height')
        links.append({
            'url': info['url'],
            'quality': f"{h}p" if h else 'Best Quality',
            'format': info.get('ext', 'mp4'),
            'size': _format_size(info.get('filesize') or info.get('filesize_approx')),
        })

    if not links:
        return {'success': False, 'error': 'No downloadable formats found for this YouTube video.'}

    # Sort best quality first
    links.sort(
        key=lambda x: int(x['quality'].replace('p', '')) if x['quality'].endswith('p') else 0,
        reverse=True,
    )
    links = links[:6]

    result = {
        'success': True,
        'title': title,
        'thumbnail': thumbnail,
        'links': links,
        'platform': 'youtube',
    }
    if duration:
        result['duration'] = f"{int(duration // 60)}:{int(duration % 60):02d}"
    return result
