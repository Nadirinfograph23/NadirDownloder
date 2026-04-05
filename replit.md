# NADIR DOWNLOADER

A social media video downloader supporting Facebook, TikTok, YouTube, Instagram, Pinterest, and X (Twitter).

## Architecture

- **Frontend**: Static HTML/CSS/JS (`index.html`, `style.css`, `script.js`)
- **Backend**: Flask server (`server.py`) serving static files and API routes
- **API Handlers** (`api/`):
  - `download.py` — extracts video info and download links via yt-dlp / scraping
  - `proxy.py` — proxies video downloads server-side with platform-specific headers
  - `thumbnail.py` — proxies thumbnail images to bypass CORS/Referer restrictions

## Running

The app runs via Flask on port 5000:

```
python server.py
```

## Migration Notes

Originally a Vercel project with serverless Python functions (Vercel `BaseHTTPRequestHandler` style). Migrated to Replit with a unified Flask server (`server.py`) that wraps the same handler logic via `_run_handler()` adapter.

## Dependencies

- `flask` — web framework
- `yt-dlp` — video extraction
- `requests` — HTTP client
- `beautifulsoup4` — HTML parsing for Facebook/Pinterest scraping

## Supported Platforms

Facebook, TikTok, YouTube, Instagram, Pinterest, X (Twitter)
