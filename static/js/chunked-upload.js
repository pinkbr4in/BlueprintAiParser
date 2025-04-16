// static/js/chunked-upload.js
// --- Corrected Closure Scope for uploadNextChunk ---

document.addEventListener('DOMContentLoaded', function() {
    console.log("[DEBUG] DOMContentLoaded: Script starting.");
    // --- DOM References ---
    const form = document.getElementById('blueprint-form');
    const parseButton = document.getElementById('parse-button');
    const blueprintText = document.getElementById('blueprintText');
    const processingIndicator = document.getElementById('processing-indicator');
    const processingMessage = document.getElementById('processing-message');
    const resultsArea = document.getElementById('results-area');
    const errorDisplay = document.getElementById('error-display');
    const humanContentDiv = document.getElementById('human-readable-content');
    const statsSummaryDiv = document.getElementById('stats-summary-content');
    const aiCodeContainer = document.getElementById('ai-code-container');
    const aiPlaceholder = document.getElementById('ai-placeholder');
    const copyTextBtn = document.getElementById('copy-text-btn');
    const copyJsonBtn = document.getElementById('copy-json-btn');
    const initialPlaceholders = document.querySelectorAll('.initial-placeholder');


    // --- State ---
    let pollIntervalId = null;
    let currentUploadId = null; // Tracks the *active* client-side upload attempt (using SERVER-CONFIRMED ID once received)

    // --- Inline Helpers ---
    function displayErrorInline(message, isWarning = false) {
        console.warn("[DEBUG] displayErrorInline called. Message:", message, "IsWarning:", isWarning);
        if (errorDisplay) {
            errorDisplay.textContent = message;
            errorDisplay.className = isWarning ? 'alert alert-warning' : 'alert alert-danger';
            errorDisplay.style.display = 'block';
        }
        if (processingIndicator) processingIndicator.style.display = 'none';
        if (resultsArea) resultsArea.style.display = 'none';
        if (initialPlaceholders) initialPlaceholders.forEach(p => p.style.display = 'none');
        if (parseButton && !pollIntervalId) {
            console.log("[DEBUG] Re-enabling parse button (displayErrorInline).");
            parseButton.disabled = false;
        }
        if (pollIntervalId) {
            console.log("[DEBUG] Clearing poll interval due to error.");
            clearInterval(pollIntervalId);
            pollIntervalId = null;
        }
        console.log(`[DEBUG] Clearing currentUploadId (${currentUploadId}) due to error.`);
        currentUploadId = null;
    }

    function displayResultsInline(taskResult) {
        console.log("[DEBUG] displayResultsInline called. Result Data:", taskResult);
        if (errorDisplay) errorDisplay.style.display = 'none';
        if (processingIndicator) processingIndicator.style.display = 'none';
        if (resultsArea) resultsArea.style.display = 'block';
        if (initialPlaceholders) initialPlaceholders.forEach(p => p.style.display = 'none');

        if (taskResult && taskResult.error) {
            displayErrorInline(`Processing completed with issues: ${taskResult.error}`, true);
        }

        // Display stats summary (Received as HTML)
        if (taskResult && taskResult.stats_summary && statsSummaryDiv) {
            console.log("[DEBUG] Displaying stats summary HTML.");
            statsSummaryDiv.innerHTML = taskResult.stats_summary;
            statsSummaryDiv.style.display = 'block';
        } else if (statsSummaryDiv) {
            console.log("[DEBUG] Hiding stats summary div.");
            statsSummaryDiv.style.display = 'none';
        }

        // Display human-readable output (Received as HTML)
        if (taskResult && taskResult.output && humanContentDiv) {
             console.log("[DEBUG] Displaying human-readable HTML output.");
            humanContentDiv.innerHTML = taskResult.output;
            if (copyTextBtn) copyTextBtn.style.display = 'inline-block';
        } else if (humanContentDiv) {
             console.log("[DEBUG] No human-readable output, displaying placeholder.");
            humanContentDiv.innerHTML = '<p class="text-muted">No human-readable output generated.</p>';
            if (copyTextBtn) copyTextBtn.style.display = 'none';
        }

        // Display AI output (JSON)
        if (taskResult && taskResult.ai_output && aiCodeContainer && aiPlaceholder) {
            console.log("[DEBUG] Displaying AI output (JSON).");
            const aiCodeElement = aiCodeContainer.querySelector('code');
            if (aiCodeElement) {
                 aiCodeElement.textContent = taskResult.ai_output;
                 aiCodeContainer.style.display = 'block';
                 if (aiPlaceholder) aiPlaceholder.style.display = 'none';
                 if (copyJsonBtn) copyJsonBtn.style.display = 'inline-block';

                 if (typeof hljs !== 'undefined' && hljs.highlightElement) {
                     console.log("[DEBUG] Applying highlight.js to JSON...");
                     try {
                         aiCodeElement.removeAttribute('data-highlighted');
                         hljs.highlightElement(aiCodeElement);
                         aiCodeElement.setAttribute('data-highlighted', 'true');
                     } catch (e) { console.error("Highlight.js error on JSON:", e); }
                 }
            } else {
                 console.error("[DEBUG] Could not find code element inside #ai-code-container");
            }
        } else if (aiCodeContainer && aiPlaceholder) {
            console.log("[DEBUG] No AI output, displaying placeholder.");
            aiCodeContainer.style.display = 'none';
            aiPlaceholder.textContent = 'No AI-readable output generated.';
            aiPlaceholder.style.display = 'block';
            if (copyJsonBtn) copyJsonBtn.style.display = 'none';
        }

        if (parseButton) {
             console.log("[DEBUG] Re-enabling parse button (displayResultsInline).");
             parseButton.disabled = false;
        }
        console.log(`[DEBUG] Clearing currentUploadId (${currentUploadId}) on success.`);
        currentUploadId = null;
    }

    // --- Polling Function ---
    function pollTaskStatus(taskId) {
        console.log(`[DEBUG] Starting polling for task: ${taskId}`);
        if (pollIntervalId) {
            console.warn(`[DEBUG] Clearing existing poll interval ${pollIntervalId} before starting new one.`);
            clearInterval(pollIntervalId);
        }

        pollIntervalId = setInterval(() => {
            console.log(`[DEBUG] Polling status check for task: ${taskId}`);
            fetch(`/status/${taskId}`)
                .then(response => {
                    if (!response.ok) {
                        return response.text().then(text => {
                            console.error(`[DEBUG] Polling HTTP error! Status: ${response.status}, Message: ${text || 'No message'}`);
                            throw new Error(`HTTP error! Status: ${response.status}, Message: ${text || 'No message'}`);
                        });
                    }
                    return response.json();
                })
                .then(data => {
                    console.log("[DEBUG] Poll status response received:", data);
                    if (['SUCCESS', 'FAILURE', 'PARTIAL_FAILURE', 'UNEXPECTED_RESULT'].includes(data.status)) {
                        console.log(`[DEBUG] Polling complete for task ${taskId}, final status: ${data.status}. Clearing interval ${pollIntervalId}.`);
                        clearInterval(pollIntervalId);
                        pollIntervalId = null;
                        if (processingIndicator) processingIndicator.style.display = 'none';

                        if (data.status === 'SUCCESS' || data.status === 'PARTIAL_FAILURE') {
                            displayResultsInline(data.result || {});
                        } else {
                            displayErrorInline(data.error || `Task failed with status: ${data.status}`);
                        }
                    } else if (['PROCESSING', 'PENDING', 'STARTED'].includes(data.status)) {
                        console.log(`[DEBUG] Task ${taskId} still processing (Status: ${data.status}). Continuing poll.`);
                        if (processingIndicator) processingIndicator.style.display = 'flex';
                    } else {
                        console.warn(`[DEBUG] Polling stopped for task ${taskId} due to unknown status: ${data.status}. Clearing interval ${pollIntervalId}.`);
                        clearInterval(pollIntervalId);
                        pollIntervalId = null;
                        if (parseButton) {
                             console.log("[DEBUG] Re-enabling parse button (unknown poll status).");
                             parseButton.disabled = false;
                        }
                        displayErrorInline(`Task ended with unexpected status: ${data.status}`);
                    }
                })
                .catch(error => {
                    console.error('[DEBUG] Polling fetch/processing error:', error);
                    clearInterval(pollIntervalId);
                    pollIntervalId = null;
                    if (parseButton) {
                         console.log("[DEBUG] Re-enabling parse button (polling error).");
                         parseButton.disabled = false;
                    }
                    displayErrorInline(`Error checking task status: ${error.message}. The server might be down or the task ID is invalid. Please try again or refresh the page.`);
                });
        }, 3000);
        console.log(`[DEBUG] Poll interval ${pollIntervalId} set for task ${taskId}.`);
    }

    // --- Chunked Upload Logic ---
    function startChunkedUpload(csrfToken, textContent) {
        const uploadIdForThisAttempt = typeof uuid !== 'undefined' && uuid.v4 ?
            `upload-${uuid.v4()}` :
            `upload-${Date.now()}-${Math.random().toString(36).substring(2, 15)}`;

        // Set the global tracker initially to the client-generated ID for this attempt
        currentUploadId = uploadIdForThisAttempt;
        console.log(`[DEBUG] Starting NEW chunked upload attempt. Client-generated ID: ${uploadIdForThisAttempt}`);

        const blob = new Blob([textContent], { type: 'text/plain' });
        const chunkSize = 5 * 1024 * 1024;
        const totalSize = blob.size;

        console.log(`[DEBUG] Upload details: Size=${totalSize}, ChunkSize=${chunkSize}`);

        // Update UI
        if (processingIndicator) processingIndicator.style.display = 'flex';
        if (processingMessage) processingMessage.textContent = 'Initiating upload...';
        if (parseButton) parseButton.disabled = true;
        if (errorDisplay) errorDisplay.style.display = 'none';
        if (resultsArea) resultsArea.style.display = 'none';
        if (pollIntervalId) {
            console.warn(`[DEBUG] Clearing existing poll interval ${pollIntervalId} at start of new upload.`);
            clearInterval(pollIntervalId);
            pollIntervalId = null;
        }

        // 1. Initiate Upload
        const initiatePayload = {
            // Client *can* send an ID, but server generates the definitive one
            // upload_id: uploadIdForThisAttempt, // We don't strictly need to send this anymore
            total_size: totalSize,
            filename: 'pasted_blueprint.txt'
        };
        console.log("[DEBUG] Sending /initiate-upload request with payload:", initiatePayload);
        fetch('/initiate-upload', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken
            },
            body: JSON.stringify(initiatePayload)
        })
        .then(response => {
            console.log(`[DEBUG] Received response for /initiate-upload (Client Attempt ID: ${uploadIdForThisAttempt}). Status: ${response.status}`);
            // Check if the upload attempt associated with this fetch is still the active one
            if (currentUploadId !== uploadIdForThisAttempt) {
                console.warn(`[DEBUG] Upload initiation response received for ${uploadIdForThisAttempt}, but a newer upload (${currentUploadId}) is active. Ignoring.`);
                throw new Error("Upload superseded by a newer request.");
            }
            if (!response.ok) {
                return response.json().then(err => {
                    const errorMsg = err.message || `Initiate failed: ${response.status}`;
                    console.error(`[DEBUG] /initiate-upload failed: ${errorMsg}`);
                    throw new Error(errorMsg);
                }).catch(() => {
                    const errorMsg = `Initiate failed: ${response.status}`;
                     console.error(`[DEBUG] /initiate-upload failed: ${errorMsg} (Could not parse error JSON)`);
                    throw new Error(errorMsg);
                });
            }
            return response.json();
        })
        .then(initData => { // *** Move uploadNextChunk definition INSIDE this .then() ***
            console.log("[DEBUG] /initiate-upload response JSON:", initData);
             // Double-check if still the active upload before proceeding
            if (currentUploadId !== uploadIdForThisAttempt) {
                console.warn(`[DEBUG] Upload initiation data processed for ${uploadIdForThisAttempt}, but a newer upload (${currentUploadId}) is active. Stopping chunk upload.`);
                return;
            }

            if (initData.status !== 'success' || !initData.task_id || !initData.upload_id) {
                 const errorMsg = initData.message || 'Failed to get required data (task_id/upload_id) from initiation.';
                 console.error(`[DEBUG] /initiate-upload reported failure or missing data: ${errorMsg}`);
                throw new Error(errorMsg);
            }

            // *** Use the upload_id confirmed by the server ***
            const confirmedUploadId = initData.upload_id; // This is the ID the server is tracking
            const taskId = initData.task_id;

            // Update the global tracker ONLY if this attempt is still the active one
            if (currentUploadId === uploadIdForThisAttempt) {
                 console.log(`[DEBUG] Updating currentUploadId from ${currentUploadId} to server-confirmed ${confirmedUploadId}`);
                 currentUploadId = confirmedUploadId; // Update global tracker
            } else {
                 console.warn(`[DEBUG] Server confirmed ID ${confirmedUploadId}, but current active ID is ${currentUploadId}. Not updating global tracker.`);
            }

            console.log(`[DEBUG] Upload initiated successfully. Server Confirmed Upload ID: ${confirmedUploadId}, Task ID: ${taskId}`);

            // 2. Start Uploading Chunks
            let currentChunkIndex = 0;
            const totalChunks = Math.ceil(totalSize / chunkSize);
            console.log(`[DEBUG] Starting chunk uploads for ${confirmedUploadId}. Total chunks: ${totalChunks}`);

            // *** DEFINE uploadNextChunk HERE ***
            // It now closes over the correct 'confirmedUploadId' and 'taskId'
            function uploadNextChunk() {
                // Check if THIS upload attempt (using confirmed ID) is still the active one
                if (currentUploadId !== confirmedUploadId) {
                    console.warn(`[DEBUG] Upload ${confirmedUploadId} cancelled by newer submission (${currentUploadId}). Stopping chunk upload.`);
                    return;
                }

                if (currentChunkIndex >= totalChunks) {
                    console.log(`[DEBUG] All ${totalChunks} chunks uploaded for ${confirmedUploadId}. Starting poll for task ${taskId}.`);
                    if (processingMessage) processingMessage.textContent = 'Upload complete. Processing...';
                    pollTaskStatus(taskId);
                    return;
                }

                const start = currentChunkIndex * chunkSize;
                const end = Math.min(start + chunkSize, totalSize);
                const chunk = blob.slice(start, end);
                console.log(`[DEBUG] Preparing chunk ${currentChunkIndex + 1}/${totalChunks} (Bytes: ${start}-${end}) for ${confirmedUploadId}`);

                const formData = new FormData();
                formData.append('chunk', chunk, `chunk_${currentChunkIndex}.txt`);
                formData.append('upload_id', confirmedUploadId); // *** Send the CONFIRMED upload ID ***
                formData.append('chunk_index', currentChunkIndex);

                const percentComplete = Math.round(((currentChunkIndex + 1) / totalChunks) * 100);
                if (processingMessage) processingMessage.textContent = `Uploading... ${percentComplete}%`;

                console.log(`[DEBUG] Sending /upload-chunk request for chunk ${currentChunkIndex + 1}. Upload ID: ${confirmedUploadId}`);

                fetch('/upload-chunk', {
                    method: 'POST',
                    headers: {
                        'X-CSRFToken': csrfToken
                    },
                    body: formData
                })
                .then(response => {
                    console.log(`[DEBUG] Received response for /upload-chunk ${currentChunkIndex + 1} (Upload ID: ${confirmedUploadId}). Status: ${response.status}`);
                     // Check if THIS upload attempt is still active before processing response
                    if (currentUploadId !== confirmedUploadId) {
                        console.warn(`[DEBUG] Chunk response received for ${confirmedUploadId}, but a newer upload (${currentUploadId}) is active. Ignoring.`);
                        throw new Error("Upload superseded by a newer request.");
                    }
                    if (!response.ok) {
                         return response.json().then(errData => {
                             const errorMsg = errData.message || `Chunk upload failed: ${response.status}`;
                             console.error(`[DEBUG] /upload-chunk ${currentChunkIndex + 1} failed: ${errorMsg}`);
                             throw new Error(errorMsg);
                         }).catch(() => {
                             const errorMsg = `Chunk upload failed: ${response.status}`;
                             console.error(`[DEBUG] /upload-chunk ${currentChunkIndex + 1} failed: ${errorMsg} (Could not parse error JSON)`);
                             throw new Error(errorMsg);
                         });
                    }
                    return response.json();
                })
                .then(chunkData => {
                    console.log(`[DEBUG] /upload-chunk ${currentChunkIndex + 1} response JSON:`, chunkData);
                     // Check again if still active
                     if (currentUploadId !== confirmedUploadId) {
                         console.warn(`[DEBUG] Chunk data processed for ${confirmedUploadId}, but a newer upload (${currentUploadId}) is active. Stopping.`);
                         return;
                     }

                    if (chunkData.status === 'success') {
                        currentChunkIndex++;
                        setTimeout(uploadNextChunk, 0);
                    } else {
                         const errorMsg = chunkData.message || 'Chunk upload reported failure.';
                         console.error(`[DEBUG] /upload-chunk ${currentChunkIndex + 1} reported failure: ${errorMsg}`);
                        throw new Error(errorMsg);
                    }
                })
                .catch(error => {
                    if (currentUploadId === confirmedUploadId) {
                         console.error(`[DEBUG] Error during chunk ${currentChunkIndex + 1} upload for ${confirmedUploadId}:`, error);
                         displayErrorInline(`Upload failed on chunk ${currentChunkIndex + 1}: ${error.message}`);
                    } else {
                         console.warn(`[DEBUG] Error caught for superseded upload ${confirmedUploadId}: ${error.message}. Ignoring display.`);
                    }
                });
            } // *** End of uploadNextChunk definition ***

            // Start uploading the first chunk
            uploadNextChunk(); // *** Call the function defined inside .then() ***

        }) // End of .then() for /initiate-upload
        .catch(error => {
            // Only display error if this is still the active upload attempt
            if (currentUploadId === uploadIdForThisAttempt) {
                 console.error('[DEBUG] Initiation or superseded error:', error);
                 displayErrorInline(`Upload initiation failed: ${error.message}`);
            } else {
                  console.warn(`[DEBUG] Error caught for superseded upload ${uploadIdForThisAttempt}: ${error.message}. Ignoring display.`);
            }
        });
    } // End startChunkedUpload

    // --- Form Submission Handler ---
    if (form) {
        form.addEventListener('submit', function(event) {
            console.log("[DEBUG] Form submit event listener triggered!");
            event.preventDefault();

            if (pollIntervalId) {
                 console.log(`[DEBUG] Clearing previous polling interval ${pollIntervalId} on new submission.`);
                 clearInterval(pollIntervalId);
                 pollIntervalId = null;
            }
            console.log(`[DEBUG] Clearing currentUploadId (${currentUploadId}) on new submission.`);
            currentUploadId = null; // Reset active upload tracker

            const csrfTokenInput = document.getElementById('csrf_token');
            const textContent = blueprintText ? blueprintText.value : '';
            const csrfToken = csrfTokenInput ? csrfTokenInput.value : null;

            // --- UI Reset ---
             console.log("[DEBUG] Resetting UI elements for new submission.");
            if (errorDisplay) errorDisplay.style.display = 'none';
            // ... other resets ...
            if (parseButton) parseButton.disabled = true;

            // --- Input Validation ---
            if (!textContent || textContent.trim() === '') {
                 console.warn("[DEBUG] Input validation failed: Empty text.");
                displayErrorInline("Please paste some Blueprint text.");
                return;
            }
            if (!csrfToken) {
                 console.error("[DEBUG] Input validation failed: Missing CSRF token.");
                displayErrorInline("Client error: CSRF token missing. Please refresh.");
                return;
            }
             console.log("[DEBUG] Input validation passed.");

            // --- Start Chunked Upload ---
            startChunkedUpload(csrfToken, textContent);
        });
    } else {
        console.error("[DEBUG] Blueprint form not found!");
    }

    // --- Copy Button Setup ---
    if (typeof setupCopyButton === 'function') {
        console.log("[DEBUG] Setting up copy buttons.");
        setupCopyButton('copy-text-btn', '#human-readable-content');
        setupCopyButton('copy-json-btn', '#ai-readable-content code');
    } else {
        console.warn("[DEBUG] setupCopyButton function not found.");
    }

}); // End DOMContentLoaded