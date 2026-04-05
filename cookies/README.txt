# NADIR DOWNLOADER — Cookie Files
# ─────────────────────────────────────────────────────────────────────────────
# Place Netscape-format cookie files here to enable authenticated downloads
# from platforms that require a logged-in account (Instagram, Twitter/X, etc.)
#
# FILE NAMES (one per platform):
#   instagram.txt
#   tiktok.txt
#   twitter.txt
#   youtube.txt
#   facebook.txt
#   pinterest.txt
#
# HOW TO EXPORT COOKIES:
#   1. Install the browser extension "Get cookies.txt LOCALLY" (Chrome/Firefox)
#   2. Log in to the platform in your browser
#   3. Visit the platform homepage (e.g. instagram.com)
#   4. Click the extension → Export → save as the filename above
#   5. Place the .txt file in this directory
#   6. Restart the server — cookies are picked up automatically on next request
#
# VERIFICATION:
#   Visit /api/status to see which cookie files are currently loaded.
#
# SECURITY NOTE:
#   Cookie files contain your login session.  Do NOT share or commit them.
#   Add   cookies/*.txt   to your .gitignore.
