/* ============================================
   NADIR DOWNLOADER - Main Script
   Platform detection, icon switching, on-site download
   ============================================ */

// ==================== TRANSLATIONS ====================
var currentLang = localStorage.getItem('nadir_lang') || 'en';

var TRANSLATIONS = {
    en: {
        nav_platforms: 'Platforms',
        nav_how: 'How it works',
        subtitle: 'Download videos from social media platforms \u2014 fast, free, and easy',
        input_placeholder: 'Paste your video link here...',
        btn_download: 'Download',
        btn_downloading: 'Downloading...',
        helper_text: 'Supports: Facebook, TikTok, YouTube, Instagram, Pinterest, X (Twitter)',
        how_title: 'How it works',
        step1_title: '1. Copy the Link',
        step1_desc: 'Copy the video URL from your favorite social media platform',
        step2_title: '2. Paste it Here',
        step2_desc: 'Paste the link into the input field above \u2014 platform is auto-detected',
        step3_title: '3. Download',
        step3_desc: 'Click the download button and get your video instantly',
        footer_copy: '\u00A9 2025 NADIR DOWNLOADER. All rights reserved.',
        footer_dev: '\u062a\u0637\u0648\u064a\u0631 : ',
        toast_paste_link: 'Please paste a video link first',
        toast_unsupported: 'Unsupported platform. Try Facebook, TikTok, YouTube, Instagram, Pinterest, or X',
        toast_extracting: 'Extracting download links from ',
        toast_ready: 'Download links ready!',
        toast_failed: 'Failed to extract links',
        toast_network: 'Connection error',
        toast_pasted: 'Link pasted!',
        toast_paste_manual: 'Press Ctrl+V to paste',
        extracting_video: 'Extracting video...',
        error_extract: 'Could not extract download links. Please try again.',
        error_network: 'Network error. Please check your connection and try again.',
        detected_suffix: ' detected \u2014 ready to download!',
        pwa_install_text: 'Install app for a better experience'
    },
    ar: {
        nav_platforms: '\u0627\u0644\u0645\u0646\u0635\u0627\u062a',
        nav_how: '\u0643\u064a\u0641 \u064a\u0639\u0645\u0644',
        subtitle: '\u062d\u0645\u0651\u0644 \u0627\u0644\u0641\u064a\u062f\u064a\u0648\u0647\u0627\u062a \u0645\u0646 \u0645\u0646\u0635\u0627\u062a \u0627\u0644\u062a\u0648\u0627\u0635\u0644 \u0627\u0644\u0627\u062c\u062a\u0645\u0627\u0639\u064a \u2014 \u0628\u0633\u0631\u0639\u0629\u060c \u0645\u062c\u0627\u0646\u0627\u064b \u0648 \u0628\u0633\u0647\u0648\u0644\u0629',
        input_placeholder: '\u0627\u0644\u0635\u0642 \u0631\u0627\u0628\u0637 \u0627\u0644\u0641\u064a\u062f\u064a\u0648 \u0647\u0646\u0627...',
        btn_download: '\u062a\u062d\u0645\u064a\u0644',
        btn_downloading: '\u062c\u0627\u0631\u064a \u0627\u0644\u062a\u062d\u0645\u064a\u0644...',
        helper_text: '\u064a\u062f\u0639\u0645: Facebook, TikTok, YouTube, Instagram, Pinterest, X (Twitter)',
        how_title: '\u0643\u064a\u0641 \u064a\u0639\u0645\u0644',
        step1_title: '1. \u0627\u0646\u0633\u062e \u0627\u0644\u0631\u0627\u0628\u0637',
        step1_desc: '\u0627\u0646\u0633\u062e \u0631\u0627\u0628\u0637 \u0627\u0644\u0641\u064a\u062f\u064a\u0648 \u0645\u0646 \u0645\u0646\u0635\u0629 \u0627\u0644\u062a\u0648\u0627\u0635\u0644 \u0627\u0644\u0627\u062c\u062a\u0645\u0627\u0639\u064a \u0627\u0644\u0645\u0641\u0636\u0644\u0629 \u0644\u062f\u064a\u0643',
        step2_title: '2. \u0627\u0644\u0635\u0642\u0647 \u0647\u0646\u0627',
        step2_desc: '\u0627\u0644\u0635\u0642 \u0627\u0644\u0631\u0627\u0628\u0637 \u0641\u064a \u062d\u0642\u0644 \u0627\u0644\u0625\u062f\u062e\u0627\u0644 \u0623\u0639\u0644\u0627\u0647 \u2014 \u064a\u062a\u0645 \u0627\u0644\u0643\u0634\u0641 \u0639\u0646 \u0627\u0644\u0645\u0646\u0635\u0629 \u062a\u0644\u0642\u0627\u0626\u064a\u0627\u064b',
        step3_title: '3. \u062d\u0645\u0651\u0644',
        step3_desc: '\u0627\u0636\u063a\u0637 \u0639\u0644\u0649 \u0632\u0631 \u0627\u0644\u062a\u062d\u0645\u064a\u0644 \u0648\u0627\u062d\u0635\u0644 \u0639\u0644\u0649 \u0627\u0644\u0641\u064a\u062f\u064a\u0648 \u0641\u0648\u0631\u0627\u064b',
        footer_copy: '\u00A9 2025 NADIR DOWNLOADER. \u062c\u0645\u064a\u0639 \u0627\u0644\u062d\u0642\u0648\u0642 \u0645\u062d\u0641\u0648\u0638\u0629.',
        footer_dev: '\u062a\u0637\u0648\u064a\u0631 : ',
        toast_paste_link: '\u0627\u0644\u0631\u062c\u0627\u0621 \u0644\u0635\u0642 \u0631\u0627\u0628\u0637 \u0627\u0644\u0641\u064a\u062f\u064a\u0648 \u0623\u0648\u0644\u0627\u064b',
        toast_unsupported: '\u0645\u0646\u0635\u0629 \u063a\u064a\u0631 \u0645\u062f\u0639\u0648\u0645\u0629. \u062c\u0631\u0628 Facebook, TikTok, YouTube, Instagram, Pinterest, \u0623\u0648 X',
        toast_extracting: '\u062c\u0627\u0631\u064a \u0627\u0633\u062a\u062e\u0631\u0627\u062c \u0631\u0648\u0627\u0628\u0637 \u0627\u0644\u062a\u062d\u0645\u064a\u0644 \u0645\u0646 ',
        toast_ready: '\u0631\u0648\u0627\u0628\u0637 \u0627\u0644\u062a\u062d\u0645\u064a\u0644 \u062c\u0627\u0647\u0632\u0629!',
        toast_failed: '\u0641\u0634\u0644 \u0641\u064a \u0627\u0633\u062a\u062e\u0631\u0627\u062c \u0627\u0644\u0631\u0648\u0627\u0628\u0637',
        toast_network: '\u062e\u0637\u0623 \u0641\u064a \u0627\u0644\u0627\u062a\u0635\u0627\u0644',
        toast_pasted: '\u062a\u0645 \u0644\u0635\u0642 \u0627\u0644\u0631\u0627\u0628\u0637!',
        toast_paste_manual: '\u0627\u0636\u063a\u0637 Ctrl+V \u0644\u0644\u0635\u0642',
        extracting_video: '\u062c\u0627\u0631\u064a \u0627\u0633\u062a\u062e\u0631\u0627\u062c \u0627\u0644\u0641\u064a\u062f\u064a\u0648...',
        error_extract: '\u062a\u0639\u0630\u0631 \u0627\u0633\u062a\u062e\u0631\u0627\u062c \u0631\u0648\u0627\u0628\u0637 \u0627\u0644\u062a\u062d\u0645\u064a\u0644. \u062d\u0627\u0648\u0644 \u0645\u0631\u0629 \u0623\u062e\u0631\u0649.',
        error_network: '\u062e\u0637\u0623 \u0641\u064a \u0627\u0644\u0634\u0628\u0643\u0629. \u062a\u062d\u0642\u0642 \u0645\u0646 \u0627\u062a\u0635\u0627\u0644\u0643 \u0648\u062d\u0627\u0648\u0644 \u0645\u0631\u0629 \u0623\u062e\u0631\u0649.',
        detected_suffix: ' \u062a\u0645 \u0627\u0644\u0643\u0634\u0641 \u2014 \u062c\u0627\u0647\u0632 \u0644\u0644\u062a\u062d\u0645\u064a\u0644!',
        pwa_install_text: '\u062b\u0628\u0651\u062a \u0627\u0644\u062a\u0637\u0628\u064a\u0642 \u0644\u062a\u062c\u0631\u0628\u0629 \u0623\u0641\u0636\u0644'
    },
    fr: {
        nav_platforms: 'Plateformes',
        nav_how: 'Comment \u00e7a marche',
        subtitle: 'T\u00e9l\u00e9chargez des vid\u00e9os depuis les r\u00e9seaux sociaux \u2014 rapide, gratuit et facile',
        input_placeholder: 'Collez le lien de la vid\u00e9o ici...',
        btn_download: 'T\u00e9l\u00e9charger',
        btn_downloading: 'T\u00e9l\u00e9chargement...',
        helper_text: 'Supporte : Facebook, TikTok, YouTube, Instagram, Pinterest, X (Twitter)',
        how_title: 'Comment \u00e7a marche',
        step1_title: '1. Copiez le lien',
        step1_desc: 'Copiez l\u2019URL de la vid\u00e9o depuis votre r\u00e9seau social pr\u00e9f\u00e9r\u00e9',
        step2_title: '2. Collez-le ici',
        step2_desc: 'Collez le lien dans le champ ci-dessus \u2014 la plateforme est d\u00e9tect\u00e9e automatiquement',
        step3_title: '3. T\u00e9l\u00e9chargez',
        step3_desc: 'Cliquez sur le bouton de t\u00e9l\u00e9chargement et obtenez votre vid\u00e9o instantan\u00e9ment',
        footer_copy: '\u00A9 2025 NADIR DOWNLOADER. Tous droits r\u00e9serv\u00e9s.',
        footer_dev: 'D\u00e9veloppement : ',
        toast_paste_link: 'Veuillez d\u2019abord coller un lien vid\u00e9o',
        toast_unsupported: 'Plateforme non support\u00e9e. Essayez Facebook, TikTok, YouTube, Instagram, Pinterest ou X',
        toast_extracting: 'Extraction des liens depuis ',
        toast_ready: 'Liens de t\u00e9l\u00e9chargement pr\u00eats !',
        toast_failed: '\u00c9chec de l\u2019extraction des liens',
        toast_network: 'Erreur de connexion',
        toast_pasted: 'Lien coll\u00e9 !',
        toast_paste_manual: 'Appuyez sur Ctrl+V pour coller',
        extracting_video: 'Extraction de la vid\u00e9o...',
        error_extract: 'Impossible d\u2019extraire les liens. Veuillez r\u00e9essayer.',
        error_network: 'Erreur r\u00e9seau. V\u00e9rifiez votre connexion et r\u00e9essayez.',
        detected_suffix: ' d\u00e9tect\u00e9 \u2014 pr\u00eat \u00e0 t\u00e9l\u00e9charger !',
        pwa_install_text: 'Installez l\u2019appli pour une meilleure exp\u00e9rience'
    }
};

function t(key) {
    return (TRANSLATIONS[currentLang] && TRANSLATIONS[currentLang][key]) || TRANSLATIONS.en[key] || key;
}

function applyLanguage(lang) {
    currentLang = lang;
    localStorage.setItem('nadir_lang', lang);

    var htmlRoot = document.getElementById('htmlRoot');
    if (lang === 'ar') {
        htmlRoot.setAttribute('dir', 'rtl');
        htmlRoot.setAttribute('lang', 'ar');
    } else {
        htmlRoot.setAttribute('dir', 'ltr');
        htmlRoot.setAttribute('lang', lang);
    }

    // Translate all data-i18n elements
    document.querySelectorAll('[data-i18n]').forEach(function(el) {
        var key = el.getAttribute('data-i18n');
        el.textContent = t(key);
    });

    // Translate placeholders
    document.querySelectorAll('[data-i18n-placeholder]').forEach(function(el) {
        var key = el.getAttribute('data-i18n-placeholder');
        el.placeholder = t(key);
    });

    // Update active lang option
    document.querySelectorAll('.lang-option').forEach(function(opt) {
        opt.classList.remove('active');
        if (opt.dataset.lang === lang) {
            opt.classList.add('active');
        }
    });

    // Update helper text if no platform is detected
    if (!currentPlatform) {
        helperText.textContent = t('helper_text');
        helperText.style.color = '';
    }
}

function setupLanguageSwitcher() {
    var langBtn = document.getElementById('langBtn');
    var langDropdown = document.getElementById('langDropdown');
    if (!langBtn || !langDropdown) return;

    langBtn.addEventListener('click', function(e) {
        e.stopPropagation();
        langDropdown.classList.toggle('show');
    });

    document.querySelectorAll('.lang-option').forEach(function(opt) {
        opt.addEventListener('click', function(e) {
            e.stopPropagation();
            var lang = this.dataset.lang;
            applyLanguage(lang);
            langDropdown.classList.remove('show');
        });
    });

    // Close dropdown when clicking outside
    document.addEventListener('click', function() {
        langDropdown.classList.remove('show');
    });
}

// Platform configuration
const PLATFORMS = {
    facebook: {
        patterns: [/facebook\.com/, /fb\.com/, /fb\.watch/, /fbcdn\.net/],
        icon: 'fab fa-facebook-f',
        color: '#1877f2',
        glow: 'rgba(24, 119, 242, 0.3)',
        name: 'Facebook'
    },
    tiktok: {
        patterns: [/tiktok\.com/, /vm\.tiktok\.com/],
        icon: 'fab fa-tiktok',
        color: '#ff0050',
        glow: 'rgba(255, 0, 80, 0.3)',
        name: 'TikTok'
    },
    youtube: {
        patterns: [/youtube\.com/, /youtu\.be/, /yt\.be/],
        icon: 'fab fa-youtube',
        color: '#ff0000',
        glow: 'rgba(255, 0, 0, 0.3)',
        name: 'YouTube'
    },
    instagram: {
        patterns: [/instagram\.com/, /instagr\.am/],
        icon: 'fab fa-instagram',
        color: '#e4405f',
        glow: 'rgba(228, 64, 95, 0.3)',
        name: 'Instagram'
    },
    pinterest: {
        patterns: [/pinterest\.com/, /pin\.it/],
        icon: 'fab fa-pinterest-p',
        color: '#e60023',
        glow: 'rgba(230, 0, 35, 0.3)',
        name: 'Pinterest'
    },
    twitter: {
        patterns: [/twitter\.com/, /x\.com/, /t\.co/],
        icon: 'fab fa-x-twitter',
        color: '#ffffff',
        glow: 'rgba(255, 255, 255, 0.2)',
        name: 'X (Twitter)'
    }
};

// DOM Elements
const urlInput = document.getElementById('urlInput');
const downloadBtn = document.getElementById('downloadBtn');
const pasteBtn = document.getElementById('pasteBtn');
const platformIcon = document.getElementById('platformIcon');
const iconBox = document.getElementById('iconBox');
const iconContainer = document.getElementById('iconContainer');
const inputWrapper = document.getElementById('inputWrapper');
const inputIcon = document.getElementById('inputIcon');
const helperText = document.getElementById('helperText');
const iconGlow = iconContainer.querySelector('.icon-glow');
const resultsSection = document.getElementById('resultsSection');
const previewCard = document.getElementById('previewCard');
const previewThumbnail = document.getElementById('previewThumbnail');
const previewPlayIcon = document.getElementById('previewPlayIcon');
const previewPlatformIcon = document.getElementById('previewPlatformIcon');
const previewPlatformName = document.getElementById('previewPlatformName');
const previewTitleText = document.getElementById('previewTitleText');
const previewDownloads = document.getElementById('previewDownloads');

let currentPlatform = null;
let isDownloading = false;

// Detect platform from URL
function detectPlatform(url) {
    if (!url || url.trim() === '') return null;
    
    const normalizedUrl = url.toLowerCase().trim();
    
    for (const [key, platform] of Object.entries(PLATFORMS)) {
        for (const pattern of platform.patterns) {
            if (pattern.test(normalizedUrl)) {
                return key;
            }
        }
    }
    return null;
}

// Update UI based on detected platform
function updatePlatformUI(platformKey) {
    if (platformKey === currentPlatform) return;
    
    currentPlatform = platformKey;
    
    // Animate icon switch
    iconBox.classList.add('icon-switching');
    setTimeout(() => iconBox.classList.remove('icon-switching'), 500);
    
    if (platformKey && PLATFORMS[platformKey]) {
        const platform = PLATFORMS[platformKey];
        
        // Update icon
        platformIcon.className = platform.icon;
        
        // Update icon box style
        iconBox.className = 'icon-box ' + platformKey;
        
        // Update glow color
        iconGlow.style.background = platform.glow;
        iconGlow.style.opacity = '0.7';
        
        // Update input wrapper
        inputWrapper.classList.add('platform-detected');
        inputWrapper.style.setProperty('--detected-color', platform.color);
        inputWrapper.style.setProperty('--detected-glow', platform.glow);
        
        // Update input icon
        inputIcon.innerHTML = '<i class="' + platform.icon + '"></i>';
        inputIcon.style.color = platform.color;
        
        // Update helper text
        helperText.innerHTML = '<i class="' + platform.icon + '" style="color:' + platform.color + '"></i> ' + platform.name + t('detected_suffix');
        helperText.style.color = platform.color;
        
        // Update download button
        downloadBtn.style.background = platform.color;
        downloadBtn.style.color = platformKey === 'twitter' ? '#000' : '#fff';
        
        // Highlight matching badge
        document.querySelectorAll('.badge').forEach(function(badge) {
            badge.classList.remove('active');
            if (badge.dataset.platform === platformKey) {
                badge.classList.add('active');
                badge.style.borderColor = platform.color;
                badge.style.color = platform.color;
            } else {
                badge.style.borderColor = '';
                badge.style.color = '';
            }
        });
        
    } else {
        // Reset to default
        platformIcon.className = 'fas fa-cloud-arrow-down';
        iconBox.className = 'icon-box';
        iconGlow.style.background = 'var(--accent-glow)';
        iconGlow.style.opacity = '0.5';
        
        inputWrapper.classList.remove('platform-detected');
        inputWrapper.style.removeProperty('--detected-color');
        inputWrapper.style.removeProperty('--detected-glow');
        
        inputIcon.innerHTML = '<i class="fas fa-link"></i>';
        inputIcon.style.color = '';
        
        helperText.textContent = t('helper_text');
        helperText.style.color = '';
        
        downloadBtn.style.background = '';
        downloadBtn.style.color = '';
        
        document.querySelectorAll('.badge').forEach(function(badge) {
            badge.classList.remove('active');
            badge.style.borderColor = '';
            badge.style.color = '';
        });
    }
}

// Show toast notification
function showToast(message, icon) {
    // Remove existing toast
    var existingToast = document.querySelector('.toast');
    if (existingToast) existingToast.remove();
    
    var toast = document.createElement('div');
    toast.className = 'toast';
    toast.innerHTML = '<i class="' + (icon || 'fas fa-info-circle') + '"></i> ' + message;
    document.body.appendChild(toast);
    
    requestAnimationFrame(function() {
        toast.classList.add('show');
    });
    
    setTimeout(function() {
        toast.classList.remove('show');
        setTimeout(function() { toast.remove(); }, 400);
    }, 3000);
}

// Show loading state
function setLoading(loading) {
    isDownloading = loading;
    if (loading) {
        downloadBtn.innerHTML = '<span class="btn-text">' + t('btn_downloading') + '</span> <i class="fas fa-spinner fa-spin btn-icon"></i>';
        downloadBtn.disabled = true;
        downloadBtn.style.opacity = '0.7';
    } else {
        downloadBtn.innerHTML = '<span class="btn-text">' + t('btn_download') + '</span> <i class="fas fa-arrow-down btn-icon"></i>';
        downloadBtn.disabled = false;
        downloadBtn.style.opacity = '1';
    }
}

// HTML escape helper
function escapeHtml(str) {
    if (!str) return '';
    var div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// Display download results in preview card
function showResults(data, platform) {
    resultsSection.style.display = 'block';
    setTimeout(function() {
        resultsSection.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }, 100);

    var platformInfo = PLATFORMS[platform];

    // Set platform badge
    previewPlatformIcon.className = platformInfo.icon;
    previewPlatformIcon.style.color = platformInfo.color;
    previewPlatformName.textContent = platformInfo.name;

    // Set thumbnail if available
    if (data.thumbnail) {
        previewThumbnail.innerHTML = '<img src="' + escapeHtml(data.thumbnail) + '" alt="Video thumbnail"><i class="fas fa-play-circle preview-play-icon" id="previewPlayIcon"></i>';
    } else {
        previewThumbnail.innerHTML = '<i class="' + platformInfo.icon + '" style="font-size:64px; color:' + platformInfo.color + '; opacity:0.3"></i><i class="fas fa-play-circle preview-play-icon"></i>';
    }

    // Set title
    var titleStr = data.title || (platformInfo.name + ' Video');
    if (data.duration) {
        titleStr += ' (' + data.duration + ')';
    }
    previewTitleText.textContent = titleStr;
    previewTitleText.style.display = 'block';

    // Build download buttons
    var html = '';
    data.links.forEach(function(link, index) {
        var formatLabel = link.format ? link.format.toUpperCase() : 'MP4';
        var qualityLabel = link.quality || ('Quality ' + (index + 1));
        var sizeLabel = link.size ? ' - ' + link.size : '';
        var btnClass = index === 0 ? 'preview-download-btn' : 'preview-download-btn secondary';

        // Platforms whose CDN URLs need server-side headers (Referer,
        // cookies) that the browser won't attach on a plain <a> click.
        // For these we route through /api/proxy; others use direct links.
        // Pinterest uses direct pinimg.com CDN URLs that don't need
        // special headers and work fine as direct browser downloads.
        var needsProxy = ['tiktok', 'facebook', 'instagram', 'twitter'];
        var downloadHref;
        // TikTok CDN URLs require yt-dlp to download (cookies / auth
        // handled internally); pass the original page URL + format_id
        // so the proxy can use yt-dlp.
        var ytdlpPlatforms = ['tiktok', 'facebook'];
        if (ytdlpPlatforms.indexOf(platform) !== -1 && data.original_url && link.format_id) {
            var safeTitle = (data.title || 'video').replace(/[^\w\s\-]/g, '').trim().substring(0, 60) || 'video';
            downloadHref = '/api/proxy'
                + '?url=' + encodeURIComponent(data.original_url)
                + '&platform=' + encodeURIComponent(platform)
                + '&format_id=' + encodeURIComponent(link.format_id)
                + '&filename=' + encodeURIComponent(safeTitle)
                + '&format=' + encodeURIComponent(link.format || 'mp4');
        } else if (needsProxy.indexOf(platform) !== -1) {
            var safeTitle = (data.title || 'video').replace(/[^\w\s\-]/g, '').trim().substring(0, 60) || 'video';
            downloadHref = '/api/proxy'
                + '?url=' + encodeURIComponent(link.url)
                + '&platform=' + encodeURIComponent(platform)
                + '&filename=' + encodeURIComponent(safeTitle)
                + '&format=' + encodeURIComponent(link.format || 'mp4');
        } else {
            downloadHref = link.url;
        }

        html += '<a href="' + escapeHtml(downloadHref) + '" class="' + btnClass + '" download rel="noopener noreferrer">';
        html += '  <div class="dl-info">';
        html += '    <i class="fas fa-download"></i>';
        html += '    <span>' + escapeHtml(qualityLabel) + escapeHtml(sizeLabel) + '</span>';
        html += '  </div>';
        html += '  <span class="dl-format">' + formatLabel + '</span>';
        html += '</a>';
    });
    previewDownloads.innerHTML = html;
}

// Hide results
function hideResults() {
    resultsSection.style.display = 'none';
    previewDownloads.innerHTML = '';
}

// Show loading in preview card
function showPreviewLoading(platform) {
    var platformInfo = PLATFORMS[platform];
    resultsSection.style.display = 'block';
    previewPlatformIcon.className = platformInfo.icon;
    previewPlatformIcon.style.color = platformInfo.color;
    previewPlatformName.textContent = platformInfo.name;
    previewThumbnail.innerHTML = '<div class="preview-loading"><i class="fas fa-spinner fa-spin"></i><span>' + t('extracting_video') + '</span></div>';
    previewTitleText.textContent = '';
    previewTitleText.style.display = 'none';
    previewDownloads.innerHTML = '';
    setTimeout(function() {
        resultsSection.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }, 100);
}

// Show error in preview card
function showError(message) {
    previewThumbnail.innerHTML = '<div class="preview-error"><i class="fas fa-exclamation-triangle"></i>' + escapeHtml(message) + '</div>';
    previewTitleText.style.display = 'none';
    previewDownloads.innerHTML = '';
}

// Handle download - calls our serverless API
async function handleDownload() {
    var url = urlInput.value.trim();
    
    if (!url) {
        showToast(t('toast_paste_link'), 'fas fa-exclamation-triangle');
        urlInput.focus();
        return;
    }
    
    var platform = detectPlatform(url);
    
    if (!platform) {
        showToast(t('toast_unsupported'), 'fas fa-exclamation-circle');
        return;
    }

    if (isDownloading) return;
    
    setLoading(true);
    showPreviewLoading(platform);
    showToast(t('toast_extracting') + PLATFORMS[platform].name + '...', PLATFORMS[platform].icon);

    try {
        var response = await fetch('/api/download', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: url })
        });

        var data = await response.json();

        if (data.success && data.links && data.links.length > 0) {
            showResults(data, platform);
            showToast(t('toast_ready'), 'fas fa-check');
        } else {
            showError(data.error || t('error_extract'));
            showToast(t('toast_failed'), 'fas fa-exclamation-circle');
        }
    } catch (err) {
        showError(t('error_network'));
        showToast(t('toast_network'), 'fas fa-wifi');
    } finally {
        setLoading(false);
    }
}

// Handle paste from clipboard
async function handlePaste() {
    try {
        var text = await navigator.clipboard.readText();
        if (text) {
            urlInput.value = text;
            urlInput.dispatchEvent(new Event('input'));
            showToast(t('toast_pasted'), 'fas fa-check');
        }
    } catch (err) {
        // Fallback: focus input for manual paste
        urlInput.focus();
        showToast(t('toast_paste_manual'), 'fas fa-keyboard');
    }
}

// Event Listeners
urlInput.addEventListener('input', function() {
    var platform = detectPlatform(this.value);
    updatePlatformUI(platform);
});

urlInput.addEventListener('paste', function() {
    // Small delay to get pasted content
    setTimeout(function() {
        var platform = detectPlatform(urlInput.value);
        updatePlatformUI(platform);
    }, 50);
});

downloadBtn.addEventListener('click', handleDownload);
pasteBtn.addEventListener('click', handlePaste);

// Enter key to download
urlInput.addEventListener('keydown', function(e) {
    if (e.key === 'Enter') {
        handleDownload();
    }
});

// Create background particles
function createParticles() {
    var container = document.getElementById('particles');
    var particleCount = 30;
    
    for (var i = 0; i < particleCount; i++) {
        var particle = document.createElement('div');
        particle.className = 'particle';
        particle.style.left = Math.random() * 100 + '%';
        particle.style.width = (Math.random() * 3 + 1) + 'px';
        particle.style.height = particle.style.width;
        particle.style.animationDuration = (Math.random() * 15 + 10) + 's';
        particle.style.animationDelay = (Math.random() * 10) + 's';
        container.appendChild(particle);
    }
}

// Developer link - open Facebook app on mobile, web on desktop
function setupDeveloperLink() {
    var developerLink = document.getElementById('developerLink');
    if (!developerLink) return;
    
    developerLink.addEventListener('click', function(e) {
        var isMobile = /Android|iPhone|iPad|iPod|webOS|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent);
        
        if (isMobile) {
            e.preventDefault();
            // Try to open Facebook app first, fallback to web
            var fbAppUrl = 'fb://facewebmodal/f?href=https://www.facebook.com/nadir.infograph23';
            var fbWebUrl = 'https://www.facebook.com/nadir.infograph23';
            
            var appOpened = false;
            var timeout = setTimeout(function() {
                if (!appOpened) {
                    window.open(fbWebUrl, '_blank');
                }
            }, 1500);
            
            window.location.href = fbAppUrl;
            
            window.addEventListener('blur', function onBlur() {
                appOpened = true;
                clearTimeout(timeout);
                window.removeEventListener('blur', onBlur);
            });
        }
        // On desktop, the default <a> tag behavior opens the web URL in a new tab
    });
}

// Setup Facebook nav icon - open Facebook app on mobile, web on desktop
function setupFacebookNavIcon() {
    var fbNavIcon = document.getElementById('fbNavIcon');
    if (!fbNavIcon) return;
    
    fbNavIcon.addEventListener('click', function(e) {
        var isMobile = /Android|iPhone|iPad|iPod|webOS|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent);
        
        if (isMobile) {
            e.preventDefault();
            var fbAppUrl = 'fb://facewebmodal/f?href=https://www.facebook.com/nadir.infograph23';
            var fbWebUrl = 'https://www.facebook.com/nadir.infograph23';
            
            var appOpened = false;
            var timeout = setTimeout(function() {
                if (!appOpened) {
                    window.open(fbWebUrl, '_blank');
                }
            }, 1500);
            
            window.location.href = fbAppUrl;
            
            window.addEventListener('blur', function onBlur() {
                appOpened = true;
                clearTimeout(timeout);
                window.removeEventListener('blur', onBlur);
            });
        }
        // On desktop, the default <a> tag behavior opens the web URL in a new tab
    });
}

// ==================== PWA INSTALL BANNER ====================
var deferredPrompt = null;

function setupPWAInstallBanner() {
    var banner = document.getElementById('pwaInstallBanner');
    var installBtn = document.getElementById('pwaInstallBtn');
    var closeBtn = document.getElementById('pwaCloseBtn');
    if (!banner || !installBtn || !closeBtn) return;

    // Don't show if running as installed app (standalone mode)
    if (window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true) {
        return;
    }

    // Don't show on desktop
    var isMobile = /Android|iPhone|iPad|iPod|webOS|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent);
    if (!isMobile) return;

    // Don't show if user dismissed it this session
    if (sessionStorage.getItem('nadir_pwa_dismissed')) return;

    // Listen for the beforeinstallprompt event
    window.addEventListener('beforeinstallprompt', function(e) {
        e.preventDefault();
        deferredPrompt = e;
        showPWABanner();
    });

    // If no beforeinstallprompt fires (iOS, etc.), still show the banner
    // iOS doesn't fire beforeinstallprompt, so show after a delay
    setTimeout(function() {
        if (!deferredPrompt && !sessionStorage.getItem('nadir_pwa_dismissed')) {
            // Check if already installed
            if (!window.matchMedia('(display-mode: standalone)').matches && !window.navigator.standalone) {
                showPWABanner();
            }
        }
    }, 2000);

    // Install button click
    installBtn.addEventListener('click', function() {
        if (deferredPrompt) {
            deferredPrompt.prompt();
            deferredPrompt.userChoice.then(function(choiceResult) {
                if (choiceResult.outcome === 'accepted') {
                    hidePWABanner();
                }
                deferredPrompt = null;
            });
        } else {
            // iOS: show instructions
            showToast('Tap the Share button then "Add to Home Screen"', 'fas fa-share-square');
        }
    });

    // Close button click
    closeBtn.addEventListener('click', function() {
        hidePWABanner();
        sessionStorage.setItem('nadir_pwa_dismissed', '1');
    });
}

function showPWABanner() {
    var banner = document.getElementById('pwaInstallBanner');
    if (banner) {
        banner.classList.add('show');
        document.body.classList.add('pwa-banner-visible');
    }
}

function hidePWABanner() {
    var banner = document.getElementById('pwaInstallBanner');
    if (banner) {
        banner.classList.remove('show');
        document.body.classList.remove('pwa-banner-visible');
    }
}

// Register Service Worker
if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js').catch(function() {});
}

// Initialize
document.addEventListener('DOMContentLoaded', function() {
    createParticles();
    setupDeveloperLink();
    setupFacebookNavIcon();
    setupLanguageSwitcher();
    setupPWAInstallBanner();
    applyLanguage(currentLang);
    urlInput.focus();
});
