"""
YouTube download service — uses ytdown.to API + process4.me.

Flow:
1. POST to https://app.ytdown.to/proxy.php with the YouTube URL
2. Get mediaItems list (Video MP4 entries per quality)
3. Poll each process4.me mediaUrl to get the final fileUrl
4. Return direct MP4 download links (no yt-dlp, no CDN expiry issues)

Retries: up to 3 attempts on the ytdown.to API.
Polling: up to 15 polls × 2s delay per quality (max ~30s per quality).
"""

import time
import requests as _requests

_UA = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/124.0.0.0 Safari/537.36'
)

_YTDOWN_URL = 'https://app.ytdown.to/proxy.php'
_YTDOWN_HEADERS = {
    'User-Agent': _UA,
    'Origin': 'https://app.ytdown.to',
    'Referer': 'https://app.ytdown.to/fr23/',
    'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
    'X-Requested-With': 'XMLHttpRequest',
    'Accept': '*/*',
}

_QUALITY_LABEL = {
    'FHD': '1080p',
    'HD':  '720p',
    'SD':  '480p',
}

_MAX_API_RETRIES = 3
_MAX_POLL_ATTEMPTS = 15
_POLL_DELAY = 2


def _poll_process4me(media_url, quality_label):
    """
    Poll a process4.me media URL until status=completed.
    Returns {'url': fileUrl, 'quality': quality_label, 'format': 'mp4', 'size': fileSize}
    or None on failure.
    """
    headers = {
        'User-Agent': _UA,
        'Referer': 'https://app.ytdown.to/',
        'Accept': 'application/json',
    }
    for _ in range(_MAX_POLL_ATTEMPTS):
        try:
            resp = _requests.get(media_url, headers=headers, timeout=15)
            if resp.status_code != 200:
                time.sleep(_POLL_DELAY)
                continue
            data = resp.json()
            status = data.get('status', '').lower()
            if status == 'completed':
                file_url = data.get('fileUrl', '')
                file_size = data.get('fileSize', '')
                if file_url:
                    return {
                        'url': file_url,
                        'quality': quality_label,
                        'format': 'mp4',
                        'size': file_size,
                    }
                return None
            if status in ('error', 'failed'):
                return None
            time.sleep(_POLL_DELAY)
        except Exception:
            time.sleep(_POLL_DELAY)
    return None


def _fetch_ytdown(url):
    """
    Call the ytdown.to proxy API and return a list of resolved download links.
    Returns (title, thumbnail, links) or raises an exception.
    """
    for attempt in range(1, _MAX_API_RETRIES + 1):
        try:
            resp = _requests.post(
                _YTDOWN_URL,
                data={'url': url},
                headers=_YTDOWN_HEADERS,
                timeout=30,
            )
            if resp.status_code != 200:
                if attempt < _MAX_API_RETRIES:
                    time.sleep(1)
                    continue
                raise RuntimeError(f'ytdown.to returned HTTP {resp.status_code}')

            raw = resp.text
            idx = raw.find('{')
            if idx < 0:
                raise RuntimeError('No JSON in response')

            data = resp.json() if idx == 0 else __import__('json').loads(raw[idx:])
            api = data.get('api', {})
            status = (api.get('status') or '').lower()

            if status == 'error':
                code = api.get('code', '')
                if code == 503:
                    raise RuntimeError('ytdown.to is in maintenance mode')
                raise RuntimeError(api.get('message') or 'Unknown error from ytdown.to')

            if api.get('service', '').upper() != 'YOUTUBE':
                raise RuntimeError('Not a YouTube URL')

            if status != 'ok':
                if attempt < _MAX_API_RETRIES:
                    time.sleep(2)
                    continue
                raise RuntimeError(f'Unexpected status: {status}')

            title = api.get('title') or 'YouTube Video'
            thumbnail = api.get('imagePreviewUrl') or ''

            # Filter only Video MP4 items
            media_items = api.get('mediaItems', [])
            video_items = [
                m for m in media_items
                if m.get('type') == 'Video' and
                   m.get('mediaExtension', '').upper() == 'MP4' and
                   m.get('mediaUrl')
            ]

            if not video_items:
                raise RuntimeError('No video MP4 formats found')

            # Resolve links (poll process4.me for each quality)
            links = []
            seen_qualities = set()
            for item in video_items:
                raw_quality = item.get('mediaQuality', '')
                # Map "FHD" → "1080p", "HD" → "720p", etc.
                # Also handle direct strings like "1080p"
                quality_label = _QUALITY_LABEL.get(raw_quality, raw_quality)
                if not quality_label:
                    quality_label = 'Best Quality'
                if quality_label in seen_qualities:
                    continue
                seen_qualities.add(quality_label)

                media_url = item.get('mediaUrl', '')
                task = item.get('mediaTask', '').lower()

                if task == 'download':
                    # Already a direct download link
                    links.append({
                        'url': media_url,
                        'quality': quality_label,
                        'format': 'mp4',
                        'size': item.get('mediaFileSize', ''),
                    })
                else:
                    # task=merge or render: poll process4.me
                    resolved = _poll_process4me(media_url, quality_label)
                    if resolved:
                        links.append(resolved)

                # Stop after getting top 4 qualities
                if len(links) >= 4:
                    break

            if not links:
                raise RuntimeError('All download links failed to resolve')

            return title, thumbnail, links

        except RuntimeError:
            raise
        except Exception as e:
            if attempt < _MAX_API_RETRIES:
                time.sleep(1)
                continue
            raise RuntimeError(str(e))

    raise RuntimeError('All ytdown.to attempts exhausted')


def extract_youtube(url, cookie_file=None):
    """
    Main entry point. Returns a dict with success/title/thumbnail/links.
    """
    try:
        title, thumbnail, links = _fetch_ytdown(url)
        return {
            'success': True,
            'title': title,
            'thumbnail': thumbnail,
            'platform': 'youtube',
            'links': links,
        }
    except RuntimeError as e:
        msg = str(e).lower()
        if 'unavailable' in msg or 'private' in msg:
            return {'success': False, 'error': 'This video is private or unavailable.'}
        if 'maintenance' in msg:
            return {'success': False, 'error': 'YouTube downloader is temporarily under maintenance. Please try again later.'}
        return {'success': False, 'error': f'Could not extract YouTube video. {e}'}
    except Exception as e:
        return {'success': False, 'error': f'Unexpected error: {e}'}
