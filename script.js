// Script Update: Removing the secondary download button

// Function to handle video downloads
function downloadVideo(quality) {
    // Check the selected quality and proceed with download
    switch (quality) {
        case '720p':
            // Perform download of 720p video
            break;
        case '1080p':
            // Perform download of 1080p video
            break;
        // Additional cases for different qualities
        default:
            console.error('Quality not supported');
            return;
    }
}

// Event listener for download buttons
document.querySelectorAll('.download-button').forEach(button => {
    button.addEventListener('click', (event) => {
        const quality = event.target.dataset.quality;
        downloadVideo(quality);
    });
});

// Note: Secondary button for proxy.txt download has been removed. Only one button per quality is maintained for clarity.