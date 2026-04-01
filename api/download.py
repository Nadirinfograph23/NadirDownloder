"""
NADIR DOWNLOADER - Video Download API
Uses yt-dlp to extract video info and download links from social media platforms.
Deployed as a Vercel Python serverless function.
"""

from http.server import BaseHTTPRequestHandler
import json
import re
import yt_dlp


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

    The ``mc/720p`` MP4 already contains both video and audio, so it can
    be proxied directly without needing ffmpeg to merge separate streams.
    """
    # Extract the video hash from any HLS manifest URL.
    video_hash = None
    best_height = None
    for f in formats:
        f_url = f.get('url', '')
        m = re.match(
            r'https://v\d+\.pinimg\.com/videos/iht/hls/(.+?)_\w+\.m3u8',
            f_url,
        )
        if m:
            video_hash = m.group(1)
            h = f.get('height')
            if h and (best_height is None or h > best_height):
                best_height = h
            break

    if not video_hash:
        return

    direct_url = (
        f'https://v1.pinimg.com/videos/mc/720p/{video_hash}.mp4'
    )
    label = f'{best_height}p' if best_height else '720p'
    if best_height not in seen_heights:
        seen_heights.add(best_height)
        links.append({
            'url': direct_url,
            'quality': label,
            'format': 'mp4',
            'size': '',
        })


def extract_video_info(url):
    """Use yt-dlp to extract video info and available formats."""
    platform = detect_platform(url)

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
            return {'success': False, 'error': 'Could not extract video information.'}

        title = info.get('title', 'Video')
        thumbnail = info.get('thumbnail', '')
        duration = info.get('duration')
        formats = info.get('formats', [])

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
        if platform == 'pinterest' and not links:
            _pinterest_direct_mp4(formats, links, seen_heights)

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

        # Pinterest-specific fallback: use the main video URL which is
        # typically a muxed stream with both video and audio.
        if not links and platform == 'pinterest' and info.get('url'):
            main_url = info['url']
            if main_url not in seen_urls:
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
        error_msg = str(e)
        if 'Private' in error_msg or 'private' in error_msg:
            return {'success': False, 'error': 'This video is private or unavailable.'}
        if 'not found' in error_msg.lower() or '404' in error_msg:
            return {'success': False, 'error': 'Video not found. Please check the URL.'}
        return {'success': False, 'error': 'Could not extract video. Please check the URL and try again.'}
    except Exception as e:
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
