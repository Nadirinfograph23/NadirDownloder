const https = require('https');

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

// Fetch video info from RapidAPI "Auto Download All In One" API
// Free tier: $0.00/mo (1 req/sec limit)
// Subscribe at: https://rapidapi.com/nguyenmanhict-MuTUtGWD7K/api/auto-download-all-in-one
function fetchFromRapidAPI(videoUrl) {
    return new Promise((resolve, reject) => {
        const postBody = JSON.stringify({ url: videoUrl });
        const options = {
            hostname: 'auto-download-all-in-one.p.rapidapi.com',
            path: '/v1/social/autolink',
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'x-rapidapi-key': process.env.RAPIDAPI_KEY,
                'x-rapidapi-host': 'auto-download-all-in-one.p.rapidapi.com',
                'Content-Length': Buffer.byteLength(postBody)
            }
        };

        const req = https.request(options, (res) => {
            let data = '';
            res.on('data', (chunk) => { data += chunk; });
            res.on('end', () => {
                try {
                    const parsed = JSON.parse(data);
                    resolve({ statusCode: res.statusCode, data: parsed });
                } catch (e) {
                    reject(new Error('Failed to parse API response'));
                }
            });
        });

        req.on('error', reject);
        req.setTimeout(30000, () => {
            req.destroy();
            reject(new Error('Request timeout'));
        });
        req.write(postBody);
        req.end();
    });
}

// Transform API response to match frontend expected format
// API returns: { url, source, author, title, thumbnail, duration, medias: [{ url, quality, extension, type }] }
// Frontend expects: { success, links: [{ url, quality, format }], title, thumbnail, platform }
function transformResponse(apiData, platform) {
    const links = [];
    const title = apiData.title || '';
    const thumbnail = apiData.thumbnail || '';

    if (apiData.medias && Array.isArray(apiData.medias)) {
        apiData.medias.forEach((item) => {
            if (item.url) {
                const quality = item.quality || 'Download';
                const format = item.extension || (item.type === 'audio' ? 'mp3' : 'mp4');

                links.push({
                    url: item.url,
                    quality: quality,
                    format: format,
                    size: item.size || ''
                });
            }
        });
    }

    return {
        success: links.length > 0,
        links: links,
        title: title,
        thumbnail: thumbnail,
        platform: platform
    };
}

// Main handler
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
        return res.status(400).json({ success: false, error: 'Unsupported platform. Try Facebook, TikTok, YouTube, Instagram, Pinterest, or X (Twitter).' });
    }

    if (!process.env.RAPIDAPI_KEY) {
        return res.status(500).json({ success: false, error: 'API key not configured. Please set RAPIDAPI_KEY environment variable.' });
    }

    try {
        const response = await fetchFromRapidAPI(url);

        if (response.statusCode === 429) {
            return res.status(429).json({ success: false, error: 'Too many requests. Please try again later.' });
        }

        if (response.statusCode === 401 || response.statusCode === 403) {
            return res.status(401).json({ success: false, error: 'Invalid API key or not subscribed. Please check configuration.' });
        }

        if (response.statusCode !== 200) {
            return res.status(422).json({ success: false, error: 'Could not process this URL. Please try again.' });
        }

        const result = transformResponse(response.data, platform);

        if (!result.success) {
            return res.status(422).json({
                success: false,
                error: 'Could not extract download links. The video may be private or unavailable.',
                platform: platform
            });
        }

        return res.status(200).json(result);
    } catch (err) {
        return res.status(500).json({
            success: false,
            error: 'Download service error: ' + err.message,
            platform: platform
        });
    }
};
