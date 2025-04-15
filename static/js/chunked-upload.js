/**
 * Chunked Upload Implementation for Blueprint Parser
 * 
 * This script handles large text input by:
 * 1. Splitting it into chunks
 * 2. Uploading chunks sequentially
 * 3. Tracking progress
 * 4. Polling for task status after completion
 */

document.addEventListener('DOMContentLoaded', function() {
    // --- DOM References ---
    const form = document.getElementById('blueprint-form');
    const parseButton = document.getElementById('parse-button');
    const blueprintText = document.getElementById('blueprintText');
    const processingIndicator = document.getElementById('processing-indicator');
    const processingMessage = document.getElementById('processing-message');
    const resultsArea = document.getElementById('results-area');
    const errorDisplay = document.getElementById('error-display');
    const humanContentDiv = document.getElementById('human-readable-content');
    const aiContentCode = document.getElementById('ai-readable-content');
    const aiCodeContainer = document.getElementById('ai-code-container');
    const aiPlaceholder = document.getElementById('ai-placeholder');
    const statsSummaryDiv = document.getElementById('stats-summary-content');
    const copyTextBtn = document.getElementById('copy-text-btn');
    const copyJsonBtn = document.getElementById('copy-json-btn');
    const initialPlaceholders = document.querySelectorAll('.initial-placeholder');

    // --- State ---
    let pollIntervalId = null;
    let currentUploadId = null; // Track current upload

    // --- Inline Helpers ---
    function displayErrorInline(message, isWarning = false) {
        console.warn("Displaying Error/Warning:", message);
        if (errorDisplay) {
            errorDisplay.textContent = message;
            errorDisplay.className = isWarning ? 'alert alert-warning' : 'alert alert-danger';
            errorDisplay.style.display = 'block';
        }
        if (processingIndicator) processingIndicator.style.display = 'none';
        if (resultsArea) resultsArea.style.display = 'none';
        if (initialPlaceholders) initialPlaceholders.forEach(p => p.style.display = 'none');
        if (parseButton) parseButton.disabled = false; // Re-enable button on error
        if (pollIntervalId) { clearInterval(pollIntervalId); pollIntervalId = null; } // Stop polling on error
    }

    function displayResultsInline(taskResult) {
        console.log("Displaying Results:", taskResult);
        // Debug output to help investigate HTML rendering issues
        if (taskResult && taskResult.output) {
            console.log("Raw HTML content:", JSON.stringify(taskResult.output).slice(0, 500));
        }
        
        if (errorDisplay) errorDisplay.style.display = 'none';
        if (processingIndicator) processingIndicator.style.display = 'none';
        if (resultsArea) resultsArea.style.display = 'block';
        if (initialPlaceholders) initialPlaceholders.forEach(p => p.style.display = 'none');

        if (taskResult && taskResult.error) {
            displayErrorInline(`Processing completed with issues: ${taskResult.error}`, true);
        }

        // Display stats summary (Received as HTML)
        if (taskResult && taskResult.stats_summary && statsSummaryDiv) {
            statsSummaryDiv.innerHTML = taskResult.stats_summary;
            statsSummaryDiv.style.display = 'block';
            if (typeof fixTables === 'function') setTimeout(fixTables, 50);
        } else if (statsSummaryDiv) { 
            statsSummaryDiv.style.display = 'none'; 
        }

        // Display human-readable output (Received as HTML)
        if (taskResult && taskResult.output && humanContentDiv) {
            humanContentDiv.innerHTML = taskResult.output;
            console.log("AFTER setting humanContentDiv.innerHTML");
            if (copyTextBtn) copyTextBtn.style.display = 'inline-block';
            
            // Call fixups AFTER injecting HTML
            if (typeof fixBlueprintHighlighting === 'function') {
                console.log("Attempting to fix Blueprint highlighting...");
                setTimeout(fixBlueprintHighlighting, 50);
            }
            if (typeof fixTables === 'function') setTimeout(fixTables, 50);
            if (typeof fixEventRendering === 'function') setTimeout(fixEventRendering, 50);
            
            // Optional: Re-highlight non-blueprint code blocks
            if (typeof hljs !== 'undefined') {
                console.log("Applying highlight.js to non-blueprint code blocks...");
                document.querySelectorAll('.markdown-body pre:not(.blueprint) code').forEach(block => {
                    if(!block.hasAttribute('data-highlighted')) {
                        try {
                            hljs.highlightElement(block);
                            block.setAttribute('data-highlighted', 'true');
                        } catch(e) {
                            console.error("Error highlighting generic code block:", e);
                        }
                    }
                });
            }
        } else if (humanContentDiv) {
            humanContentDiv.innerHTML = '<p class="text-muted">No human-readable output generated.</p>';
            if (copyTextBtn) copyTextBtn.style.display = 'none';
        }

        // Display AI output (JSON)
        if (taskResult && taskResult.ai_output && aiContentCode && aiCodeContainer && aiPlaceholder) {
            console.log("Displaying AI output.");
            aiContentCode.textContent = taskResult.ai_output; // Use textContent for safety before highlighting
            aiCodeContainer.style.display = 'block';
            aiPlaceholder.style.display = 'none';
            if (copyJsonBtn) copyJsonBtn.style.display = 'inline-block';
            
            // Re-highlight JSON block
            if (typeof hljs !== 'undefined' && hljs.highlightElement) {
                console.log("Applying highlight.js to JSON...");
                try {
                    // Ensure data-highlighted is removed before re-highlighting
                    aiContentCode.removeAttribute('data-highlighted'); // Clean slate
                    hljs.highlightElement(aiContentCode);
                    aiContentCode.setAttribute('data-highlighted', 'true'); // Mark as highlighted
                } catch (e) {
                    console.error("Highlight.js error on JSON:", e);
                }
            }
        } else if (aiCodeContainer && aiPlaceholder) {
            console.log("No AI output generated.");
            aiCodeContainer.style.display = 'none';
            aiPlaceholder.textContent = 'No AI-readable output generated.';
            aiPlaceholder.style.display = 'block';
            if (copyJsonBtn) copyJsonBtn.style.display = 'none';
        }
    }

    // --- Polling Function ---
    function pollTaskStatus(taskId) {
        console.log(`Starting polling for task: ${taskId}`);
        if (pollIntervalId) clearInterval(pollIntervalId);

        pollIntervalId = setInterval(() => {
            console.log(`Polling status for task: ${taskId}`);
            fetch(`/status/${taskId}`)
                .then(response => {
                    if (!response.ok) {
                        return response.text().then(text => { 
                            throw new Error(`HTTP error! Status: ${response.status}, Message: ${text || 'No message'}`); 
                        });
                    }
                    return response.json();
                })
                .then(data => {
                    console.log("Poll status response:", data);
                    if (['SUCCESS', 'FAILURE', 'PARTIAL_FAILURE', 'UNEXPECTED_RESULT'].includes(data.status)) {
                        clearInterval(pollIntervalId); 
                        pollIntervalId = null;
                        console.log(`Polling stopped for task ${taskId}, status: ${data.status}`);
                        if (processingIndicator) processingIndicator.style.display = 'none';
                        if (parseButton) parseButton.disabled = false; // Re-enable button

                        if (data.status === 'SUCCESS' || data.status === 'PARTIAL_FAILURE') {
                            displayResultsInline(data.result || {});
                        } else {
                            displayErrorInline(data.error || `Task failed with status: ${data.status}`);
                        }
                    } else if (['PROCESSING', 'PENDING', 'STARTED'].includes(data.status)) {
                        // Keep indicator visible, button disabled
                        if (processingIndicator) processingIndicator.style.display = 'flex';
                    } else {
                        // Unknown status
                        clearInterval(pollIntervalId); 
                        pollIntervalId = null;
                        if (parseButton) parseButton.disabled = false;
                        displayErrorInline(`Task ended with unexpected status: ${data.status}`);
                    }
                })
                .catch(error => {
                    console.error('Polling error:', error);
                    clearInterval(pollIntervalId); 
                    pollIntervalId = null;
                    if (parseButton) parseButton.disabled = false;
                    displayErrorInline(`Error checking task status: ${error.message}. The server might be down or the task ID is invalid. Please try again or refresh the page.`);
                });
        }, 3000); // Poll every 3 seconds
    }

    // --- Chunked Upload Logic ---
    function startChunkedUpload(csrfToken, textContent) {
        // Generate a UUID for this upload session
        const uploadId = typeof uuid !== 'undefined' && uuid.v4 ? 
            `upload-${uuid.v4()}` : // Use UUID library if available
            `upload-${Date.now()}-${Math.random().toString(36).substring(2, 15)}`; // Fallback
        
        currentUploadId = uploadId;
        
        // Convert text to blob for chunking
        const blob = new Blob([textContent], { type: 'text/plain' });
        const chunkSize = 5 * 1024 * 1024; // 5MB chunks
        const totalSize = blob.size;
        
        console.log(`Starting chunked upload: ID=${uploadId}, Size=${totalSize}, ChunkSize=${chunkSize}`);

        // Update UI
        if (processingIndicator) processingIndicator.style.display = 'flex';
        if (processingMessage) processingMessage.textContent = 'Initiating upload...';
        if (parseButton) parseButton.disabled = true;
        if (errorDisplay) errorDisplay.style.display = 'none';
        if (resultsArea) resultsArea.style.display = 'none';

        // 1. Initiate Upload - get reserved task_id
        fetch('/initiate-upload', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken
            },
            body: JSON.stringify({
                upload_id: uploadId,
                total_size: totalSize,
                filename: 'pasted_blueprint.txt'
            })
        })
        .then(response => {
            if (!response.ok) {
                return response.json()
                    .then(err => { throw new Error(err.message || `Initiate failed: ${response.status}`); })
                    .catch(() => { throw new Error(`Initiate failed: ${response.status}`); });
            }
            return response.json();
        })
        .then(initData => {
            if (initData.status !== 'success' || !initData.task_id) {
                throw new Error(initData.message || 'Failed to get task ID from initiation.');
            }
            
            const taskId = initData.task_id;
            console.log(`Upload initiated. Server Upload ID: ${initData.upload_id}, Reserved Task ID: ${taskId}`);
            
            // 2. Start Uploading Chunks
            let currentChunkIndex = 0;
            const totalChunks = Math.ceil(totalSize / chunkSize);
            
            function uploadNextChunk() {
                // Check if this upload was superseded
                if (currentUploadId !== uploadId) {
                    console.log(`Upload ${uploadId} cancelled by newer submission.`);
                    if (parseButton) parseButton.disabled = false;
                    return;
                }

                if (currentChunkIndex >= totalChunks) {
                    console.log(`All ${totalChunks} chunks uploaded for ${uploadId}. Starting poll for task ${taskId}.`);
                    if (processingMessage) processingMessage.textContent = 'Upload complete. Processing...';
                    pollTaskStatus(taskId);
                    return;
                }

                const start = currentChunkIndex * chunkSize;
                const end = Math.min(start + chunkSize, totalSize);
                const chunk = blob.slice(start, end);
                
                const formData = new FormData();
                formData.append('chunk', chunk, `chunk_${currentChunkIndex}.txt`);
                formData.append('upload_id', uploadId);
                formData.append('chunk_index', currentChunkIndex);
                
                const percentComplete = Math.round(((currentChunkIndex + 1) / totalChunks) * 100);
                if (processingMessage) processingMessage.textContent = `Uploading... ${percentComplete}%`;
                
                fetch('/upload-chunk', {
                    method: 'POST',
                    headers: {
                        'X-CSRFToken': csrfToken
                    },
                    body: formData
                })
                .then(response => {
                    if (!response.ok) {
                        return response.json()
                            .then(errData => { throw new Error(errData.message || `Chunk upload failed: ${response.status}`); })
                            .catch(() => { throw new Error(`Chunk upload failed: ${response.status}`); });
                    }
                    return response.json();
                })
                .then(chunkData => {
                    if (chunkData.status === 'success') {
                        currentChunkIndex++;
                        uploadNextChunk();
                    } else {
                        throw new Error(chunkData.message || 'Chunk upload reported failure.');
                    }
                })
                .catch(error => {
                    console.error(`Error uploading chunk ${currentChunkIndex} for ${uploadId}:`, error);
                    displayErrorInline(`Upload failed on chunk ${currentChunkIndex + 1}: ${error.message}`);
                });
            }
            
            // Start uploading chunks
            uploadNextChunk();
        })
        .catch(error => {
            console.error('Initiation error:', error);
            displayErrorInline(`Upload initiation failed: ${error.message}`);
            if(parseButton) parseButton.disabled = false;
            if(processingIndicator) processingIndicator.style.display = 'none';
        });
    }

    // --- Form Submission Handler ---
    if (form) {
        form.addEventListener('submit', function(event) {
            console.log("Form submit event listener triggered!");
            event.preventDefault();
            
            const csrfTokenInput = document.getElementById('csrf_token');
            const textContent = blueprintText ? blueprintText.value : '';
            const csrfToken = csrfTokenInput ? csrfTokenInput.value : null;

            // --- UI Reset ---
            if (errorDisplay) errorDisplay.style.display = 'none';
            if (resultsArea) resultsArea.style.display = 'none';
            if (humanContentDiv) humanContentDiv.innerHTML = `<p class="text-muted initial-placeholder">Results will appear here after parsing.</p>`;
            if (statsSummaryDiv) statsSummaryDiv.style.display = 'none'; statsSummaryDiv.innerHTML='';
            if (aiCodeContainer) aiCodeContainer.style.display = 'none';
            if (aiPlaceholder) aiPlaceholder.style.display = 'block'; aiPlaceholder.textContent = 'AI-readable JSON output will appear here after parsing.';
            if (copyTextBtn) copyTextBtn.style.display = 'none';
            if (copyJsonBtn) copyJsonBtn.style.display = 'none';
            if (initialPlaceholders) initialPlaceholders.forEach(p => p.style.display = 'block');
            if (processingMessage) processingMessage.textContent = 'Preparing upload...';
            if (processingIndicator) processingIndicator.style.display = 'flex';
            if (parseButton) parseButton.disabled = true;
            if (pollIntervalId) { clearInterval(pollIntervalId); pollIntervalId = null; }

            // --- Input Validation ---
            if (!textContent || textContent.trim() === '') {
                displayErrorInline("Please paste some Blueprint text."); 
                return;
            }
            if (!csrfToken) {
                displayErrorInline("Client error: CSRF token missing. Please refresh."); 
                return;
            }

            // --- Start Chunked Upload ---
            startChunkedUpload(csrfToken, textContent);
        });
    } else { 
        console.error("Blueprint form not found!"); 
    }

    // Setup copy buttons (they are hidden initially, shown when results appear)
    if (typeof setupCopyButton === 'function') {
        setupCopyButton('copy-text-btn', '#human-readable-content');
        setupCopyButton('copy-json-btn', '#ai-readable-content');
    } else { 
        console.warn("setupCopyButton function not found (needed from scripts.js)"); 
    }
});