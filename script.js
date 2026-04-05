// NADIR DOWNLOADER - Frontend Logic

// ─── Translations ────────────────────────────────────────────────────────────
const TRANSLATIONS = {
  en: {
    subtitle: 'Download videos from social media platforms — fast, free, and easy',
    nav_platforms: 'Platforms',
    nav_how: 'How it works',
    input_placeholder: 'Paste your video link here...',
    btn_download: 'Download',
    helper_text: 'Supports: Facebook, TikTok, YouTube, Instagram, Pinterest, X (Twitter)',
    how_title: 'How it works',
    step1_title: '1. Copy the Link',
    step1_desc: 'Copy the video URL from your favorite social media platform',
    step2_title: '2. Paste it Here',
    step2_desc: 'Paste the link into the input field above — platform is auto-detected',
    step3_title: '3. Download',
    step3_desc: 'Click the download button and get your video instantly',
    footer_copy: '© 2025 NADIR DOWNLOADER. All rights reserved.',
    footer_dev: 'Developer: ',
    pwa_install_text: 'Install app for a better experience',
    error_no_url: 'Please enter a video URL.',
    error_unsupported: 'Unsupported platform. Please use a Facebook, TikTok, YouTube, Instagram, Pinterest, or X (Twitter) link.',
    error_generic: 'Could not fetch video info. Please try again.',
    loading: 'Fetching video info...',
    btn_downloading: 'Fetching...',
    no_results: 'No downloadable formats found.',
  },
  ar: {
    subtitle: 'تحميل مقاطع الفيديو من منصات التواصل الاجتماعي — بسرعة ومجاناً وبسهولة',
    nav_platforms: 'المنصات',
    nav_how: 'كيف يعمل',
    input_placeholder: 'الصق رابط الفيديو هنا...',
    btn_download: 'تحميل',
    helper_text: 'يدعم: فيسبوك، تيك توك، يوتيوب، إنستغرام، بينترست، تويتر',
    how_title: 'كيف يعمل',
    step1_title: '١. انسخ الرابط',
    step1_desc: 'انسخ رابط الفيديو من منصة التواصل الاجتماعي المفضلة لديك',
    step2_title: '٢. الصقه هنا',
    step2_desc: 'الصق الرابط في حقل الإدخال أعلاه — يتم اكتشاف المنصة تلقائياً',
    step3_title: '٣. تحميل',
    step3_desc: 'انقر على زر التحميل واحصل على الفيديو فوراً',
    footer_copy: '© 2025 NADIR DOWNLOADER. جميع الحقوق محفوظة.',
    footer_dev: 'تطوير : ',
    pwa_install_text: 'ثبّت التطبيق للحصول على تجربة أفضل',
    error_no_url: 'الرجاء إدخال رابط الفيديو.',
    error_unsupported: 'المنصة غير مدعومة. استخدم رابطاً من فيسبوك أو تيك توك أو يوتيوب أو إنستغرام أو بينترست أو تويتر.',
    error_generic: 'تعذّر جلب معلومات الفيديو. حاول مرة أخرى.',
    loading: 'جارٍ جلب معلومات الفيديو...',
    btn_downloading: 'جارٍ الجلب...',
    no_results: 'لم يتم العثور على صيغ قابلة للتحميل.',
  },
  fr: {
    subtitle: 'Téléchargez des vidéos depuis les réseaux sociaux — rapide, gratuit et simple',
    nav_platforms: 'Plateformes',
    nav_how: 'Comment ça marche',
    input_placeholder: 'Collez votre lien vidéo ici...',
    btn_download: 'Télécharger',
    helper_text: 'Prend en charge : Facebook, TikTok, YouTube, Instagram, Pinterest, X (Twitter)',
    how_title: 'Comment ça marche',
    step1_title: '1. Copiez le lien',
    step1_desc: 'Copiez l\'URL de la vidéo depuis votre plateforme préférée',
    step2_title: '2. Collez-le ici',
    step2_desc: 'Collez le lien dans le champ ci-dessus — la plateforme est détectée automatiquement',
    step3_title: '3. Téléchargez',
    step3_desc: 'Cliquez sur le bouton de téléchargement et obtenez votre vidéo instantanément',
    footer_copy: '© 2025 NADIR DOWNLOADER. Tous droits réservés.',
    footer_dev: 'Développement : ',
    pwa_install_text: 'Installez l\'application pour une meilleure expérience',
    error_no_url: 'Veuillez saisir une URL vidéo.',
    error_unsupported: 'Plateforme non prise en charge. Utilisez un lien Facebook, TikTok, YouTube, Instagram, Pinterest ou X (Twitter).',
    error_generic: 'Impossible de récupérer les informations vidéo. Veuillez réessayer.',
    loading: 'Récupération des informations vidéo...',
    btn_downloading: 'Récupération...',
    no_results: 'Aucun format téléchargeable trouvé.',
  },
};

// ─── State ────────────────────────────────────────────────────────────────────
let currentLang = localStorage.getItem('lang') || 'en';
let deferredPrompt = null;

// ─── Platform helpers ─────────────────────────────────────────────────────────
const PLATFORM_ICONS = {
  facebook: 'fab fa-facebook-f',
  tiktok: 'fab fa-tiktok',
  youtube: 'fab fa-youtube',
  instagram: 'fab fa-instagram',
  pinterest: 'fab fa-pinterest-p',
  twitter: 'fab fa-x-twitter',
};

const PLATFORM_COLORS = {
  facebook: '#1877f2',
  tiktok: '#000000',
  youtube: '#ff0000',
  instagram: '#e1306c',
  pinterest: '#e60023',
  twitter: '#000000',
};

function detectPlatform(url) {
  const u = url.toLowerCase();
  if (/facebook\.com|fb\.com|fb\.watch|fbcdn\.net/.test(u)) return 'facebook';
  if (/tiktok\.com|vm\.tiktok\.com/.test(u)) return 'tiktok';
  if (/youtube\.com|youtu\.be|yt\.be/.test(u)) return 'youtube';
  if (/instagram\.com|instagr\.am/.test(u)) return 'instagram';
  if (/pinterest\.com|pin\.it/.test(u)) return 'pinterest';
  if (/twitter\.com|x\.com|t\.co/.test(u)) return 'twitter';
  return null;
}

// ─── i18n ─────────────────────────────────────────────────────────────────────
function t(key) {
  return (TRANSLATIONS[currentLang] && TRANSLATIONS[currentLang][key]) ||
    (TRANSLATIONS.en[key]) || key;
}

function applyTranslations() {
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.getAttribute('data-i18n');
    el.textContent = t(key);
  });
  document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
    const key = el.getAttribute('data-i18n-placeholder');
    el.placeholder = t(key);
  });
  const isRTL = currentLang === 'ar';
  document.documentElement.setAttribute('dir', isRTL ? 'rtl' : 'ltr');
  document.documentElement.setAttribute('lang', currentLang);
}

function setLang(lang) {
  currentLang = lang;
  localStorage.setItem('lang', lang);
  applyTranslations();
  document.querySelectorAll('.lang-option').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.lang === lang);
  });
}

// ─── Particles ────────────────────────────────────────────────────────────────
function initParticles() {
  const container = document.getElementById('particles');
  if (!container) return;
  for (let i = 0; i < 20; i++) {
    const p = document.createElement('div');
    p.className = 'particle';
    p.style.cssText = `
      left: ${Math.random() * 100}%;
      top: ${Math.random() * 100}%;
      width: ${Math.random() * 6 + 2}px;
      height: ${Math.random() * 6 + 2}px;
      animation-delay: ${Math.random() * 8}s;
      animation-duration: ${Math.random() * 10 + 8}s;
    `;
    container.appendChild(p);
  }
}

// ─── Icon update based on URL ─────────────────────────────────────────────────
function updateIcon(platform) {
  const iconEl = document.getElementById('platformIcon');
  const iconBox = document.getElementById('iconBox');
  if (!iconEl || !iconBox) return;

  if (platform && PLATFORM_ICONS[platform]) {
    iconEl.className = PLATFORM_ICONS[platform];
    iconBox.style.color = PLATFORM_COLORS[platform] || '';
  } else {
    iconEl.className = 'fas fa-cloud-arrow-down';
    iconBox.style.color = '';
  }
}

// ─── Download logic ───────────────────────────────────────────────────────────
async function handleDownload() {
  const urlInput = document.getElementById('urlInput');
  const downloadBtn = document.getElementById('downloadBtn');
  const btnText = downloadBtn.querySelector('.btn-text');
  const resultsSection = document.getElementById('resultsSection');

  const url = urlInput.value.trim();
  if (!url) {
    showError(t('error_no_url'));
    return;
  }

  const platform = detectPlatform(url);
  if (!platform) {
    showError(t('error_unsupported'));
    return;
  }

  // Loading state
  downloadBtn.disabled = true;
  if (btnText) btnText.textContent = t('btn_downloading');
  clearError();
  if (resultsSection) resultsSection.style.display = 'none';

  try {
    const response = await fetch('/api/download', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    });

    const data = await response.json();

    if (!data.success) {
      showError(data.error || t('error_generic'));
      return;
    }

    renderResults(data, platform);
  } catch (err) {
    showError(t('error_generic'));
  } finally {
    downloadBtn.disabled = false;
    if (btnText) btnText.textContent = t('btn_download');
  }
}

// ─── Render results ───────────────────────────────────────────────────────────
function renderResults(data, platform) {
  const resultsSection = document.getElementById('resultsSection');
  const previewThumbnail = document.getElementById('previewThumbnail');
  const previewPlayIcon = document.getElementById('previewPlayIcon');
  const previewTitleText = document.getElementById('previewTitleText');
  const previewDownloads = document.getElementById('previewDownloads');
  const previewPlatformIcon = document.getElementById('previewPlatformIcon');
  const previewPlatformName = document.getElementById('previewPlatformName');

  // Thumbnail
  if (previewThumbnail && data.thumbnail) {
    previewThumbnail.style.backgroundImage = `url(${data.thumbnail})`;
    previewThumbnail.style.backgroundSize = 'cover';
    previewThumbnail.style.backgroundPosition = 'center';
  }

  // Platform badge
  if (previewPlatformIcon && PLATFORM_ICONS[platform]) {
    previewPlatformIcon.className = PLATFORM_ICONS[platform];
  }
  if (previewPlatformName) {
    const names = {
      facebook: 'Facebook', tiktok: 'TikTok', youtube: 'YouTube',
      instagram: 'Instagram', pinterest: 'Pinterest', twitter: 'X (Twitter)',
    };
    previewPlatformName.textContent = names[platform] || platform;
  }

  // Title
  if (previewTitleText) {
    previewTitleText.textContent = data.title || 'Video';
  }

  // Download links
  if (previewDownloads && data.links) {
    previewDownloads.innerHTML = '';
    if (data.links.length === 0) {
      previewDownloads.innerHTML = `<p class="no-results">${t('no_results')}</p>`;
    } else {
      data.links.forEach(link => {
        const btn = document.createElement('a');
        const proxyUrl = buildProxyUrl(link, platform, data.title || 'video');
        btn.href = proxyUrl;
        btn.download = `${sanitizeFilename(data.title || 'video')}.${link.format || 'mp4'}`;
        btn.className = 'download-link-btn';
        btn.innerHTML = `
          <span class="dl-quality">${link.quality || 'Video'}</span>
          ${link.size ? `<span class="dl-size">${link.size}</span>` : ''}
          <span class="dl-format">${(link.format || 'mp4').toUpperCase()}</span>
          <i class="fas fa-download dl-icon"></i>
        `;
        previewDownloads.appendChild(btn);
      });
    }
  }

  if (resultsSection) {
    resultsSection.style.display = 'block';
    resultsSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
}

function buildProxyUrl(link, platform, title) {
  const params = new URLSearchParams({
    url: link.url,
    platform: platform,
    filename: sanitizeFilename(title),
    format: link.format || 'mp4',
  });
  if (link.format_id) {
    params.set('format_id', link.format_id);
  }
  return `/api/proxy?${params.toString()}`;
}

function sanitizeFilename(name) {
  return (name || 'video').replace(/[^\w\s\-.]/g, '').trim().slice(0, 100) || 'video';
}

// ─── Error display ────────────────────────────────────────────────────────────
function showError(msg) {
  let errEl = document.getElementById('errorMsg');
  if (!errEl) {
    errEl = document.createElement('p');
    errEl.id = 'errorMsg';
    errEl.className = 'error-msg';
    const wrapper = document.getElementById('inputWrapper');
    if (wrapper) wrapper.after(errEl);
  }
  errEl.textContent = msg;
  errEl.style.display = 'block';
}

function clearError() {
  const errEl = document.getElementById('errorMsg');
  if (errEl) errEl.style.display = 'none';
}

// ─── PWA ──────────────────────────────────────────────────────────────────────
function initPWA() {
  const banner = document.getElementById('pwaInstallBanner');
  const installBtn = document.getElementById('pwaInstallBtn');
  const closeBtn = document.getElementById('pwaCloseBtn');

  window.addEventListener('beforeinstallprompt', e => {
    e.preventDefault();
    deferredPrompt = e;
    if (banner) banner.style.display = 'flex';
  });

  if (installBtn) {
    installBtn.addEventListener('click', async () => {
      if (!deferredPrompt) return;
      deferredPrompt.prompt();
      const { outcome } = await deferredPrompt.userChoice;
      deferredPrompt = null;
      if (banner) banner.style.display = 'none';
    });
  }

  if (closeBtn) {
    closeBtn.addEventListener('click', () => {
      if (banner) banner.style.display = 'none';
    });
  }

  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js').catch(() => {});
  }
}

// ─── Language switcher ────────────────────────────────────────────────────────
function initLangSwitcher() {
  const langBtn = document.getElementById('langBtn');
  const langDropdown = document.getElementById('langDropdown');

  if (langBtn && langDropdown) {
    langBtn.addEventListener('click', e => {
      e.stopPropagation();
      langDropdown.classList.toggle('open');
    });

    document.addEventListener('click', () => {
      langDropdown.classList.remove('open');
    });

    document.querySelectorAll('.lang-option').forEach(btn => {
      btn.addEventListener('click', () => {
        setLang(btn.dataset.lang);
        langDropdown.classList.remove('open');
      });
    });
  }
}

// ─── URL input live detection ─────────────────────────────────────────────────
function initInputDetection() {
  const urlInput = document.getElementById('urlInput');
  if (!urlInput) return;

  urlInput.addEventListener('input', () => {
    const platform = detectPlatform(urlInput.value.trim());
    updateIcon(platform);

    // Highlight matching platform badge
    document.querySelectorAll('.badge').forEach(badge => {
      badge.classList.toggle('active', badge.dataset.platform === platform);
    });
  });

  urlInput.addEventListener('keydown', e => {
    if (e.key === 'Enter') handleDownload();
  });
}

// ─── Paste button ─────────────────────────────────────────────────────────────
function initPasteBtn() {
  const pasteBtn = document.getElementById('pasteBtn');
  if (!pasteBtn) return;
  pasteBtn.addEventListener('click', async () => {
    try {
      const text = await navigator.clipboard.readText();
      const urlInput = document.getElementById('urlInput');
      if (urlInput) {
        urlInput.value = text;
        urlInput.dispatchEvent(new Event('input'));
      }
    } catch (e) {
      // Clipboard not available; ignore silently
    }
  });
}

// ─── Download button ──────────────────────────────────────────────────────────
function initDownloadBtn() {
  const downloadBtn = document.getElementById('downloadBtn');
  if (downloadBtn) {
    downloadBtn.addEventListener('click', handleDownload);
  }
}

// ─── Init ─────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  applyTranslations();
  initParticles();
  initPWA();
  initLangSwitcher();
  initInputDetection();
  initPasteBtn();
  initDownloadBtn();
});
