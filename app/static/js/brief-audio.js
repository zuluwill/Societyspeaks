/**
 * Brief Audio Generation Functions
 * 
 * Unified audio generation and management for both DailyBrief and BriefRun.
 * Works with data attributes for flexibility.
 */

(function() {
    'use strict';

    // Poll audio job status
    async function pollAudioJobStatus(jobId, progressBar, progressText, statusMessage, button) {
        const maxAttempts = 300; // 5 minutes max (300 * 1 second)
        let attempts = 0;
        
        const poll = async () => {
            try {
                const response = await fetch(`/api/brief/audio/job/${jobId}/status`);
                const data = await response.json();
                
                const progress = data.progress || 0;
                const status = data.status;
                
                if (progressBar) progressBar.style.width = progress + '%';
                if (progressText) progressText.textContent = progress + '%';
                
                if (status === 'completed') {
                    const failedMsg = data.failed_items > 0 ? ` (${data.failed_items} failed)` : '';
                    if (statusMessage) {
                        statusMessage.textContent = `Completed! Generated audio for ${data.completed_items}/${data.total_items} items${failedMsg}.`;
                    }
                    if (data.failed_items > 0) {
                        if (window.showWarning) {
                            window.showWarning(`Audio generation completed with ${data.failed_items} failed item(s). You can retry failed items.`);
                        }
                    } else {
                        if (window.showSuccess) {
                            window.showSuccess(`Audio generation completed! Generated ${data.completed_items} audio files.`);
                        }
                    }
                    if (button) {
                        button.disabled = false;
                        const span = button.querySelector('span');
                        if (span) span.textContent = 'Generate All Audio';
                    }
                    // Reload page after 2 seconds to show audio players
                    setTimeout(() => window.location.reload(), 2000);
                    return;
                } else if (status === 'failed') {
                    if (statusMessage) {
                        statusMessage.textContent = 'Generation failed: ' + (data.error_message || 'Unknown error');
                    }
                    if (window.showError) {
                        window.showError('Audio generation failed: ' + (data.error_message || 'Unknown error'));
                    }
                    if (button) {
                        button.disabled = false;
                        const span = button.querySelector('span');
                        if (span) span.textContent = 'Retry Generation';
                    }
                    return;
                } else if (status === 'processing') {
                    const processed = (data.completed_items || 0) + (data.failed_items || 0);
                    const failedMsg = data.failed_items > 0 ? ` (${data.failed_items} failed)` : '';
                    if (statusMessage) {
                        statusMessage.textContent = `Generating audio... ${processed}/${data.total_items} items processed${failedMsg}`;
                    }
                } else {
                    if (statusMessage) {
                        statusMessage.textContent = 'Queued... waiting to start (model loading may take 30-60 seconds)';
                    }
                }
                
                attempts++;
                if (attempts < maxAttempts && status !== 'completed' && status !== 'failed') {
                    setTimeout(poll, 1000); // Poll every second
                } else if (attempts >= maxAttempts) {
                    if (statusMessage) {
                        statusMessage.textContent = 'Polling timeout. Please refresh the page to check status.';
                    }
                    if (window.showWarning) {
                        window.showWarning('Polling timeout. Please refresh the page to check status.');
                    }
                    if (button) {
                        button.disabled = false;
                        const span = button.querySelector('span');
                        if (span) span.textContent = 'Generate All Audio';
                    }
                }
            } catch (error) {
                console.error('Error polling audio job status:', error);
                if (window.showError) {
                    window.showError('Error checking audio generation status. Please refresh the page.');
                }
                if (button) {
                    button.disabled = false;
                    const span = button.querySelector('span');
                    if (span) span.textContent = 'Generate All Audio';
                }
            }
        };
        
        poll();
    }

    // Generate audio for DailyBrief
    async function generateAllAudio(briefId) {
        const button = document.getElementById('generate-all-audio-btn');
        const voiceSelect = document.getElementById('voice-select');
        const statusDiv = document.getElementById('audio-generation-status');
        const progressBar = document.getElementById('audio-progress-bar');
        const progressText = document.getElementById('audio-progress-text');
        const statusMessage = document.getElementById('audio-status-message');
        
        if (!button) return;
        
        // Disable button
        button.disabled = true;
        const span = button.querySelector('span');
        if (span) span.textContent = 'Generating...';
        
        // Show status
        if (statusDiv) statusDiv.classList.remove('hidden');
        if (statusMessage) statusMessage.textContent = 'Creating audio generation job...';
        
        try {
            const voiceId = voiceSelect ? voiceSelect.value : 'professional';
            const response = await fetch(`/api/brief/${briefId}/audio/generate`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ voice_id: voiceId })
            });
            
            const data = await response.json();

            // Feature disabled (410 Gone)
            if (response.status === 410 || data.code === 'AUDIO_DISABLED') {
                if (window.showInfo) {
                    window.showInfo(data.error || 'Audio generation is disabled.');
                }
                button.disabled = false;
                if (span) span.textContent = 'Generate All Audio';
                if (statusDiv) statusDiv.classList.add('hidden');
                return;
            }

            if (data.success) {
                if (window.showInfo) {
                    window.showInfo('Audio generation started. This may take 15-20 minutes.');
                }
                // Start polling for status
                pollAudioJobStatus(data.job_id, progressBar, progressText, statusMessage, button);
            } else {
                if (window.showError) {
                    window.showError('Failed to start audio generation: ' + (data.error || 'Unknown error'));
                }
                button.disabled = false;
                if (span) span.textContent = 'Generate All Audio';
                if (statusDiv) statusDiv.classList.add('hidden');
            }
        } catch (error) {
            console.error('Audio generation error:', error);
            if (window.showError) {
                window.showError('Failed to start audio generation. Please try again.');
            }
            button.disabled = false;
            if (span) span.textContent = 'Generate All Audio';
            if (statusDiv) statusDiv.classList.add('hidden');
        }
    }

    // Generate audio for BriefRun
    async function generateAllAudioForRun(briefRunId, briefingId) {
        const button = document.getElementById('generate-all-audio-btn-run');
        const voiceSelect = document.getElementById('voice-select-run');
        const statusDiv = document.getElementById('audio-generation-status-run');
        const progressBar = document.getElementById('audio-progress-bar-run');
        const progressText = document.getElementById('audio-progress-text-run');
        const statusMessage = document.getElementById('audio-status-message-run');
        
        if (!button) return;
        
        // Disable button
        button.disabled = true;
        const span = button.querySelector('span');
        if (span) span.textContent = 'Generating...';
        
        // Show status
        if (statusDiv) statusDiv.classList.remove('hidden');
        if (statusMessage) statusMessage.textContent = 'Creating audio generation job...';
        
        try {
            const voiceId = voiceSelect ? voiceSelect.value : 'professional';
            const response = await fetch(`/briefings/api/${briefingId}/runs/${briefRunId}/audio/generate`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ voice_id: voiceId })
            });
            
            const data = await response.json();

            // Feature disabled (410 Gone)
            if (response.status === 410 || data.code === 'AUDIO_DISABLED') {
                if (window.showInfo) {
                    window.showInfo(data.error || 'Audio generation is disabled.');
                }
                button.disabled = false;
                if (span) span.textContent = 'Generate All Audio';
                if (statusDiv) statusDiv.classList.add('hidden');
                return;
            }

            if (data.success) {
                if (window.showInfo) {
                    window.showInfo('Audio generation started. This may take 15-20 minutes.');
                }
                // Start polling for status
                pollAudioJobStatus(data.job_id, progressBar, progressText, statusMessage, button);
            } else {
                if (window.showError) {
                    window.showError('Failed to start audio generation: ' + (data.error || 'Unknown error'));
                }
                button.disabled = false;
                if (span) span.textContent = 'Generate All Audio';
                if (statusDiv) statusDiv.classList.add('hidden');
            }
        } catch (error) {
            console.error('Audio generation error:', error);
            if (window.showError) {
                window.showError('Failed to start audio generation. Please try again.');
            }
            button.disabled = false;
            if (span) span.textContent = 'Generate All Audio';
            if (statusDiv) statusDiv.classList.add('hidden');
        }
    }

    // Toggle deeper context (works with any ID prefix)
    function toggleDeeperContext(itemId, prefix = '') {
        const contextId = prefix ? `deeper-context-${prefix}-${itemId}` : `deeper-context-${itemId}`;
        const contextDiv = document.getElementById(contextId);
        const button = document.querySelector(`.toggle-deeper-context-btn[data-item-id="${itemId}"]`);
        
        if (!contextDiv || !button) return;
        
        // Find icon - try data-icon-id first, then by ID pattern
        const icon = document.querySelector(`[data-icon-id="${itemId}"]`) || 
                    (prefix ? document.getElementById(`icon-${prefix}-${itemId}`) : null) ||
                    document.getElementById(`icon-${itemId}`);
        
        const isExpanded = !contextDiv.classList.contains('hidden');
        
        if (isExpanded) {
            contextDiv.classList.add('hidden');
            if (icon) icon.style.transform = 'rotate(0deg)';
            const span = button.querySelector('span');
            if (span) span.textContent = 'Want a bit more detail?';
            button.setAttribute('aria-expanded', 'false');
        } else {
            contextDiv.classList.remove('hidden');
            if (icon) icon.style.transform = 'rotate(180deg)';
            const span = button.querySelector('span');
            if (span) span.textContent = 'Show less detail';
            button.setAttribute('aria-expanded', 'true');
        }
    }

    // Copy dive deeper text to clipboard
    function copyDiveDeeperText(itemId, prefix = '') {
        const textareaId = prefix ? `dive-deeper-text-${prefix}-${itemId}` : `dive-deeper-text-${itemId}`;
        const textarea = document.getElementById(textareaId);
        
        if (!textarea) {
            if (window.showError) {
                window.showError('Could not find text to copy.');
            }
            return;
        }
        
        textarea.select();
        textarea.setSelectionRange(0, 99999); // For mobile devices
        
        try {
            document.execCommand('copy');
            if (window.showSuccess) {
                window.showSuccess('Text copied to clipboard!');
            }
        } catch (err) {
            // Fallback to modern Clipboard API
            navigator.clipboard.writeText(textarea.value).then(() => {
                if (window.showSuccess) {
                    window.showSuccess('Text copied to clipboard!');
                }
            }).catch(() => {
                if (window.showError) {
                    window.showError('Failed to copy text. Please select and copy manually.');
                }
            });
        }
    }

    // Initialize event listeners
    function init() {
        // Function to set up event listeners
        function setupListeners() {
            // Audio generation for DailyBrief
            const generateBtn = document.getElementById('generate-all-audio-btn');
            if (generateBtn && !generateBtn.hasAttribute('data-listener-attached')) {
                generateBtn.setAttribute('data-listener-attached', 'true');
                let touchHandled = false;
                
                generateBtn.addEventListener('click', function(e) {
                    if (!touchHandled) {
                        e.preventDefault();
                        e.stopPropagation();
                        const briefId = this.dataset.briefId;
                        generateAllAudio(briefId);
                    }
                });
                // Also handle touch events for mobile
                generateBtn.addEventListener('touchend', function(e) {
                    e.preventDefault();
                    e.stopPropagation();
                    touchHandled = true;
                    const briefId = this.dataset.briefId;
                    generateAllAudio(briefId);
                    setTimeout(() => { touchHandled = false; }, 300);
                }, { passive: false });
            }
            
            // Audio generation for BriefRun
            const generateBtnRun = document.getElementById('generate-all-audio-btn-run');
            if (generateBtnRun && !generateBtnRun.hasAttribute('data-listener-attached')) {
                generateBtnRun.setAttribute('data-listener-attached', 'true');
                let touchHandled = false;
                
                generateBtnRun.addEventListener('click', function(e) {
                    if (!touchHandled) {
                        e.preventDefault();
                        e.stopPropagation();
                        const briefRunId = this.dataset.briefRunId;
                        const briefingId = this.dataset.briefingId;
                        generateAllAudioForRun(briefRunId, briefingId);
                    }
                });
                // Also handle touch events for mobile
                generateBtnRun.addEventListener('touchend', function(e) {
                    e.preventDefault();
                    e.stopPropagation();
                    touchHandled = true;
                    const briefRunId = this.dataset.briefRunId;
                    const briefingId = this.dataset.briefingId;
                    generateAllAudioForRun(briefRunId, briefingId);
                    setTimeout(() => { touchHandled = false; }, 300);
                }, { passive: false });
            }
            
            // Toggle deeper context buttons (works with any prefix)
            document.querySelectorAll('.toggle-deeper-context-btn').forEach(btn => {
                if (!btn.hasAttribute('data-listener-attached')) {
                    btn.setAttribute('data-listener-attached', 'true');
                    let touchHandled = false;
                    
                    btn.addEventListener('click', function(e) {
                        if (!touchHandled) {
                            e.preventDefault();
                            e.stopPropagation();
                            const itemId = this.dataset.itemId;
                            const prefix = this.dataset.prefix || '';
                            toggleDeeperContext(itemId, prefix);
                        }
                    });
                    // Also handle touch events for mobile
                    btn.addEventListener('touchend', function(e) {
                        e.preventDefault();
                        e.stopPropagation();
                        touchHandled = true;
                        const itemId = this.dataset.itemId;
                        const prefix = this.dataset.prefix || '';
                        toggleDeeperContext(itemId, prefix);
                        setTimeout(() => { touchHandled = false; }, 300);
                    }, { passive: false });
                }
            });
            
            // Copy dive deeper text buttons (works with any prefix)
            document.querySelectorAll('.copy-dive-deeper-btn').forEach(btn => {
                if (!btn.hasAttribute('data-listener-attached')) {
                    btn.setAttribute('data-listener-attached', 'true');
                    let touchHandled = false;
                    
                    btn.addEventListener('click', function(e) {
                        if (!touchHandled) {
                            e.preventDefault();
                            e.stopPropagation();
                            const itemId = this.dataset.itemId;
                            const prefix = this.dataset.prefix || '';
                            copyDiveDeeperText(itemId, prefix);
                        }
                    });
                    // Also handle touch events for mobile
                    btn.addEventListener('touchend', function(e) {
                        e.preventDefault();
                        e.stopPropagation();
                        touchHandled = true;
                        const itemId = this.dataset.itemId;
                        const prefix = this.dataset.prefix || '';
                        copyDiveDeeperText(itemId, prefix);
                        setTimeout(() => { touchHandled = false; }, 300);
                    }, { passive: false });
                }
            });
        }
        
        // Check if DOM is already loaded
        if (document.readyState === 'loading') {
            // DOM hasn't finished loading yet, wait for it
            document.addEventListener('DOMContentLoaded', setupListeners);
        } else {
            // DOM is already loaded, run immediately
            setupListeners();
        }
    }

    // Export to global scope
    window.pollAudioJobStatus = pollAudioJobStatus;
    window.generateAllAudio = generateAllAudio;
    window.generateAllAudioForRun = generateAllAudioForRun;
    window.toggleDeeperContext = toggleDeeperContext;
    window.copyDiveDeeperText = copyDiveDeeperText;

    // Auto-initialize
    init();
})();
