// static/js/scripts.js

document.addEventListener('DOMContentLoaded', function() {
    console.log('Blueprint parser custom scripts loaded (scripts.js).'); // Added file marker

    // Enhanced textarea styling (Runs on initial load)
    const blueprintTextArea = document.getElementById('blueprintText');
    if (blueprintTextArea) {
        blueprintTextArea.addEventListener('focus', () => {
            blueprintTextArea.style.borderColor = '#4d78cc';
            blueprintTextArea.style.boxShadow = '0 0 0 2px rgba(77, 120, 204, 0.25)';
        });
        blueprintTextArea.addEventListener('blur', () => {
            blueprintTextArea.style.borderColor = '';
            blueprintTextArea.style.boxShadow = '';
        });
    }

    // Initial fixes/checks that might run on static content if any
    // fixEventRendering(); // Probably better to call after dynamic content is added
    // fixTables(); // Call this after results are potentially displayed

    // Initialize highlight.js (for non-blueprint blocks initially)
    // Note: The override logic should be in index.html before this script runs
    if (typeof hljs !== 'undefined' && hljs.highlightAll) {
         // hljs.highlightAll(); // Let's trigger this manually after content is potentially ready
         console.log("highlight.js loaded (scripts.js). Manual highlightAll recommended after content load.");
    } else {
         console.warn("highlight.js not found or highlightAll not available.");
    }

    // Initial call for BP highlighting fix (might be needed if content exists on load)
    // setTimeout(fixBlueprintHighlighting, 50); // Call this after dynamic content

    // Tab switching logic (Keep this)
    const tabs = document.querySelectorAll('.nav-link');
    tabs.forEach(tab => {
        tab.addEventListener('shown.bs.tab', () => { // Use Bootstrap's event
            console.log(`Tab shown: ${tab.id}`);
            if (tab.id === 'human-tab') {
                // Fix BP highlighting when human tab becomes visible
                setTimeout(fixBlueprintHighlighting, 50);
            } else if (tab.id === 'ai-tab' && typeof hljs !== 'undefined' && hljs.highlightElement) {
                // Re-highlight JSON if needed when AI tab becomes visible
                 const aiCodeBlock = document.querySelector('#ai-readable-content'); // Corrected selector
                 if (aiCodeBlock && aiCodeBlock.textContent.trim() && !aiCodeBlock.hasAttribute('data-highlighted')) { // Check if content exists
                      try {
                           hljs.highlightElement(aiCodeBlock);
                           console.log("Re-highlighted JSON block on tab switch.");
                           aiCodeBlock.setAttribute('data-highlighted', 'true'); // Mark as highlighted
                      } catch(e) { console.error("Highlight.js error on tab switch:", e); }
                 }
            }
            // Optional: Run debug checks on tab switch
            // debugBlueprintSpans();
            // checkCssStyles();
        });
    });

    // Initial Debug & CSS Checks (Keep these)
    debugBlueprintSpans();
    checkCssStyles();

    // Initial Setup for Copy Buttons (Keep this)
    // They will attach listeners but buttons might be hidden initially
    setupCopyButton('copy-text-btn', '#human-readable-content'); // Target the content div
    setupCopyButton('copy-json-btn', '#ai-readable-content'); // Target the code element

    // --- END Initial DOMContentLoaded ---
});


// --- Keep ALL Helper Functions from your original script ---

/**
 * Fix Blueprint highlighting after it might have been processed by highlight.js
 */
function fixBlueprintHighlighting() {
     console.log("Attempting to fix Blueprint highlighting (fixBlueprintHighlighting)...");
     document.querySelectorAll('pre.blueprint code').forEach(block => {
        // Check if highlight.js added classes (less likely now with override)
        const needsCheck = block.classList.contains('hljs');
        const originalContent = block.getAttribute('data-original-content'); // Check if we stored original

        if (needsCheck && originalContent) {
             // Restore original content if hljs likely altered it
             // (Your existing restoration logic here) ...
             console.log("Restoring original content for blueprint block (if applicable).");
             block.innerHTML = originalContent;
             block.classList.remove('hljs'); // etc.
             block.removeAttribute('data-highlighted');
        } else if (needsCheck) {
             console.warn("Block has hljs class but no original content stored.");
             block.classList.remove('hljs'); // etc.
             block.removeAttribute('data-highlighted');
        }

        // Ensure our spans are styled correctly (using inline styles as fallback/override)
        block.querySelectorAll('span[class^="bp-"]').forEach(span => {
            span.style.display = 'inline'; // Crucial
            // (Your existing logic to apply colors/styles based on bp- class) ...
            const classes = span.classList;
            if (classes.contains('bp-keyword')) { span.style.color = '#c792ea'; span.style.fontWeight = 'bold'; }
            // ... other classes ...
            else if (classes.contains('bp-section')) { span.style.color = '#c3e88d'; span.style.fontWeight = 'bold'; }
        });
    });
     console.log("Blueprint highlighting fix attempt complete.");
}

/**
 * Fixes event header rendering (if necessary)
 */
function fixEventRendering() {
    console.log("Running fixEventRendering...");
    document.querySelectorAll('pre.blueprint code, .markdown-body h3').forEach(block => { // Check headers too
        // Fix encoded spans if they appear
        if (block.innerHTML.includes('<span class="')) {
            block.innerHTML = block.innerHTML
                .replace(/<span class="([^"]+)">/g, '<span class="$1">')
                .replace(/<\/span>/g, '</span>');
            console.log("Fixed HTML-encoded spans in block/header.");
        }
        // Apply specific styles if needed (redundant if CSS is working)
        // Example: block.querySelectorAll('.event-name').forEach(el => el.style.color = '#ffcb6b');
    });
}


/**
 * Fixes table display issues (if applicable)
 */
function fixTables() {
     console.log("Running fixTables...");
     // Your existing table fixing logic (scrolling, span display, coloring)
     document.querySelectorAll('table.blueprint-table td:nth-child(3)').forEach(cell => { // Be specific with selector
         // ... scroll logic ...
     });
     document.querySelectorAll('table.blueprint-table td span').forEach(span => { // Be specific
         span.style.display = 'inline';
     });
     // ... cell coloring logic ...
}

/**
 * Debug function to check blueprint spans
 */
function debugBlueprintSpans() {
    // Your existing debug logic
    console.log("Running debugBlueprintSpans...");
    // ...
}

/**
 * Check if CSS styles are properly applied
 */
function checkCssStyles() {
    // Your existing CSS check logic
    console.log("Running checkCssStyles...");
    // ...
}


/**
 * Generic copy function (Keep your version)
 */
function setupCopyButton(buttonId, contentSelector) { // Removed isHtmlContent - textContent works for both
    const copyBtn = document.getElementById(buttonId);
    // Use querySelector for flexibility
    const contentElement = document.querySelector(contentSelector);

    if (copyBtn && contentElement) {
        // Check if listener already exists (simple check)
        if (copyBtn.dataset.listenerAttached === 'true') {
             console.log(`Copy button listener already attached for: ${buttonId}`);
             return;
        }
        copyBtn.addEventListener('click', () => {
            // Get text content, works for <pre><code> and <div>
            const textToCopy = contentElement.textContent || "";

            if (!textToCopy.trim()) {
                console.warn(`No text content found in ${contentSelector} to copy.`);
                alert('Nothing to copy!');
                return;
            }

            navigator.clipboard.writeText(textToCopy).then(() => {
                const originalText = copyBtn.textContent;
                copyBtn.textContent = 'Copied!';
                copyBtn.disabled = true;
                console.log(`Copied content from ${contentSelector}`);
                setTimeout(() => {
                    // Check if button still exists before resetting
                    if (document.getElementById(buttonId)) {
                         copyBtn.textContent = originalText;
                         copyBtn.disabled = false;
                    }
                }, 2000);
            }).catch(err => {
                console.error(`Failed to copy from ${contentSelector}: `, err);
                // (Your existing detailed error alert logic) ...
                let alertMessage = 'Failed to copy. Please try selecting the text manually.';
                 if (navigator.clipboard === undefined) {
                     alertMessage = 'Clipboard API not available (requires HTTPS or localhost).';
                 }
                 alert(alertMessage);
            });
        });
        copyBtn.dataset.listenerAttached = 'true'; // Mark as attached
        console.log(`Copy button event listener set up for: ${buttonId}`);
    } else {
         // Delay warning slightly in case elements render later
         setTimeout(() => {
              if (!document.getElementById(buttonId)) console.warn(`Copy button not found: ${buttonId}`);
              if (!document.querySelector(contentSelector)) console.warn(`Content element not found: ${contentSelector}`);
         }, 500);
     }
}

/**
 * Check if a DOM node has a parent with the specified selector
 */
function hasParent(element, selector) {
    // Your existing hasParent logic
    // ...
    return false; // Placeholder
}

// Note: Removed specific calls like setupCopyButton from the main DOMContentLoaded here.
// They will be called from index.html or triggered appropriately.