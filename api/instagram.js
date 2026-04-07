/**
 * NADIR DOWNLOADER — /api/instagram
 * POST { url: "https://www.instagram.com/..." }
 *
 * Multi-method Instagram video extraction (no paid APIs):
 *   A  og:video  meta tag
 *   B  video_url / playable_url in page JSON blobs
 *   C  window.__additionalDataLoaded  +  application/ld+json  contentUrl
 *   D  video_versions[].url  (GraphQL-style JSON)
 *   E  /embed/captioned/ page (same A-D pass)
 *   F  GraphQL API  /api/graphql  with fresh session cookies
 *   G  Instagram mobile API  (i.instagram.com)
 *
 * Anti-block: 2 retries · 300-800 ms jitter · 2 rotated User-Agents
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
// URL helpers
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
  const m = url.match(/instagram\.com\/(?:p|reel|reels|tv)\/([A-Za-z0-9_-]+)/i)
    || url.match(/instagr\.am\/p\/([A-Za-z0-9_-]+)/i);
  return m ? m[1] : null;
}

function shortcodeToMediaId(shortcode) {
  const alpha = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_';
  let id = BigInt(0);
  for (const ch of shortcode) {
    id = id * BigInt(64) + BigInt(alpha.indexOf(ch));
  }
  return id.toString();
}

function delay(ms) {
  return new Promise(r => setTimeout(r, ms));
}

// ─────────────────────────────────────────────────────────────────────────────
// Page-level detection
// ─────────────────────────────────────────────────────────────────────────────
function isLoginPage(html) {
  return (
    html.includes('"login_page"') ||
    html.includes('id="loginForm"') ||
    html.includes('class="LoginForm"') ||
    (html.includes('"require_login"') && html.includes('true'))
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Extraction methods A – D  (from raw HTML string)
// ─────────────────────────────────────────────────────────────────────────────

// A — og:video
function methodA_ogVideo(html) {
  return (
    html.match(/<meta[^>]+property="og:video(?::url)?"[^>]+content="([^"]+)"/i)?.[1] ||
    html.match(/<meta[^>]+content="([^"]+)"[^>]+property="og:video(?::url)?"/i)?.[1] ||
    null
  )?.replace(/&amp;/g, '&') ?? null;
}

// B — video_url / playable_url anywhere in page
function methodB_videoUrlJson(html) {
  const fields = ['video_url', 'playable_url', 'playable_url_quality_hd'];
  for (const f of fields) {
    const re = new RegExp(`"${f}"\\s*:\\s*"([^"\\\\]+(?:\\\\.[^"\\\\]*)*)"`, 'i');
    const m = html.match(re);
    if (m) return m[1].replace(/\\u0026/g, '&').replace(/\\\//g, '/').replace(/\\"/g, '"');
  }
  return null;
}

// C — application/ld+json  +  window.__additionalDataLoaded
function methodC_ldJson(html) {
  // ld+json scripts
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

  // window.__additionalDataLoaded(key, {...})
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

  // Generic JSON blocks in <script> tags
  for (const sm of html.matchAll(/<script[^>]*>([\s\S]{200,100000}?)<\/script>/gi)) {
    const snippet = sm[1];
    try {
      const parsed = JSON.parse(snippet);
      const url = deepFindVideoUrl(parsed);
      if (url) return url;
    } catch {}
  }

  return null;
}

// D — video_versions[].url
function methodD_videoVersions(html) {
  const m = html.match(/"video_versions"\s*:\s*\[[\s\S]*?"url"\s*:\s*"([^"\\]+(?:\\.[^"\\]*)*)"/);
  return m ? m[1].replace(/\\u0026/g, '&').replace(/\\\//g, '/') : null;
}

// Deep find video_url in a JSON object (recursive, max depth 10)
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

// Run A-D on any HTML string; return first non-null
function runAllTextMethods(html) {
  return (
    methodA_ogVideo(html) ||
    methodB_videoUrlJson(html) ||
    methodC_ldJson(html) ||
    methodD_videoVersions(html) ||
    null
  );
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
    ? m[1]
        .replace(/\s+on Instagram.*$/i, '')
        .replace(/\s*•\s*Instagram.*$/i, '')
        .trim()
    : null;
}

// ─────────────────────────────────────────────────────────────────────────────
// Network helpers
// ─────────────────────────────────────────────────────────────────────────────
async function fetchPage(url, ua, extraHeaders = {}) {
  const resp = await fetch(url, {
    method: 'GET',
    headers: {
      'User-Agent': ua,
      Accept: 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
      'Accept-Language': 'en-US,en;q=0.9',
      'Accept-Encoding': 'gzip, deflate, br',
      Referer: 'https://www.instagram.com/',
      Origin: 'https://www.instagram.com',
      'Sec-Fetch-Dest': 'document',
      'Sec-Fetch-Mode': 'navigate',
      'Sec-Fetch-Site': 'same-origin',
      'Cache-Control': 'no-cache',
      Pragma: 'no-cache',
      DNT: '1',
      'Upgrade-Insecure-Requests': '1',
      ...extraHeaders,
    },
    redirect: 'follow',
  });
  if (!resp.ok) throw new Error(`HTTP ${resp.status} for ${url}`);
  return resp.text();
}

// ─────────────────────────────────────────────────────────────────────────────
// Method E — /embed/captioned/ page
// ─────────────────────────────────────────────────────────────────────────────
async function methodE_embedPage(shortcode, ua) {
  const html = await fetchPage(
    `https://www.instagram.com/p/${shortcode}/embed/captioned/`,
    ua,
    { 'Sec-Fetch-Dest': 'iframe', 'Sec-Fetch-Mode': 'navigate', 'Sec-Fetch-Site': 'same-origin' }
  );
  return runAllTextMethods(html);
}

// ─────────────────────────────────────────────────────────────────────────────
// Method F — GraphQL API with fresh session cookies
// ─────────────────────────────────────────────────────────────────────────────
async function methodF_graphQL(shortcode, ua) {
  // Get fresh cookies + LSD token
  const homeResp = await fetch('https://www.instagram.com/', {
    headers: { 'User-Agent': ua, Accept: 'text/html,*/*', 'Accept-Language': 'en-US,en;q=0.9' },
    redirect: 'follow',
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
  const cookieStr = [
    `csrftoken=${csrf}`,
    mid ? `mid=${mid}` : '',
  ]
    .filter(Boolean)
    .join('; ');

  const bodyParams = new URLSearchParams({
    av: '0',
    __d: 'www',
    __user: '0',
    __a: '1',
    __req: '3',
    __ccg: 'UNKNOWN',
    lsd,
    jazoest: '2957',
    fb_api_caller_class: 'RelayModern',
    fb_api_req_friendly_name: 'PolarisPostActionLoadPostQueryQuery',
    variables: JSON.stringify({
      shortcode,
      fetch_comment_count: 'null',
      parent_comment_count: 'null',
      child_comment_count: 'null',
      fetch_like_count: 'null',
      has_threaded_comments: 'false',
      hoisted_comment_id: 'null',
      hoisted_reply_id: 'null',
    }),
    server_timestamps: 'true',
    doc_id: '8845758582119845',
  });

  const gqlResp = await fetch('https://www.instagram.com/api/graphql', {
    method: 'POST',
    headers: {
      'User-Agent': ua,
      Accept: '*/*',
      'Accept-Language': 'en-US,en;q=0.9',
      'Content-Type': 'application/x-www-form-urlencoded',
      'X-FB-Friendly-Name': 'PolarisPostActionLoadPostQueryQuery',
      'X-CSRFToken': csrf,
      'X-IG-App-ID': '1217981644879628',
      'X-FB-LSD': lsd,
      'X-ASBD-ID': '129477',
      'Sec-Fetch-Dest': 'empty',
      'Sec-Fetch-Mode': 'cors',
      'Sec-Fetch-Site': 'same-origin',
      Origin: 'https://www.instagram.com',
      Referer: `https://www.instagram.com/p/${shortcode}/`,
      Cookie: cookieStr,
    },
    body: bodyParams.toString(),
  });

  const gqlData = await gqlResp.json();
  const media = gqlData?.data?.xdt_shortcode_media;
  if (!media || !media.is_video || !media.video_url) return null;

  return {
    videoUrl: media.video_url,
    thumbnail: media.thumbnail_src || media.display_url || null,
    title: media.title || media.accessibility_caption || null,
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// Method G — Instagram Android mobile API  (i.instagram.com)
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
      'Accept-Encoding': 'gzip, deflate',
      'X-FB-HTTP-Engine': 'Liger',
      Connection: 'keep-alive',
    },
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

  // Carousel: return first video found
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
  if (req.method !== 'POST') {
    return res.status(405).json({ success: false, error: 'Method not allowed' });
  }

  const { url } = req.body || {};
  if (!url) return res.status(400).json({ success: false, error: 'URL is required' });

  const cleanUrl = cleanInstagramUrl(url);
  const shortcode = extractShortcode(cleanUrl);
  if (!shortcode) {
    return res.status(400).json({ success: false, error: 'Invalid Instagram URL. Use a /p/ or /reel/ link.' });
  }

  let lastError = 'Unable to extract video from this post.';

  for (let attempt = 0; attempt < 2; attempt++) {
    if (attempt > 0) await delay(300 + Math.random() * 500);

    const ua = USER_AGENTS[attempt % USER_AGENTS.length];

    try {
      // ── Main page fetch + A-D ────────────────────────────────────────────
      let html;
      try {
        html = await fetchPage(cleanUrl, ua);
      } catch (e) {
        lastError = e.message;
        continue;
      }

      if (isLoginPage(html)) {
        lastError = 'Instagram requires login to view this post.';
        // Still try other methods below
      } else {
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

      // ── Method E — embed page ────────────────────────────────────────────
      try {
        const embedUrl = await methodE_embedPage(shortcode, ua);
        if (embedUrl) {
          return res.json({
            success: true,
            videoUrl: embedUrl,
            thumbnail: extractThumbnail(html || ''),
            title: extractTitle(html || ''),
          });
        }
      } catch {}

      // ── Method F — GraphQL ───────────────────────────────────────────────
      try {
        const gqlResult = await methodF_graphQL(shortcode, ua);
        if (gqlResult?.videoUrl) {
          return res.json({ success: true, ...gqlResult });
        }
      } catch {}

      // ── Method G — mobile API ────────────────────────────────────────────
      try {
        const mobileResult = await methodG_mobileApi(shortcode);
        if (mobileResult?.videoUrl) {
          return res.json({ success: true, ...mobileResult });
        }
      } catch {}

    } catch (err) {
      lastError = err.message;
    }
  }

  return res.json({ success: false, fallback: true, error: lastError });
};
