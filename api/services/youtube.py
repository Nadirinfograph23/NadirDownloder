"""
YouTube download service — yt-dlp, single best link, no broken CDN URLs.

Strategy:
- Use yt-dlp to extract video info (title, thumbnail, duration).
- Return the ORIGINAL YouTube URL as the download target.
- The proxy re-extracts a fresh CDN URL at download time (same server IP).
- This avoids the cross-IP CDN URL expiry problem on Vercel serverless.

Format used: best[ext=mp4]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/best
Retry: up to 3 times across multiple yt-dlp player clients.
"""

import time
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

_FORMAT = 'best[ext=mp4]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/best'

_YT_CLIENT_SETS = [
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
    {
        'http_headers': {'User-Agent': _UA_DESKTOP},
        'age_limit': 99,
    },
]

_MAX_RETRIES = 3


def _format_duration(seconds):
    if not seconds:
        return ''
    return f"{int(seconds // 60)}:{int(seconds % 60):02d}"


def extract_youtube(url, cookie_file=None):
    """
    Extract YouTube video metadata and return ONE download link.
    The link URL is the original YouTube page URL — the proxy re-extracts
    a fresh CDN URL at download time using yt-dlp (same server IP, no expiry).
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
    if cookie_file:
        base_opts['cookiefile'] = cookie_file

    last_exc = None

    for attempt in range(1, _MAX_RETRIES + 1):
        for client_set in _YT_CLIENT_SETS:
            opts = {**base_opts, **client_set}
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    if not info:
                        continue

                    title = info.get('title', 'YouTube Video')
                    thumbnail = info.get('thumbnail', '')
                    duration = _format_duration(info.get('duration'))

                    result = {
                        'success': True,
                        'title': title,
                        'thumbnail': thumbnail,
                        'platform': 'youtube',
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
                    if duration:
                        result['duration'] = duration
                    return result

            except yt_dlp.utils.DownloadError as e:
                last_exc = e
                msg = str(e).lower()
                if 'private video' in msg or 'video unavailable' in msg:
                    return {'success': False, 'error': 'This video is private or unavailable.'}
                continue
            except Exception as e:
                last_exc = e
                continue

        if attempt < _MAX_RETRIES:
            time.sleep(1)

    err = str(last_exc) if last_exc else ''
    if 'sign in' in err.lower() or 'bot' in err.lower() or 'login' in err.lower():
        return {
            'success': False,
            'error': 'YouTube is temporarily blocking this server. Please try again in a few seconds.',
        }
    if 'private' in err.lower() or 'unavailable' in err.lower():
        return {'success': False, 'error': 'This video is private or unavailable.'}

    return {'success': False, 'error': 'Could not extract video info. Please try again.'}
