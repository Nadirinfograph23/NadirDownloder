const https = require('https');
const http = require('http');
const { URL } = require('url');

// Platform detection
function detectPlatform(url) {
    const normalized = url.toLowerCase();
    if (/facebook\.com|fb\.com|fb\.watch|fbcdn\.net/.test(normalized)) return 'facebook';
    if (/tiktok\.com|vm\.tiktok\.com/.test(normalized)) return 'tiktok';
    if (/youtube\.com|youtu\.be|yt\.be/.test(normalized)) return 'youtube';
    if (/instagram\.com|instagr\.am/.test(normalized)) return 'instagram';
    if (/pinterest\.com|pin\.it/.test(normalized)) return 'pinterest';
    if (/twitter\.com|x\.com|t\.co/.test(normalized)) return 'twitter';
    return null;
}

// Make HTTP request helper
function makeRequest(options, postData) {
    return new Promise((resolve, reject) => {
        const protocol = options.protocol === 'http:' ? http : https;
        const req = protocol.request(options, (res) => {
            let data = '';
            // Handle redirects
            if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
                const redirectUrl = new URL(res.headers.location, `${options.protocol}//${options.hostname}`);
                const newOptions = {
                    hostname: redirectUrl.hostname,
                    port: redirectUrl.port,
                    path: redirectUrl.pathname + redirectUrl.search,
                    method: options.method,
                    headers: options.headers,
                    protocol: redirectUrl.protocol
                };
                return resolve(makeRequest(newOptions, postData));
            }
            res.on('data', (chunk) => { data += chunk; });
            res.on('end', () => resolve({ statusCode: res.statusCode, headers: res.headers, body: data }));
        });
        req.on('error', reject);
        req.setTimeout(20000, () => { req.destroy(); reject(new Error('Request timeout')); });
        if (postData) req.write(postData);
        req.end();
    });
}

// Helper: sleep for polling
function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

// =============================================
// Facebook downloader via snapsave.io
// =============================================
async function downloadFacebook(videoUrl) {
    try {
        const postData = `url=${encodeURIComponent(videoUrl)}&q_auto=0`;
        const response = await makeRequest({
            hostname: 'snapsave.io',
            path: '/api/ajaxSearch',
            method: 'POST',
            protocol: 'https:',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
                'Content-Length': Buffer.byteLength(postData),
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
                'Referer': 'https://snapsave.io/',
                'Origin': 'https://snapsave.io',
                'Accept': '*/*',
                'Accept-Language': 'en-US,en;q=0.9'
            }
        }, postData);

        const body = response.body;
        const links = [];
        let data;
        try { data = JSON.parse(body); } catch (e) { data = null; }

        // Try JSON response with data field containing HTML
        if (data && data.data) {
            const html = data.data;
            const hrefMatches = html.match(/href="(https?:\/\/[^"]+)"/gi);
            if (hrefMatches) {
                hrefMatches.forEach((match, i) => {
                    const url = match.match(/href="([^"]+)"/)[1];
                    if (url.includes('.mp4') || url.includes('video') || url.includes('fbcdn')) {
                        links.push({ url: url, quality: i === 0 ? 'HD' : 'SD', format: 'mp4' });
                    }
                });
            }
        }

        // Try to extract mp4 URLs directly
        if (links.length === 0) {
            const urlMatches = body.match(/https?:\/\/[^\s"'<>]+\.mp4[^\s"'<>]*/gi);
            if (urlMatches) {
                const unique = [...new Set(urlMatches)];
                unique.forEach((url, i) => {
                    links.push({ url: url, quality: i === 0 ? 'HD' : 'SD', format: 'mp4' });
                });
            }
        }

        // Try decoding encoded response
        if (links.length === 0) {
            const encodedMatch = body.match(/decodeURIComponent\(escape\(atob\("([^"]+)"\)\)\)/);
            if (encodedMatch) {
                const decoded = Buffer.from(encodedMatch[1], 'base64').toString();
                const decodedUrls = decoded.match(/https?:\/\/[^\s"'<>]+\.mp4[^\s"'<>]*/gi);
                if (decodedUrls) {
                    const unique = [...new Set(decodedUrls)];
                    unique.forEach((url, i) => {
                        links.push({ url: url, quality: i === 0 ? 'HD' : 'SD', format: 'mp4' });
                    });
                }
            }
        }

        if (links.length > 0) return { success: true, links };
        return { success: false, error: 'Could not extract download links. The video may be private or unavailable.' };
    } catch (err) {
        return { success: false, error: 'Facebook download service error: ' + err.message };
    }
}

// =============================================
// TikTok downloader via tikwm.com
// =============================================
async function downloadTiktok(videoUrl) {
    try {
        const postData = `url=${encodeURIComponent(videoUrl)}&count=12&cursor=0&web=1&hd=1`;
        const response = await makeRequest({
            hostname: 'www.tikwm.com',
            path: '/api/',
            method: 'POST',
            protocol: 'https:',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
                'Content-Length': Buffer.byteLength(postData),
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
                'Accept': 'application/json, text/javascript, */*; q=0.01',
                'Origin': 'https://www.tikwm.com',
                'Referer': 'https://www.tikwm.com/'
            }
        }, postData);

        let data;
        try { data = JSON.parse(response.body); } catch (e) { data = null; }

        const links = [];

        if (data && data.code === 0 && data.data) {
            const d = data.data;
            const base = 'https://www.tikwm.com';
            if (d.hdplay) {
                const hdUrl = d.hdplay.startsWith('http') ? d.hdplay : base + d.hdplay;
                links.push({ url: hdUrl, quality: 'HD (No Watermark)', format: 'mp4' });
            }
            if (d.play) {
                const playUrl = d.play.startsWith('http') ? d.play : base + d.play;
                links.push({ url: playUrl, quality: 'No Watermark', format: 'mp4' });
            }
            if (d.wmplay) {
                const wmUrl = d.wmplay.startsWith('http') ? d.wmplay : base + d.wmplay;
                links.push({ url: wmUrl, quality: 'With Watermark', format: 'mp4' });
            }
            if (d.music) {
                const musicUrl = d.music.startsWith('http') ? d.music : base + d.music;
                links.push({ url: musicUrl, quality: 'Audio Only', format: 'mp3' });
            }

            const title = d.title || '';
            const thumbnail = d.cover || d.origin_cover || '';

            if (links.length > 0) {
                return { success: true, links, title, thumbnail };
            }
        }

        return { success: false, error: 'Could not extract TikTok download links. The video may be private.' };
    } catch (err) {
        return { success: false, error: 'TikTok download service error: ' + err.message };
    }
}

// =============================================
// TikTok downloader via snaptik (backup)
// =============================================
async function downloadTiktokSnaptik(videoUrl) {
    try {
        const pageResponse = await makeRequest({
            hostname: 'snaptik.app',
            path: '/fr2',
            method: 'GET',
            protocol: 'https:',
            headers: {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
            }
        });

        const tokenMatch = pageResponse.body.match(/name="token"\s+value="([^"]+)"/);
        const token = tokenMatch ? tokenMatch[1] : '';

        const postData = `url=${encodeURIComponent(videoUrl)}&token=${encodeURIComponent(token)}`;
        const response = await makeRequest({
            hostname: 'snaptik.app',
            path: '/abc2.php',
            method: 'POST',
            protocol: 'https:',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
                'Content-Length': Buffer.byteLength(postData),
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
                'Referer': 'https://snaptik.app/fr2',
                'Origin': 'https://snaptik.app'
            }
        }, postData);

        const body = response.body;
        const links = [];

        const urlMatches = body.match(/https?:\/\/[^\s"'<>\\]+\.mp4[^\s"'<>\\]*/gi);
        if (urlMatches) {
            const unique = [...new Set(urlMatches)];
            unique.forEach((url, i) => {
                links.push({ url: url, quality: i === 0 ? 'No Watermark' : 'With Watermark', format: 'mp4' });
            });
        }

        const encodedMatches = body.match(/atob\("([^"]+)"\)/g);
        if (encodedMatches) {
            encodedMatches.forEach(match => {
                const b64 = match.match(/atob\("([^"]+)"\)/);
                if (b64) {
                    try {
                        const decoded = Buffer.from(b64[1], 'base64').toString();
                        const decodedUrls = decoded.match(/https?:\/\/[^\s"'<>]+\.mp4[^\s"'<>]*/gi);
                        if (decodedUrls) {
                            decodedUrls.forEach(url => {
                                if (!links.find(l => l.url === url)) {
                                    links.push({ url: url, quality: 'Video', format: 'mp4' });
                                }
                            });
                        }
                    } catch (e) {}
                }
            });
        }

        if (links.length > 0) return { success: true, links };
        return { success: false, error: 'Could not extract TikTok download links via snaptik.' };
    } catch (err) {
        return { success: false, error: 'TikTok snaptik service error: ' + err.message };
    }
}

// =============================================
// YouTube downloader via loader.to
// =============================================
async function downloadYoutube(videoUrl) {
    try {
        // Step 1: Submit the download request
        const submitResponse = await makeRequest({
            hostname: 'loader.to',
            path: '/ajax/download.php?format=1080&url=' + encodeURIComponent(videoUrl),
            method: 'GET',
            protocol: 'https:',
            headers: {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
                'Accept': 'application/json, text/javascript, */*; q=0.01',
                'Referer': 'https://loader.to/',
                'Origin': 'https://loader.to'
            }
        });

        let submitData;
        try { submitData = JSON.parse(submitResponse.body); } catch (e) { submitData = null; }

        if (!submitData || !submitData.success || !submitData.id) {
            return { success: false, error: 'YouTube download service: failed to submit request.' };
        }

        const jobId = submitData.id;

        // Step 2: Poll for progress (max 30 seconds)
        let downloadUrl = null;
        for (let i = 0; i < 15; i++) {
            await sleep(2000);

            const progressResponse = await makeRequest({
                hostname: 'loader.to',
                path: '/ajax/progress.php?id=' + jobId,
                method: 'GET',
                protocol: 'https:',
                headers: {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
                    'Accept': 'application/json',
                    'Referer': 'https://loader.to/'
                }
            });

            let progressData;
            try { progressData = JSON.parse(progressResponse.body); } catch (e) { progressData = null; }

            if (progressData && progressData.success === 1 && progressData.download_url) {
                downloadUrl = progressData.download_url;
                break;
            }

            // success:1 with no download_url means conversion failed
            if (progressData && progressData.success === 1 && !progressData.download_url) {
                break;
            }

            // success:0 with progress > 0 means still processing - continue polling
            // success:0 with progress === 0 and no text means genuine failure
            if (progressData && progressData.success === 0 && progressData.progress === 0) {
                break;
            }
        }

        if (!downloadUrl) {
            return { success: false, error: 'YouTube download: conversion timed out or failed.' };
        }

        const links = [
            { url: downloadUrl, quality: '1080p', format: 'mp4' }
        ];

        // Get metadata via noembed
        let title = '';
        let thumbnail = '';
        try {
            const metaResponse = await makeRequest({
                hostname: 'noembed.com',
                path: '/embed?url=' + encodeURIComponent(videoUrl),
                method: 'GET',
                protocol: 'https:',
                headers: {
                    'User-Agent': 'Mozilla/5.0',
                    'Accept': 'application/json'
                }
            });
            let meta;
            try { meta = JSON.parse(metaResponse.body); } catch (e) { meta = null; }
            if (meta) {
                title = meta.title || '';
                thumbnail = meta.thumbnail_url || '';
            }
        } catch (e) {}

        return { success: true, links, title, thumbnail };
    } catch (err) {
        return { success: false, error: 'YouTube download service error: ' + err.message };
    }
}

// =============================================
// Instagram downloader via snapsave.io
// =============================================
async function downloadInstagram(videoUrl) {
    try {
        const postData = `url=${encodeURIComponent(videoUrl)}&q_auto=0`;
        const response = await makeRequest({
            hostname: 'snapsave.io',
            path: '/api/ajaxSearch',
            method: 'POST',
            protocol: 'https:',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
                'Content-Length': Buffer.byteLength(postData),
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
                'Referer': 'https://snapsave.io/',
                'Origin': 'https://snapsave.io',
                'Accept': '*/*',
                'Accept-Language': 'en-US,en;q=0.9'
            }
        }, postData);

        const body = response.body;
        const links = [];
        let data;
        try { data = JSON.parse(body); } catch (e) { data = null; }

        if (data && data.data) {
            const html = data.data;
            const hrefMatches = html.match(/href="(https?:\/\/[^"]+)"/gi);
            if (hrefMatches) {
                hrefMatches.forEach((match, i) => {
                    const url = match.match(/href="([^"]+)"/)[1];
                    if (url.includes('instagram') || url.includes('cdninstagram') || url.includes('.mp4') || url.includes('.jpg') || url.includes('fbcdn')) {
                        links.push({ url: url, quality: 'Download ' + (i + 1), format: url.includes('.mp4') ? 'mp4' : 'jpg' });
                    }
                });
            }
        }

        if (links.length === 0) {
            const html = (data && data.data) ? data.data : body;
            const urlMatches = html.match(/https?:\/\/[^\s"'<>]*(?:instagram|cdninstagram|fbcdn)[^\s"'<>]*/gi);
            if (urlMatches) {
                const unique = [...new Set(urlMatches)];
                unique.forEach((url, i) => {
                    links.push({ url: url, quality: 'Download ' + (i + 1), format: url.includes('.mp4') ? 'mp4' : 'jpg' });
                });
            }
        }

        if (links.length > 0) return { success: true, links };
        return { success: false, error: 'Could not extract Instagram download links. The post may be private.' };
    } catch (err) {
        return { success: false, error: 'Instagram download service error: ' + err.message };
    }
}

// =============================================
// Pinterest downloader via snapsave.io
// =============================================
async function downloadPinterest(videoUrl) {
    try {
        const postData = `url=${encodeURIComponent(videoUrl)}&q_auto=0`;
        const response = await makeRequest({
            hostname: 'snapsave.io',
            path: '/api/ajaxSearch',
            method: 'POST',
            protocol: 'https:',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
                'Content-Length': Buffer.byteLength(postData),
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
                'Referer': 'https://snapsave.io/',
                'Origin': 'https://snapsave.io',
                'Accept': '*/*',
                'Accept-Language': 'en-US,en;q=0.9'
            }
        }, postData);

        const body = response.body;
        const links = [];
        let data;
        try { data = JSON.parse(body); } catch (e) { data = null; }

        if (data && data.data) {
            const html = data.data;
            const hrefMatches = html.match(/href="(https?:\/\/[^"]+)"/gi);
            if (hrefMatches) {
                hrefMatches.forEach((match, i) => {
                    const url = match.match(/href="([^"]+)"/)[1];
                    if (url.includes('.mp4') || url.includes('.jpg') || url.includes('.png') || url.includes('.webp') || url.includes('pinimg')) {
                        const ext = url.match(/\.(mp4|jpg|png|webp)/i);
                        links.push({ url: url, quality: 'Download ' + (i + 1), format: ext ? ext[1] : 'mp4' });
                    }
                });
            }
        }

        if (links.length === 0) {
            const html = (data && data.data) ? data.data : body;
            const urlMatches = html.match(/https?:\/\/[^\s"'<>]+\.(mp4|jpg|png|webp)[^\s"'<>]*/gi);
            if (urlMatches) {
                const unique = [...new Set(urlMatches)];
                unique.forEach((url, i) => {
                    const ext = url.match(/\.(mp4|jpg|png|webp)/i);
                    links.push({ url: url, quality: 'Download ' + (i + 1), format: ext ? ext[1] : 'mp4' });
                });
            }
        }

        if (links.length > 0) return { success: true, links };
        return { success: false, error: 'Could not extract Pinterest download links.' };
    } catch (err) {
        return { success: false, error: 'Pinterest download service error: ' + err.message };
    }
}

// =============================================
// Twitter/X downloader via snapsave.io
// =============================================
async function downloadTwitter(videoUrl) {
    try {
        const postData = `url=${encodeURIComponent(videoUrl)}&q_auto=0`;
        const response = await makeRequest({
            hostname: 'snapsave.io',
            path: '/api/ajaxSearch',
            method: 'POST',
            protocol: 'https:',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
                'Content-Length': Buffer.byteLength(postData),
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
                'Referer': 'https://snapsave.io/',
                'Origin': 'https://snapsave.io',
                'Accept': '*/*',
                'Accept-Language': 'en-US,en;q=0.9'
            }
        }, postData);

        const body = response.body;
        const links = [];
        let data;
        try { data = JSON.parse(body); } catch (e) { data = null; }

        if (data && data.data) {
            const html = data.data;
            const hrefMatches = html.match(/href="(https?:\/\/[^"]+)"/gi);
            if (hrefMatches) {
                hrefMatches.forEach((match, i) => {
                    const url = match.match(/href="([^"]+)"/)[1];
                    if (url.includes('.mp4') || url.includes('video') || url.includes('twimg')) {
                        links.push({ url: url, quality: i === 0 ? 'HD' : 'SD', format: 'mp4' });
                    }
                });
            }
        }

        if (links.length === 0) {
            const html = (data && data.data) ? data.data : body;
            const urlMatches = html.match(/https?:\/\/[^\s"'<>]+\.mp4[^\s"'<>]*/gi);
            if (urlMatches) {
                const unique = [...new Set(urlMatches)];
                unique.forEach((url, i) => {
                    links.push({ url: url, quality: i === 0 ? 'HD' : 'SD', format: 'mp4' });
                });
            }

            const twitterCdn = html.match(/https?:\/\/video\.twimg\.com[^\s"'<>]*/gi);
            if (twitterCdn && links.length === 0) {
                const unique = [...new Set(twitterCdn)];
                unique.forEach((url, i) => {
                    links.push({ url: url, quality: 'Quality ' + (i + 1), format: 'mp4' });
                });
            }
        }

        if (links.length > 0) return { success: true, links };
        return { success: false, error: 'Could not extract X/Twitter download links.' };
    } catch (err) {
        return { success: false, error: 'X/Twitter download service error: ' + err.message };
    }
}

// =============================================
// FALLBACK: loader.to (multi-platform)
// Supports YouTube, Facebook, Instagram, TikTok,
// Twitter, Pinterest and many more
// =============================================
async function downloadViaLoaderTo(videoUrl, platform) {
    try {
        const format = (platform === 'youtube') ? '1080' : '360';

        const submitResponse = await makeRequest({
            hostname: 'loader.to',
            path: '/ajax/download.php?format=' + format + '&url=' + encodeURIComponent(videoUrl),
            method: 'GET',
            protocol: 'https:',
            headers: {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
                'Accept': 'application/json, text/javascript, */*; q=0.01',
                'Referer': 'https://loader.to/',
                'Origin': 'https://loader.to'
            }
        });

        let submitData;
        try { submitData = JSON.parse(submitResponse.body); } catch (e) { submitData = null; }

        if (!submitData || !submitData.success || !submitData.id) {
            return { success: false, error: 'Loader.to: failed to submit download request.' };
        }

        const jobId = submitData.id;

        // Poll for progress (max ~40 seconds)
        let downloadUrl = null;
        for (let i = 0; i < 20; i++) {
            await sleep(2000);

            const progressResponse = await makeRequest({
                hostname: 'loader.to',
                path: '/ajax/progress.php?id=' + jobId,
                method: 'GET',
                protocol: 'https:',
                headers: {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
                    'Accept': 'application/json',
                    'Referer': 'https://loader.to/'
                }
            });

            let progressData;
            try { progressData = JSON.parse(progressResponse.body); } catch (e) { progressData = null; }

            if (progressData && progressData.success === 1 && progressData.download_url) {
                downloadUrl = progressData.download_url;
                break;
            }

            // success:1 with no download_url means conversion failed
            if (progressData && progressData.success === 1 && !progressData.download_url) {
                return { success: false, error: 'Loader.to: video conversion failed.' };
            }

            // success:0 with progress > 0 means still processing - continue polling
            // success:0 with progress === 0 means genuine failure
            if (progressData && progressData.success === 0 && progressData.progress === 0) {
                return { success: false, error: 'Loader.to: video conversion failed.' };
            }
        }

        if (!downloadUrl) {
            return { success: false, error: 'Loader.to: conversion timed out.' };
        }

        const links = [
            { url: downloadUrl, quality: format === '1080' ? '1080p' : 'Download', format: 'mp4' }
        ];

        // Try to get thumbnail from content
        if (submitData.content) {
            try {
                const decoded = Buffer.from(submitData.content, 'base64').toString();
                const imgMatch = decoded.match(/src="(https?:\/\/[^"]+)"/);
                if (imgMatch) {
                    return { success: true, links, thumbnail: imgMatch[1] };
                }
            } catch (e) {}
        }

        return { success: true, links };
    } catch (err) {
        return { success: false, error: 'Loader.to error: ' + err.message };
    }
}

// =============================================
// PRIMARY DOWNLOAD - platform-specific scrapers
// =============================================
async function downloadPrimary(url, platform) {
    switch (platform) {
        case 'facebook':  return downloadFacebook(url);
        case 'tiktok':    return downloadTiktok(url);
        case 'youtube':   return downloadYoutube(url);
        case 'instagram': return downloadInstagram(url);
        case 'pinterest': return downloadPinterest(url);
        case 'twitter':   return downloadTwitter(url);
        default:          return { success: false, error: 'Unsupported platform' };
    }
}

// =============================================
// SECONDARY: TikTok has a backup scraper
// =============================================
async function downloadSecondary(url, platform) {
    if (platform === 'tiktok') {
        return downloadTiktokSnaptik(url);
    }
    return { success: false, error: 'No secondary scraper for this platform' };
}

// =============================================
// MAIN HANDLER with fallback chain:
// 1. Primary scrapers (platform-specific)
// 2. Secondary scrapers (platform-specific backup)
// 3. loader.to (universal fallback)
// =============================================
module.exports = async function handler(req, res) {
    // CORS headers
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

    if (req.method === 'OPTIONS') {
        return res.status(200).end();
    }

    if (req.method !== 'POST') {
        return res.status(405).json({ success: false, error: 'Method not allowed' });
    }

    const { url } = req.body || {};

    if (!url) {
        return res.status(400).json({ success: false, error: 'URL is required' });
    }

    const platform = detectPlatform(url);

    if (!platform) {
        return res.status(400).json({ success: false, error: 'Unsupported platform' });
    }

    // ---- Fallback chain ----
    // 1. Primary: platform-specific scrapers
    let result = await downloadPrimary(url, platform);
    if (result.success) {
        result.platform = platform;
        result.source = 'primary';
        return res.status(200).json(result);
    }

    const primaryError = result.error;

    // 2. Secondary: platform-specific backup scrapers
    result = await downloadSecondary(url, platform);
    if (result.success) {
        result.platform = platform;
        result.source = 'secondary';
        return res.status(200).json(result);
    }

    const secondaryError = result.error;

    // 3. Fallback: loader.to (multi-platform)
    result = await downloadViaLoaderTo(url, platform);
    if (result.success) {
        result.platform = platform;
        result.source = 'loader';
        return res.status(200).json(result);
    }

    // All methods failed
    return res.status(422).json({
        success: false,
        platform,
        error: 'All download methods failed. Please try again later.',
        details: {
            primary: primaryError,
            secondary: secondaryError,
            loader: result.error
        }
    });
};
