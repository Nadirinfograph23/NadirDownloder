/**
 * NADIR DOWNLOADER — /api/instagram
 * POST { url: "https://www.instagram.com/..." }
 *
 * Extraction pipeline (first success wins):
 *   H  cobalt.tools open API  (primary — no auth required)
 *   A  og:video  meta tag
 *   B  video_url / playable_url in page JSON blobs
 *   C  window.__additionalDataLoaded  +  application/ld+json
 *   D  video_versions[].url
 *   E  /embed/captioned/ page (A-D pass)
 *   F  GraphQL /api/graphql with fresh session cookies
 *   G  Instagram mobile API (i.instagram.com)
 *
 * Returns: { success, videoUrl, thumbnail, title }
 *       or { success:false, fallback:true, error }
 */

const USER_AGENTS = [
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
  'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
  'Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1',
];

const IG_ANDROID_UA =
  'Instagram 275.0.0.27.98 Android (33/13; 420dpi; 1080x2400; samsung; SM-G991B; o1s; exynos2100; en_US; 458229258)';

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────
function cleanInstagramUrl(raw) {
  try {
    const u = new URL(raw);
    u.search = '';
    u.hash = '';
    u.hostname = 'www.instagram.com';
    u.pathname = u.pathname.replace(/\/$/, '') + '/';
    return u.toString();
  } catch {
    return raw.split('?')[0].split('#')[0];
  }
}

function extractShortcode(url) {
  const m =
    url.match(/instagram\.com\/(?:p|reel|reels|tv)\/([A-Za-z0-9_-]+)/i) ||
    url.match(/instagr\.am\/p\/([A-Za-z0-9_-]+)/i);
  return m ? m[1] : null;
}

function shortcodeToMediaId(shortcode) {
  const alpha = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_';
  let id = BigInt(0);
  for (const ch of shortcode) id = id * BigInt(64) + BigInt(alpha.indexOf(ch));
  return id.toString();
}

function delay(ms) {
  return new Promise(r => setTimeout(r, ms));
}

function isLoginPage(html) {
  return (
    html.includes('"login_page"') ||
    html.includes('id="loginForm"') ||
    html.includes('class="LoginForm"') ||
    (html.includes('"require_login"') && html.includes('true'))
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Method H — cobalt.tools (primary, free, open-source)
// ─────────────────────────────────────────────────────────────────────────────
async function methodH_cobalt(igUrl) {
  const endpoints = [
    'https://api.cobalt.tools/',
    'https://co.wuk.sh/api/json',
  ];

  for (const endpoint of endpoints) {
    try {
      const resp = await fetch(endpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'application/json',
          'User-Agent': 'NadirDownloader/1.0',
        },
        body: JSON.stringify({ url: igUrl, videoQuality: '1080' }),
        signal: AbortSignal.timeout(15000),
      });

      if (!resp.ok) continue;

      const data = await resp.json();

      // status: redirect | tunnel  → direct URL
      if ((data.status === 'redirect' || data.status === 'tunnel') && data.url) {
        return { videoUrl: data.url, thumbnail: null, title: null };
      }

      // status: picker → multiple files; take first video
      if (data.status === 'picker' && Array.isArray(data.picker)) {
        const video = data.picker.find(p => p.type === 'video' || /\.mp4/i.test(p.url || ''));
        if (video?.url) return { videoUrl: video.url, thumbnail: null, title: null };
      }
    } catch {
      // try next endpoint
    }
  }
  return null;
}

// ─────────────────────────────────────────────────────────────────────────────
// Text-extraction methods A – D  (applied to raw HTML)
// ─────────────────────────────────────────────────────────────────────────────
function methodA_ogVideo(html) {
  return (
    html.match(/<meta[^>]+property="og:video(?::url)?"[^>]+content="([^"]+)"/i)?.[1] ||
    html.match(/<meta[^>]+content="([^"]+)"[^>]+property="og:video(?::url)?"/i)?.[1] ||
    null
  )?.replace(/&amp;/g, '&') ?? null;
}

function methodB_videoUrlJson(html) {
  const fields = ['video_url', 'playable_url', 'playable_url_quality_hd'];
  for (const f of fields) {
    const m = html.match(new RegExp(`"${f}"\\s*:\\s*"([^"\\\\]+(?:\\\\.[^"\\\\]*)*)"`, 'i'));
    if (m) return m[1].replace(/\\u0026/g, '&').replace(/\\\//g, '/').replace(/\\"/g, '"');
  }
  return null;
}

function methodC_ldJson(html) {
  for (const m of html.matchAll(/<script[^>]+type="application\/ld\+json"[^>]*>([\s\S]*?)<\/script>/gi)) {
    try {
      const data = JSON.parse(m[1]);
      if (data.contentUrl) return data.contentUrl;
      if (Array.isArray(data['@graph'])) {
        for (const node of data['@graph']) {
          if (node.contentUrl) return node.contentUrl;
        }
      }
    } catch {}
  }

  const adm = html.match(/window\.__additionalDataLoaded\s*\(\s*['"][^'"]*['"]\s*,\s*(\{[\s\S]*?\})\s*\)/);
  if (adm) {
    try {
      const data = JSON.parse(adm[1]);
      const media =
        data?.graphql?.shortcode_media ||
        data?.items?.[0]?.media ||
        data?.items?.[0];
      if (media?.video_url) return media.video_url;
    } catch {}
  }

  for (const sm of html.matchAll(/<script[^>]*>([\s\S]{200,100000}?)<\/script>/gi)) {
    try {
      const parsed = JSON.parse(sm[1]);
      const u = deepFindVideoUrl(parsed);
      if (u) return u;
    } catch {}
  }
  return null;
}

function methodD_videoVersions(html) {
  const m = html.match(/"video_versions"\s*:\s*\[[\s\S]*?"url"\s*:\s*"([^"\\]+(?:\\.[^"\\]*)*)"/);
  return m ? m[1].replace(/\\u0026/g, '&').replace(/\\\//g, '/') : null;
}

function deepFindVideoUrl(obj, depth = 0) {
  if (depth > 10 || !obj || typeof obj !== 'object') return null;
  for (const key of ['video_url', 'playable_url', 'videoUrl', 'contentUrl']) {
    if (typeof obj[key] === 'string' && obj[key].startsWith('http')) return obj[key];
  }
  for (const val of Object.values(obj)) {
    const found = deepFindVideoUrl(val, depth + 1);
    if (found) return found;
  }
  return null;
}

function runAllTextMethods(html) {
  return methodA_ogVideo(html) || methodB_videoUrlJson(html) || methodC_ldJson(html) || methodD_videoVersions(html) || null;
}

// ─────────────────────────────────────────────────────────────────────────────
// Meta helpers
// ─────────────────────────────────────────────────────────────────────────────
function extractThumbnail(html) {
  const m =
    html.match(/<meta[^>]+property="og:image"[^>]+content="([^"]+)"/i) ||
    html.match(/<meta[^>]+content="([^"]+)"[^>]+property="og:image"/i);
  return m ? m[1].replace(/&amp;/g, '&') : null;
}

function extractTitle(html) {
  const m =
    html.match(/<meta[^>]+property="og:title"[^>]+content="([^"]+)"/i) ||
    html.match(/<meta[^>]+content="([^"]+)"[^>]+property="og:title"/i) ||
    html.match(/<title>([^<]+)<\/title>/i);
  return m
    ? m[1].replace(/\s+on Instagram.*$/i, '').replace(/\s*•\s*Instagram.*$/i, '').trim()
    : null;
}

// ─────────────────────────────────────────────────────────────────────────────
// Method E — /embed/captioned/ page
// ─────────────────────────────────────────────────────────────────────────────
async function fetchPage(url, ua, extraHeaders = {}) {
  const resp = await fetch(url, {
    method: 'GET',
    headers: {
      'User-Agent': ua,
      Accept: 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
      'Accept-Language': 'en-US,en;q=0.9',
      'Accept-Encoding': 'gzip, deflate, br',
      Referer: 'https://www.instagram.com/',
      'Cache-Control': 'no-cache',
      Pragma: 'no-cache',
      DNT: '1',
      ...extraHeaders,
    },
    redirect: 'follow',
    signal: AbortSignal.timeout(12000),
  });
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return resp.text();
}

async function methodE_embedPage(shortcode, ua) {
  const html = await fetchPage(
    `https://www.instagram.com/p/${shortcode}/embed/captioned/`,
    ua,
    { 'Sec-Fetch-Dest': 'iframe', 'Sec-Fetch-Mode': 'navigate' }
  );
  return runAllTextMethods(html);
}

// ─────────────────────────────────────────────────────────────────────────────
// Method F — GraphQL with fresh session cookies
// ─────────────────────────────────────────────────────────────────────────────
async function methodF_graphQL(shortcode, ua) {
  const homeResp = await fetch('https://www.instagram.com/', {
    headers: { 'User-Agent': ua, Accept: 'text/html,*/*', 'Accept-Language': 'en-US,en;q=0.9' },
    redirect: 'follow',
    signal: AbortSignal.timeout(10000),
  });
  const rawCookies = homeResp.headers.get('set-cookie') || '';
  const homeHtml = await homeResp.text();

  const csrf =
    rawCookies.match(/csrftoken=([^;,\s]+)/)?.[1] ||
    homeHtml.match(/"csrf_token"\s*:\s*"([^"]+)"/)?.[1] ||
    'RVDUooU5MYsBbS1CNN3CzVAuEP8oHB52';

  const lsd =
    homeHtml.match(/"LSD"\s*,\s*\[\]\s*,\s*\{"token"\s*:\s*"([^"]+)"/)?.[1] ||
    'AVqbxe3J_YA';

  const mid = rawCookies.match(/\bmid=([^;,\s]+)/)?.[1] || '';
  const cookieStr = [`csrftoken=${csrf}`, mid ? `mid=${mid}` : ''].filter(Boolean).join('; ');

  const body = new URLSearchParams({
    av: '0', __d: 'www', __user: '0', __a: '1', __req: '3', __ccg: 'UNKNOWN',
    lsd, jazoest: '2957',
    fb_api_caller_class: 'RelayModern',
    fb_api_req_friendly_name: 'PolarisPostActionLoadPostQueryQuery',
    variables: JSON.stringify({
      shortcode,
      fetch_comment_count: 'null', parent_comment_count: 'null',
      child_comment_count: 'null', fetch_like_count: 'null',
      has_threaded_comments: 'false',
      hoisted_comment_id: 'null', hoisted_reply_id: 'null',
    }),
    server_timestamps: 'true',
    doc_id: '8845758582119845',
  });

  const gqlResp = await fetch('https://www.instagram.com/api/graphql', {
    method: 'POST',
    headers: {
      'User-Agent': ua, Accept: '*/*', 'Accept-Language': 'en-US,en;q=0.9',
      'Content-Type': 'application/x-www-form-urlencoded',
      'X-FB-Friendly-Name': 'PolarisPostActionLoadPostQueryQuery',
      'X-CSRFToken': csrf, 'X-IG-App-ID': '1217981644879628',
      'X-FB-LSD': lsd, 'X-ASBD-ID': '129477',
      Origin: 'https://www.instagram.com',
      Referer: `https://www.instagram.com/p/${shortcode}/`,
      Cookie: cookieStr,
    },
    body: body.toString(),
    signal: AbortSignal.timeout(12000),
  });

  const gqlData = await gqlResp.json();
  const media = gqlData?.data?.xdt_shortcode_media;
  if (!media?.is_video || !media.video_url) return null;

  return {
    videoUrl: media.video_url,
    thumbnail: media.thumbnail_src || media.display_url || null,
    title: media.title || media.accessibility_caption || null,
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// Method G — Instagram Android mobile API
// ─────────────────────────────────────────────────────────────────────────────
async function methodG_mobileApi(shortcode) {
  const mediaId = shortcodeToMediaId(shortcode);
  const resp = await fetch(`https://i.instagram.com/api/v1/media/${mediaId}/info/`, {
    headers: {
      'User-Agent': IG_ANDROID_UA,
      'X-IG-App-ID': '567067343352427',
      'X-IG-Connection-Type': 'WIFI',
      'X-IG-Capabilities': '3brTv10=',
      'Accept-Language': 'en-US',
      'X-FB-HTTP-Engine': 'Liger',
    },
    signal: AbortSignal.timeout(12000),
  });
  if (!resp.ok) return null;

  const data = await resp.json();
  const item = data?.items?.[0];
  if (!item) return null;

  const versions = item.video_versions || [];
  if (versions.length > 0) {
    return {
      videoUrl: versions[0].url,
      thumbnail: item.image_versions2?.candidates?.[0]?.url || null,
      title: item.caption?.text?.slice(0, 100) || null,
    };
  }
  for (const slide of item.carousel_media || []) {
    const sv = slide.video_versions || [];
    if (sv.length > 0) {
      return {
        videoUrl: sv[0].url,
        thumbnail: slide.image_versions2?.candidates?.[0]?.url || null,
        title: item.caption?.text?.slice(0, 100) || null,
      };
    }
  }
  return null;
}

// ─────────────────────────────────────────────────────────────────────────────
// Main handler
// ─────────────────────────────────────────────────────────────────────────────
module.exports = async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') return res.status(200).end();
  if (req.method !== 'POST')
    return res.status(405).json({ success: false, error: 'Method not allowed' });

  const { url } = req.body || {};
  if (!url) return res.status(400).json({ success: false, error: 'URL is required' });

  const cleanUrl = cleanInstagramUrl(url);
  const shortcode = extractShortcode(cleanUrl);
  if (!shortcode)
    return res.status(400).json({ success: false, error: 'Invalid Instagram URL. Use a /p/ or /reel/ link.' });

  let lastError = 'Unable to extract video from this post.';

  // ── Method H: cobalt.tools (primary) ───────────────────────────────────────
  try {
    const cobalt = await methodH_cobalt(cleanUrl);
    if (cobalt?.videoUrl) {
      return res.json({ success: true, ...cobalt });
    }
  } catch (e) {
    lastError = e.message;
  }

  // ── Retry loop: methods A-G ─────────────────────────────────────────────────
  for (let attempt = 0; attempt < 2; attempt++) {
    if (attempt > 0) await delay(300 + Math.random() * 500);

    const ua = USER_AGENTS[attempt % USER_AGENTS.length];

    try {
      // Main page + A-D
      let html = '';
      try {
        html = await fetchPage(cleanUrl, ua);
      } catch (e) {
        lastError = e.message;
      }

      if (html && !isLoginPage(html)) {
        const videoUrl = runAllTextMethods(html);
        if (videoUrl) {
          return res.json({
            success: true,
            videoUrl,
            thumbnail: extractThumbnail(html),
            title: extractTitle(html),
          });
        }
      }

      // Method E — embed page
      try {
        const embedUrl = await methodE_embedPage(shortcode, ua);
        if (embedUrl) {
          return res.json({
            success: true,
            videoUrl: embedUrl,
            thumbnail: extractThumbnail(html),
            title: extractTitle(html),
          });
        }
      } catch {}

      // Method F — GraphQL
      try {
        const gql = await methodF_graphQL(shortcode, ua);
        if (gql?.videoUrl) return res.json({ success: true, ...gql });
      } catch {}

      // Method G — mobile API
      try {
        const mob = await methodG_mobileApi(shortcode);
        if (mob?.videoUrl) return res.json({ success: true, ...mob });
      } catch {}

    } catch (err) {
      lastError = err.message;
    }
  }

  return res.json({ success: false, fallback: true, error: lastError });
};
