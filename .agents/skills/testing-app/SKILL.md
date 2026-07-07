# Testing NadirDownloder

## Overview
NadirDownloder is a video downloader web app with a static frontend (index.html, script.js, style.css) and Python serverless API endpoints (api/download.py for metadata extraction, api/proxy.py for downloading videos).

## Local Testing Setup

The Vercel preview URL may require authentication (returns 401). To test locally:

1. Create a test server script that serves static files from the repo root AND handles `/api/download` (POST) and `/api/proxy` (GET) endpoints
2. Import `extract_video_info` and `detect_platform` from `api/download.py`
3. For the proxy endpoint, implement the yt-dlp download logic from `api/proxy.py`
4. Run on `localhost:8080`

The test server needs to handle:
- POST `/api/download` — calls `extract_video_info(url)` and returns JSON
- GET `/api/proxy?url=...&platform=...&format_id=...&filename=...&format=...` — downloads via yt-dlp and streams back

## Test URLs

Confirmed working test URLs (as of April 2026):
- **TikTok**: `https://www.tiktok.com/@scout2015/video/6718335390845095173` — short video (10s), produces HEVC 720x1280 + AAC audio
- **Pinterest**: `https://www.pinterest.com/pin/85779567898252217/` — cooking video (36s), produces H.264 720x1280 + AAC audio

Note: Pinterest video pins can be hard to find. Search for pins with `[Video]` in the title. Many Pinterest pin URLs return 404 from yt-dlp. Test with `yt_dlp.YoutubeDL({'skip_download': True}).extract_info(url)` first.

## Platform-Specific Quirks

### TikTok
- CDN URLs from yt-dlp return **403 Forbidden** when accessed via raw HTTP
- TikTok requires session cookies/auth tokens that yt-dlp manages internally
- Downloads must go through yt-dlp (not direct HTTP fetch)
- The proxy uses `original_url` + `format_id` to let yt-dlp handle the download

### Pinterest
- yt-dlp returns mostly **HLS (m3u8_native)** streams which may be filtered out by the format processing code
- The `V_720P` format is a direct MP4 but reports `vcodec=None` / `acodec=None` — needs special handling
- Pinterest might not have `info['url']` set (returns None), so fallback paths that check `info.get('url')` won't work
- Downloads route through the yt-dlp proxy path similar to TikTok

## Verifying Downloads

Use ffprobe to verify downloaded files:
```python
import os, subprocess, json
f = 'FILEPATH'
size = os.path.getsize(f)
with open(f,'rb') as fh: magic = fh.read(12)
is_mp4 = magic[4:8] == b'ftyp'
result = subprocess.run(['ffprobe','-v','quiet','-print_format','json','-show_streams',f], capture_output=True, text=True)
data = json.loads(result.stdout) if result.returncode == 0 else {}
for s in data.get('streams',[]):
    print(f'{s["codec_type"]} codec={s["codec_name"]} {s.get("width","")}x{s.get("height","")} dur={s.get("duration","?")}')
print(f'Size: {size} bytes, MP4: {is_mp4}')
```

A valid download should have:
- ftyp MP4 header
- At least one video stream (hevc or h264)
- At least one audio stream (aac)
- Non-zero duration
- File size > 100KB

## Vercel Limitations

- **Response body size limit**: Vercel Hobby plan caps responses at ~4.5MB. Large videos will be truncated/corrupted. Consider testing with short videos.
- **Function timeout**: Serverless functions have a timeout (default 10s on Hobby). yt-dlp downloads may exceed this for large videos.

## Chrome Download Location

When testing in the Devin environment, Chrome downloads go to `/tmp/playwright-artifacts-*/` (not `~/Downloads/`). Use `find /tmp -name "<uuid>" 2>/dev/null` to locate downloaded files.

## Devin Secrets Needed

No secrets are needed for testing this app. The video downloader works with public URLs and doesn't require authentication.
