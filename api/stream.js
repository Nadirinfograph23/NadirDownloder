/**
 * NADIR DOWNLOADER - Video Stream Proxy
 * Vercel Edge Function that proxies video downloads with Content-Disposition headers,
 * forcing the browser to download the file instead of playing it in a new tab.
 */

export const config = {
  runtime: 'edge',
};

/** Allowed CDN hostname patterns to prevent open-proxy abuse. */
const ALLOWED_HOSTS = [
  /\.googlevideo\.com$/,
  /\.youtube\.com$/,
  /\.ytimg\.com$/,
  /\.tiktokcdn\.com$/,
  /\.tiktokcdn-us\.com$/,
  /\.muscdn\.com$/,
  /\.fbcdn\.net$/,
  /\.cdninstagram\.com$/,
  /\.pinimg\.com$/,
  /\.twimg\.com$/,
  /\.pstatic\.net$/,
  /\.sndcdn\.com$/,
  /\.tiktokv\.com$/,
];

function isAllowedUrl(urlStr) {
  try {
    const u = new URL(urlStr);
    if (u.protocol !== 'https:' && u.protocol !== 'http:') return false;
    return ALLOWED_HOSTS.some((re) => re.test(u.hostname));
  } catch {
    return false;
  }
}

function sanitizeFilename(name) {
  return name
    .replace(/[<>:"/\\|?*\x00-\x1f]/g, '_')
    .replace(/\s+/g, '_')
    .replace(/_{2,}/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 200);
}

export default async function handler(request) {
  // Only allow GET
  if (request.method === 'OPTIONS') {
    return new Response(null, {
      status: 204,
      headers: {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET, OPTIONS',
      },
    });
  }

  const { searchParams } = new URL(request.url);
  const videoUrl = searchParams.get('url');
  const rawFilename = searchParams.get('filename') || 'video.mp4';
  const filename = sanitizeFilename(rawFilename);

  if (!videoUrl) {
    return new Response(JSON.stringify({ error: 'Missing url parameter' }), {
      status: 400,
      headers: { 'Content-Type': 'application/json' },
    });
  }

  if (!isAllowedUrl(videoUrl)) {
    return new Response(JSON.stringify({ error: 'URL not allowed' }), {
      status: 403,
      headers: { 'Content-Type': 'application/json' },
    });
  }

  try {
    const upstream = await fetch(videoUrl, {
      headers: {
        'User-Agent':
          'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        Referer: videoUrl,
      },
    });

    if (!upstream.ok) {
      return new Response(
        JSON.stringify({ error: `Upstream returned ${upstream.status}` }),
        {
          status: 502,
          headers: { 'Content-Type': 'application/json' },
        }
      );
    }

    const headers = new Headers();
    headers.set(
      'Content-Disposition',
      `attachment; filename="${filename}"; filename*=UTF-8''${encodeURIComponent(filename)}`
    );
    headers.set(
      'Content-Type',
      upstream.headers.get('Content-Type') || 'video/mp4'
    );
    if (upstream.headers.get('Content-Length')) {
      headers.set('Content-Length', upstream.headers.get('Content-Length'));
    }
    headers.set('Access-Control-Allow-Origin', '*');
    headers.set('Cache-Control', 'no-store');

    return new Response(upstream.body, { status: 200, headers });
  } catch (err) {
    return new Response(
      JSON.stringify({ error: 'Failed to fetch video from source' }),
      {
        status: 502,
        headers: { 'Content-Type': 'application/json' },
      }
    );
  }
}
