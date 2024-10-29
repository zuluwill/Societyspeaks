let croppers = {};

async function handleImageUpload(input, previewId) {
    const file = input.files[0];
    if (!file) return;

    // Validate file type
    const validTypes = ['image/jpeg', 'image/png', 'image/jpg'];
    if (!validTypes.includes(file.type)) {
        alert('Please upload a valid image file (JPG, JPEG, or PNG)');
        input.value = '';
        return;
    }

    // Validate file size (max 5MB)
    if (file.size > 5 * 1024 * 1024) {
        alert('File size should not exceed 5MB');
        input.value = '';
        return;
    }

    // Show progress bar
    const progressBar = document.getElementById(`progress-${previewId}`);
    const progressBarFill = document.getElementById(`progress-bar-${previewId}`);
    const progressText = document.getElementById(`progress-text-${previewId}`);

    if (progressBar) {
        progressBar.classList.remove('hidden');
    }

    try {
        // Compress image
        const compressedFile = await compressImage(file, {
            maxWidth: previewId.includes('banner') ? 1200 : 400,
            maxHeight: previewId.includes('banner') ? 400 : 400,
            quality: 0.8,
            onProgress: (percent) => {
                if (progressBarFill && progressText) {
                    progressBarFill.style.width = `${percent}%`;
                    progressText.textContent = `${Math.round(percent)}%`;
                }
            }
        });

        // Update preview
        const preview = document.getElementById(previewId);
        if (preview) {
            const reader = new FileReader();
            reader.onload = function(e) {
                preview.src = e.target.result;
                // Show crop button
                const cropButton = document.getElementById(`crop-${previewId}`);
                if (cropButton) {
                    cropButton.classList.remove('hidden');
                }
            }
            reader.readAsDataURL(compressedFile);

            // Create new File object from Blob
            const newFile = new File([compressedFile], file.name, {
                type: compressedFile.type,
                lastModified: new Date().getTime()
            });

            // Update file input
            if ('DataTransfer' in window) {
                const dataTransfer = new DataTransfer();
                dataTransfer.items.add(newFile);
                input.files = dataTransfer.files;
            }
        }

        // Hide progress bar after a delay
        if (progressBar) {
            setTimeout(() => {
                progressBar.classList.add('hidden');
                if (progressBarFill) {
                    progressBarFill.style.width = '0%';
                }
            }, 500);
        }

    } catch (error) {
        console.error('Error processing image:', error);
        alert('Error processing image. Please try again.');
        if (progressBar) {
            progressBar.classList.add('hidden');
        }
        input.value = '';
    }
}

function compressImage(file, options) {
    return new Promise((resolve, reject) => {
        new Compressor(file, {
            maxWidth: options.maxWidth,
            maxHeight: options.maxHeight,
            quality: options.quality,
            success(result) {
                resolve(result);
            },
            error(err) {
                reject(err);
            },
            progress(percent) {
                if (options.onProgress) {
                    options.onProgress(percent);
                }
            }
        });
    });
}

function openCropModal(previewId) {
    const modal = document.getElementById(`crop-modal-${previewId}`);
    const originalImage = document.getElementById(previewId);
    const cropPreview = document.getElementById(`crop-preview-${previewId}`);

    if (modal && originalImage && cropPreview) {
        modal.classList.remove('hidden');
        cropPreview.src = originalImage.src;

        // Initialize cropper with different options based on image type
        const options = {
            aspectRatio: previewId.includes('profile') || previewId.includes('logo') ? 1 : 3,
            viewMode: 2,
            autoCropArea: 1,
            responsive: true,
            restore: false,
            guides: true,
            center: true,
            highlight: false,
            cropBoxMovable: true,
            cropBoxResizable: true,
            toggleDragModeOnDblclick: false,
        };

        // Destroy existing cropper if any
        if (croppers[previewId]) {
            croppers[previewId].destroy();
        }

        // Initialize new cropper with slight delay to ensure modal is visible
        setTimeout(() => {
            croppers[previewId] = new Cropper(cropPreview, options);
        }, 100);
    }
}

function closeCropModal(previewId) {
    const modal = document.getElementById(`crop-modal-${previewId}`);
    modal.classList.add('hidden');

    if (croppers[previewId]) {
        croppers[previewId].destroy();
        delete croppers[previewId];
    }
}

async function applyCrop(previewId) {
    if (!croppers[previewId]) return;

    const cropper = croppers[previewId];
    const canvas = cropper.getCroppedCanvas({
        width: previewId.includes('banner') ? 1200 : 400,
        height: previewId.includes('banner') ? 400 : 400,
        imageSmoothingQuality: 'high'
    });

    try {
        // Update preview image
        const preview = document.getElementById(previewId);
        if (preview) {
            preview.src = canvas.toDataURL('image/jpeg', 0.9);
        }

        // Convert cropped image to blob
        const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', 0.9));

        // Create File from Blob
        const file = new File([blob], 'cropped-image.jpg', { 
            type: 'image/jpeg',
            lastModified: new Date().getTime()
        });

        // Compress the cropped image
        const compressedFile = await compressImage(file, {
            maxWidth: previewId.includes('banner') ? 1200 : 400,
            maxHeight: previewId.includes('banner') ? 400 : 400,
            quality: 0.8
        });

        // Update file input
        const input = document.getElementById(previewId.replace('-preview', ''));
        if (input && 'DataTransfer' in window) {
            const dataTransfer = new DataTransfer();
            dataTransfer.items.add(new File([compressedFile], file.name, {
                type: compressedFile.type,
                lastModified: new Date().getTime()
            }));
            input.files = dataTransfer.files;
        }

        closeCropModal(previewId);
    } catch (error) {
        console.error('Error processing cropped image:', error);
        alert('Error processing image. Please try again.');
    }
}