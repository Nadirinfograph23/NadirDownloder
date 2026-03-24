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
        req.setTimeout(15000, () => { req.destroy(); reject(new Error('Request timeout')); });
        if (postData) req.write(postData);
        req.end();
    });
}

// Facebook downloader via snapsave
async function downloadFacebook(videoUrl) {
    try {
        const postData = `url=${encodeURIComponent(videoUrl)}`;
        const response = await makeRequest({
            hostname: 'snapsave.app',
            path: '/action.php?lang=fr',
            method: 'POST',
            protocol: 'https:',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
                'Content-Length': Buffer.byteLength(postData),
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Referer': 'https://snapsave.app/fr',
                'Origin': 'https://snapsave.app'
            }
        }, postData);

        const body = response.body;
        const links = [];

        // Try to extract download links from response
        const hdMatch = body.match(/href="(https?:\/\/[^"]*)"[^>]*>.*?HD/gi);
        const sdMatch = body.match(/href="(https?:\/\/[^"]*)"[^>]*>.*?SD/gi);
        const urlMatches = body.match(/https?:\/\/[^\s"'<>]+\.mp4[^\s"'<>]*/gi);

        if (urlMatches) {
            const unique = [...new Set(urlMatches)];
            unique.forEach((url, i) => {
                links.push({ url: url, quality: i === 0 ? 'HD' : 'SD', format: 'mp4' });
            });
        }

        if (links.length > 0) return { success: true, links };

        // Try decoding encoded response
        const encodedMatch = body.match(/decodeURIComponent\(escape\(atob\("([^"]+)"\)\)\)/);
        if (encodedMatch) {
            const decoded = Buffer.from(encodedMatch[1], 'base64').toString();
            const decodedUrls = decoded.match(/https?:\/\/[^\s"'<>]+\.mp4[^\s"'<>]*/gi);
            if (decodedUrls) {
                const unique = [...new Set(decodedUrls)];
                unique.forEach((url, i) => {
                    links.push({ url: url, quality: i === 0 ? 'HD' : 'SD', format: 'mp4' });
                });
                return { success: true, links };
            }
        }

        return { success: false, error: 'Could not extract download links. The video may be private or unavailable.' };
    } catch (err) {
        return { success: false, error: 'Facebook download service error: ' + err.message };
    }
}

// TikTok downloader via snaptik
async function downloadTiktok(videoUrl) {
    try {
        // First get the page to extract token
        const pageResponse = await makeRequest({
            hostname: 'snaptik.app',
            path: '/fr2',
            method: 'GET',
            protocol: 'https:',
            headers: {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
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
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
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

        // Also try to find download links in decoded content
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
        return { success: false, error: 'Could not extract TikTok download links. The video may be private.' };
    } catch (err) {
        return { success: false, error: 'TikTok download service error: ' + err.message };
    }
}

// YouTube downloader via snapany
async function downloadYoutube(videoUrl) {
    try {
        const postData = `url=${encodeURIComponent(videoUrl)}`;
        const response = await makeRequest({
            hostname: 'snapany.com',
            path: '/api/ajaxSearch',
            method: 'POST',
            protocol: 'https:',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
                'Content-Length': Buffer.byteLength(postData),
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Referer': 'https://snapany.com/fr/youtube-1',
                'Origin': 'https://snapany.com'
            }
        }, postData);

        const body = response.body;
        let data;
        try { data = JSON.parse(body); } catch (e) { data = null; }

        const links = [];

        if (data && data.links) {
            // Process video links
            if (data.links.mp4) {
                Object.values(data.links.mp4).forEach(item => {
                    if (item.url || item.k) {
                        links.push({
                            url: item.url || item.k,
                            quality: item.q || item.quality || 'Video',
                            format: 'mp4',
                            size: item.size || ''
                        });
                    }
                });
            }
            // Process audio links
            if (data.links.mp3) {
                Object.values(data.links.mp3).forEach(item => {
                    if (item.url || item.k) {
                        links.push({
                            url: item.url || item.k,
                            quality: item.q || item.quality || 'Audio',
                            format: 'mp3',
                            size: item.size || ''
                        });
                    }
                });
            }
        }

        // Fallback: extract from HTML response
        if (links.length === 0) {
            const urlMatches = body.match(/https?:\/\/[^\s"'<>]+\.(mp4|webm|m4a)[^\s"'<>]*/gi);
            if (urlMatches) {
                const unique = [...new Set(urlMatches)];
                unique.forEach((url, i) => {
                    const ext = url.match(/\.(mp4|webm|m4a)/i);
                    links.push({ url: url, quality: `Quality ${i + 1}`, format: ext ? ext[1] : 'mp4' });
                });
            }
        }

        if (links.length > 0) return { success: true, links, title: data?.title || '' };
        return { success: false, error: 'Could not extract YouTube download links.' };
    } catch (err) {
        return { success: false, error: 'YouTube download service error: ' + err.message };
    }
}

// Instagram downloader via snapinsta
async function downloadInstagram(videoUrl) {
    try {
        const postData = `url=${encodeURIComponent(videoUrl)}`;
        const response = await makeRequest({
            hostname: 'snapinsta.to',
            path: '/api/ajaxSearch',
            method: 'POST',
            protocol: 'https:',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
                'Content-Length': Buffer.byteLength(postData),
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Referer': 'https://snapinsta.to/fr',
                'Origin': 'https://snapinsta.to'
            }
        }, postData);

        const body = response.body;
        const links = [];
        let data;
        try { data = JSON.parse(body); } catch (e) { data = null; }

        // Try JSON response
        if (data && data.links) {
            Object.values(data.links).forEach(item => {
                if (item.url) {
                    links.push({ url: item.url, quality: item.q || 'Download', format: 'mp4' });
                }
            });
        }

        // Try extracting from HTML in response
        if (links.length === 0) {
            const html = data?.data || body;
            const hrefMatches = html.match(/href="(https?:\/\/[^"]+)"/gi);
            if (hrefMatches) {
                hrefMatches.forEach((match, i) => {
                    const url = match.match(/href="([^"]+)"/)[1];
                    if (url.includes('instagram') || url.includes('cdninstagram') || url.includes('.mp4') || url.includes('.jpg')) {
                        links.push({ url: url, quality: `Download ${i + 1}`, format: url.includes('.mp4') ? 'mp4' : 'jpg' });
                    }
                });
            }

            const urlMatches = html.match(/https?:\/\/[^\s"'<>]*(?:instagram|cdninstagram|fbcdn)[^\s"'<>]*/gi);
            if (urlMatches && links.length === 0) {
                const unique = [...new Set(urlMatches)];
                unique.forEach((url, i) => {
                    links.push({ url: url, quality: `Download ${i + 1}`, format: url.includes('.mp4') ? 'mp4' : 'jpg' });
                });
            }
        }

        if (links.length > 0) return { success: true, links };
        return { success: false, error: 'Could not extract Instagram download links. The post may be private.' };
    } catch (err) {
        return { success: false, error: 'Instagram download service error: ' + err.message };
    }
}

// Pinterest downloader via snappin
async function downloadPinterest(videoUrl) {
    try {
        const postData = `url=${encodeURIComponent(videoUrl)}`;
        const response = await makeRequest({
            hostname: 'snappin.app',
            path: '/api/ajaxSearch',
            method: 'POST',
            protocol: 'https:',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
                'Content-Length': Buffer.byteLength(postData),
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Referer': 'https://snappin.app/fr',
                'Origin': 'https://snappin.app'
            }
        }, postData);

        const body = response.body;
        const links = [];
        let data;
        try { data = JSON.parse(body); } catch (e) { data = null; }

        if (data && data.links) {
            Object.values(data.links).forEach(item => {
                if (item.url) {
                    links.push({ url: item.url, quality: item.q || 'Download', format: 'mp4' });
                }
            });
        }

        if (links.length === 0) {
            const html = data?.data || body;
            const urlMatches = html.match(/https?:\/\/[^\s"'<>]+\.(mp4|jpg|png|webp)[^\s"'<>]*/gi);
            if (urlMatches) {
                const unique = [...new Set(urlMatches)];
                unique.forEach((url, i) => {
                    const ext = url.match(/\.(mp4|jpg|png|webp)/i);
                    links.push({ url: url, quality: `Download ${i + 1}`, format: ext ? ext[1] : 'mp4' });
                });
            }
        }

        if (links.length > 0) return { success: true, links };
        return { success: false, error: 'Could not extract Pinterest download links.' };
    } catch (err) {
        return { success: false, error: 'Pinterest download service error: ' + err.message };
    }
}

// Twitter/X downloader via snapvid
async function downloadTwitter(videoUrl) {
    try {
        const postData = `url=${encodeURIComponent(videoUrl)}`;
        const response = await makeRequest({
            hostname: 'snapvid.net',
            path: '/api/ajaxSearch',
            method: 'POST',
            protocol: 'https:',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
                'Content-Length': Buffer.byteLength(postData),
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Referer': 'https://snapvid.net/fr1/twitter-downloader',
                'Origin': 'https://snapvid.net'
            }
        }, postData);

        const body = response.body;
        const links = [];
        let data;
        try { data = JSON.parse(body); } catch (e) { data = null; }

        if (data && data.links) {
            Object.values(data.links).forEach(item => {
                if (item.url) {
                    links.push({ url: item.url, quality: item.q || 'Download', format: 'mp4' });
                }
            });
        }

        if (links.length === 0) {
            const html = data?.data || body;
            const urlMatches = html.match(/https?:\/\/[^\s"'<>]+\.mp4[^\s"'<>]*/gi);
            if (urlMatches) {
                const unique = [...new Set(urlMatches)];
                unique.forEach((url, i) => {
                    links.push({ url: url, quality: i === 0 ? 'HD' : 'SD', format: 'mp4' });
                });
            }

            // Also try to find video URLs in Twitter CDN
            const twitterCdn = html.match(/https?:\/\/video\.twimg\.com[^\s"'<>]*/gi);
            if (twitterCdn && links.length === 0) {
                const unique = [...new Set(twitterCdn)];
                unique.forEach((url, i) => {
                    links.push({ url: url, quality: `Quality ${i + 1}`, format: 'mp4' });
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
// FALLBACK 1: Silva API
// =============================================
async function downloadViaSilvaAPI(videoUrl) {
    try {
        const apiUrl = `https://silva-ap-is.vercel.app/api/tiktok?url=${encodeURIComponent(videoUrl)}&apikey=silva`;
        const parsed = new URL(apiUrl);

        const response = await makeRequest({
            hostname: parsed.hostname,
            path: parsed.pathname + parsed.search,
            method: 'GET',
            protocol: 'https:',
            headers: {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'application/json'
            }
        });

        let data;
        try { data = JSON.parse(response.body); } catch (e) { data = null; }

        if (!data) {
            return { success: false, error: 'Silva API returned invalid response' };
        }

        const links = [];

        if (data.result && data.result.download_url) {
            links.push({ url: data.result.download_url, quality: 'HD (No Watermark)', format: 'mp4' });
        }
        if (data.result && data.result.download_url_wm) {
            links.push({ url: data.result.download_url_wm, quality: 'With Watermark', format: 'mp4' });
        }
        if (data.data && data.data.play) {
            links.push({ url: data.data.play, quality: 'HD Video', format: 'mp4' });
        }
        if (data.data && data.data.wmplay) {
            links.push({ url: data.data.wmplay, quality: 'With Watermark', format: 'mp4' });
        }
        if (data.data && data.data.hdplay) {
            links.push({ url: data.data.hdplay, quality: 'HD Video', format: 'mp4' });
        }
        if (data.data && data.data.music) {
            links.push({ url: data.data.music, quality: 'Audio Only', format: 'mp3' });
        }
        if (data.url) {
            links.push({ url: data.url, quality: 'Download', format: 'mp4' });
        }
        if (data.video) {
            links.push({ url: data.video, quality: 'Video', format: 'mp4' });
        }
        if (data.download) {
            links.push({ url: data.download, quality: 'Download', format: 'mp4' });
        }

        if (data.links && Array.isArray(data.links)) {
            data.links.forEach((link, i) => {
                if (typeof link === 'string') {
                    links.push({ url: link, quality: `Quality ${i + 1}`, format: 'mp4' });
                } else if (link.url) {
                    links.push({
                        url: link.url,
                        quality: link.quality || link.q || `Quality ${i + 1}`,
                        format: link.format || 'mp4'
                    });
                }
            });
        }

        const title = data.result?.title || data.data?.title || data.title || '';
        const thumbnail = data.result?.thumbnail || data.data?.cover || data.data?.origin_cover || data.thumbnail || '';

        if (links.length > 0) {
            return { success: true, links, title, thumbnail };
        }

        return { success: false, error: 'Silva API: no download links found' };
    } catch (err) {
        return { success: false, error: 'Silva API error: ' + err.message };
    }
}

// =============================================
// FALLBACK 2: FastSaver API
// =============================================
async function downloadViaFastSaver(videoUrl) {
    try {
        const postData = JSON.stringify({ url: videoUrl });

        const response = await makeRequest({
            hostname: 'api.fastsaverapi.com',
            path: '/v2/download',
            method: 'POST',
            protocol: 'https:',
            headers: {
                'Content-Type': 'application/json',
                'Content-Length': Buffer.byteLength(postData),
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'application/json'
            }
        }, postData);

        let data;
        try { data = JSON.parse(response.body); } catch (e) { data = null; }

        if (!data) {
            return { success: false, error: 'FastSaver API returned invalid response' };
        }

        const links = [];

        if (data.url) {
            links.push({
                url: Array.isArray(data.url) ? data.url[0] : data.url,
                quality: 'HD Video',
                format: 'mp4'
            });
        }

        if (data.video) {
            const videos = Array.isArray(data.video) ? data.video : [data.video];
            videos.forEach((v, i) => {
                if (typeof v === 'string') {
                    links.push({ url: v, quality: i === 0 ? 'HD' : 'SD', format: 'mp4' });
                } else if (v.url) {
                    links.push({
                        url: v.url,
                        quality: v.quality || (i === 0 ? 'HD' : 'SD'),
                        format: v.format || 'mp4'
                    });
                }
            });
        }

        if (data.urls && Array.isArray(data.urls)) {
            data.urls.forEach((item, i) => {
                if (typeof item === 'string') {
                    links.push({ url: item, quality: `Quality ${i + 1}`, format: 'mp4' });
                } else if (item.url) {
                    links.push({
                        url: item.url,
                        quality: item.quality || item.q || `Quality ${i + 1}`,
                        format: item.ext || item.format || 'mp4',
                        size: item.size || ''
                    });
                }
            });
        }

        if (data.medias && Array.isArray(data.medias)) {
            data.medias.forEach((media, i) => {
                if (media.url) {
                    links.push({
                        url: media.url,
                        quality: media.quality || media.formattedSize || `Quality ${i + 1}`,
                        format: media.extension || 'mp4',
                        size: media.formattedSize || ''
                    });
                }
            });
        }

        const title = data.title || data.meta?.title || '';
        const thumbnail = data.thumbnail || data.meta?.thumbnail || data.cover || '';

        if (links.length > 0) {
            return { success: true, links, title, thumbnail };
        }

        return { success: false, error: 'FastSaver API: no download links found' };
    } catch (err) {
        return { success: false, error: 'FastSaver API error: ' + err.message };
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
// MAIN HANDLER with fallback chain:
// 1. Primary scrapers (yt-dlp equivalent)
// 2. Silva API (fallback)
// 3. FastSaver API (fallback)
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

    // 2. Fallback: Silva API
    result = await downloadViaSilvaAPI(url);
    if (result.success) {
        result.platform = platform;
        result.source = 'silva';
        return res.status(200).json(result);
    }

    const silvaError = result.error;

    // 3. Fallback: FastSaver API
    result = await downloadViaFastSaver(url);
    if (result.success) {
        result.platform = platform;
        result.source = 'fastsaver';
        return res.status(200).json(result);
    }

    // All methods failed
    return res.status(422).json({
        success: false,
        platform,
        error: 'All download methods failed. Please try again later.',
        details: {
            primary: primaryError,
            silva: silvaError,
            fastsaver: result.error
        }
    });
};
