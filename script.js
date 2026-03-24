/* ============================================
   NADIR DOWNLOADER - Main Script
   Platform detection, icon switching, on-site download
   ============================================ */

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
const resultsContainer = document.getElementById('resultsContainer');
const resultsTitle = document.getElementById('resultsTitle');

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
        helperText.innerHTML = '<i class="' + platform.icon + '" style="color:' + platform.color + '"></i> ' + platform.name + ' detected — ready to download!';
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
        
        helperText.textContent = 'Supports: Facebook, TikTok, YouTube, Instagram, Pinterest, X (Twitter)';
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
        downloadBtn.innerHTML = '<span class="btn-text">Downloading...</span> <i class="fas fa-spinner fa-spin btn-icon"></i>';
        downloadBtn.disabled = true;
        downloadBtn.style.opacity = '0.7';
    } else {
        downloadBtn.innerHTML = '<span class="btn-text">Download</span> <i class="fas fa-arrow-down btn-icon"></i>';
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

// Display download results
function showResults(data, platform) {
    resultsSection.style.display = 'block';
    setTimeout(function() {
        resultsSection.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }, 100);

    var platformInfo = PLATFORMS[platform];
    resultsTitle.innerHTML = '<i class="' + platformInfo.icon + '" style="color:' + platformInfo.color + '"></i> Download Links';

    var html = '';
    if (data.title) {
        html += '<div class="result-title">' + escapeHtml(data.title) + '</div>';
    }
    html += '<div class="result-links">';
    data.links.forEach(function(link, index) {
        var formatIcon = link.format === 'mp3' ? 'fas fa-music' : (link.format === 'jpg' || link.format === 'png' || link.format === 'webp' ? 'fas fa-image' : 'fas fa-video');
        var formatLabel = link.format ? link.format.toUpperCase() : 'MP4';
        var qualityLabel = link.quality || ('Quality ' + (index + 1));
        var sizeLabel = link.size ? ' (' + link.size + ')' : '';

        html += '<a href="' + escapeHtml(link.url) + '" class="result-link" target="_blank" rel="noopener noreferrer" download>';
        html += '  <div class="result-link-info">';
        html += '    <i class="' + formatIcon + '"></i>';
        html += '    <span class="result-quality">' + escapeHtml(qualityLabel) + escapeHtml(sizeLabel) + '</span>';
        html += '    <span class="result-format">' + formatLabel + '</span>';
        html += '  </div>';
        html += '  <div class="result-link-action">';
        html += '    <i class="fas fa-download"></i> Download';
        html += '  </div>';
        html += '</a>';
    });
    html += '</div>';
    resultsContainer.innerHTML = html;
}

// Hide results
function hideResults() {
    resultsSection.style.display = 'none';
    resultsContainer.innerHTML = '';
}

// Show error in results
function showError(message) {
    resultsSection.style.display = 'block';
    resultsTitle.innerHTML = '<i class="fas fa-exclamation-triangle" style="color: #ff4444"></i> Error';
    resultsContainer.innerHTML = '<div class="result-error">' + escapeHtml(message) + '</div>';
    setTimeout(function() {
        resultsSection.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }, 100);
}

// Handle download - calls our serverless API
async function handleDownload() {
    var url = urlInput.value.trim();
    
    if (!url) {
        showToast('Please paste a video link first', 'fas fa-exclamation-triangle');
        urlInput.focus();
        return;
    }
    
    var platform = detectPlatform(url);
    
    if (!platform) {
        showToast('Unsupported platform. Try Facebook, TikTok, YouTube, Instagram, Pinterest, or X', 'fas fa-exclamation-circle');
        return;
    }

    if (isDownloading) return;
    
    setLoading(true);
    hideResults();
    showToast('Extracting download links from ' + PLATFORMS[platform].name + '...', PLATFORMS[platform].icon);

    try {
        var response = await fetch('/api/download', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: url })
        });

        var data = await response.json();

        if (data.success && data.links && data.links.length > 0) {
            showResults(data, platform);
            showToast('Download links ready!', 'fas fa-check');
        } else {
            showError(data.error || 'Could not extract download links. Please try again.');
            showToast('Failed to extract links', 'fas fa-exclamation-circle');
        }
    } catch (err) {
        showError('Network error. Please check your connection and try again.');
        showToast('Connection error', 'fas fa-wifi');
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
            showToast('Link pasted!', 'fas fa-check');
        }
    } catch (err) {
        // Fallback: focus input for manual paste
        urlInput.focus();
        showToast('Press Ctrl+V to paste', 'fas fa-keyboard');
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
            var fbAppUrl = 'fb://profile/nadir.infograph23';
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

// Initialize
document.addEventListener('DOMContentLoaded', function() {
    createParticles();
    setupDeveloperLink();
    urlInput.focus();
});
