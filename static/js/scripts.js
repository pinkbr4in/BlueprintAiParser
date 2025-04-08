// static/js/scripts.js

document.addEventListener('DOMContentLoaded', function() {
    console.log('Blueprint parser custom scripts loaded.');
    
    // Enhanced textarea styling
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
    
    // Fix any HTML rendering issues in event headers
    fixEventRendering();
    
    // Fix table display
    fixTables();
    
    // Initialize highlight.js for non-blueprint blocks
    // Ensure this runs *after* our override is set up in index.html
    // but *before* we try to fix blueprint highlighting.
    if (typeof hljs !== 'undefined' && hljs.highlightAll) {
         hljs.highlightAll(); // Run the (potentially overridden) highlightAll
         console.log("highlight.js initialized.");
    } else {
         console.warn("highlight.js not found or highlightAll not available.");
    }
    
    // Fix Blueprint syntax highlighting (needs to run after hljs potentially modifies it)
    setTimeout(fixBlueprintHighlighting, 50); // Short delay after hljs
    
    // Also fix highlighting when switching tabs
    const tabs = document.querySelectorAll('.nav-link');
    tabs.forEach(tab => {
        tab.addEventListener('shown.bs.tab', () => { // Use Bootstrap's event for reliability
            console.log(`Tab shown: ${tab.id}`);
            if (tab.id === 'human-tab') {
                setTimeout(fixBlueprintHighlighting, 50); // Fix BP blocks on human tab
            } else if (tab.id === 'ai-tab' && typeof hljs !== 'undefined' && hljs.highlightElement) {
                // Re-highlight JSON specifically if needed when switching back
                 const aiCodeBlock = document.querySelector('#ai pre code.language-json');
                 if (aiCodeBlock && !aiCodeBlock.hasAttribute('data-highlighted')) {
                      hljs.highlightElement(aiCodeBlock);
                      console.log("Re-highlighted JSON block.");
                 }
            }
            // Always run debug/check functions after tab switch if needed
             debugBlueprintSpans();
             checkCssStyles();
        });
    });
    
    // Debug Blueprint spans
    debugBlueprintSpans();
    
    // Check CSS for span styles
    checkCssStyles();

    // --- ADD COPY BUTTON LOGIC ---

    // Generic copy function
    function setupCopyButton(buttonId, contentSelector, isHtmlContent = false) {
        const copyBtn = document.getElementById(buttonId);
        if (copyBtn) {
            copyBtn.addEventListener('click', () => {
                const contentElement = document.querySelector(contentSelector);
                if (contentElement) {
                    let textToCopy = '';
                    if (isHtmlContent) {
                        textToCopy = contentElement.textContent || "";
                    } else {
                        textToCopy = contentElement.textContent || "";
                    }

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
                            copyBtn.textContent = originalText;
                            copyBtn.disabled = false;
                        }, 2000);
                    }).catch(err => {
                        console.error(`Failed to copy from ${contentSelector}: `, err);
                        let alertMessage = 'Failed to copy. Please try selecting the text manually.';
                        if (err instanceof DOMException && (err.name === 'NotAllowedError' || err.message.includes('not allowed'))) {
                             alertMessage = 'Browser denied clipboard access.\n\nPlease ensure the page is focused and clipboard permissions are granted.\n\nYou might need to click directly on the page before clicking the copy button.';
                        } else if (navigator.clipboard === undefined) {
                             alertMessage = 'Clipboard API not available. This might happen on non-secure (HTTP) connections or older browsers.';
                        }
                        alert(alertMessage);
                    });
                } else {
                    console.error(`Content element not found for selector: ${contentSelector}`);
                    alert('Could not find content to copy.');
                }
            });
             console.log(`Copy button event listener set up for: ${buttonId}`);
        } else {
             console.warn(`Copy button not found: ${buttonId}`);
        }
    }

    // Setup for Human-Readable Text
    setupCopyButton('copy-text-btn', '#human-readable-content', true);

    // Setup for AI-Readable JSON
    setupCopyButton('copy-json-btn', '#ai-code-content', false);

    // --- END COPY BUTTON LOGIC ---
});

/**
 * Fix Blueprint highlighting after it might have been processed by highlight.js
 */
function fixBlueprintHighlighting() {
     console.log("Attempting to fix Blueprint highlighting...");
     document.querySelectorAll('pre.blueprint code').forEach(block => {
        // Check if highlight.js added classes
        const needsRestore = block.classList.contains('hljs');
        const originalContent = block.getAttribute('data-original-content');

        if (needsRestore && originalContent) {
            // Restore original content only if highlight.js likely altered it
             const tempDiv = document.createElement('div');
             tempDiv.innerHTML = originalContent; // Decode entities by setting innerHTML
             const decodedContent = tempDiv.textContent || tempDiv.innerHTML; // Get decoded text or fallback

             if (decodedContent && decodedContent.includes('<span class="bp-')) {
                 block.innerHTML = decodedContent; // Use decoded content
                 block.classList.remove('hljs', 'language-markdown', 'language-javascript');
                 block.removeAttribute('data-highlighted');
                 console.log("Restored original content for blueprint block.");
             } else {
                 console.log("Original content did not contain blueprint spans, skipping restore.");
             }
        } else if (needsRestore) {
             console.warn("Block has hljs class but no original content stored.");
             // Optionally force remove hljs classes anyway if they cause issues
             block.classList.remove('hljs', 'language-markdown', 'language-javascript');
             block.removeAttribute('data-highlighted');
        }

        // Apply our styles regardless of restoration
        block.querySelectorAll('span[class^="bp-"]').forEach(span => {
            span.style.display = 'inline'; // Ensure inline display
            // Apply specific colors based on the Blueprint class
            const classes = span.classList;
            if (classes.contains('bp-keyword')) { span.style.color = '#c792ea'; span.style.fontWeight = 'bold'; }
            else if (classes.contains('bp-event-name')) { span.style.color = '#ffcb6b'; span.style.fontWeight = 'bold'; }
            else if (classes.contains('bp-func-name')) { span.style.color = '#c792ea'; span.style.fontWeight = 'bold'; }
            else if (classes.contains('bp-var')) { span.style.color = '#79d0ff'; }
            else if (classes.contains('bp-param-name')) { span.style.color = '#ff9cac'; span.style.fontStyle = 'italic'; }
            else if (classes.contains('bp-data-type')) { span.style.color = '#89ddff'; }
            else if (classes.contains('bp-literal-number')) { span.style.color = '#f78c6c'; }
            else if (classes.contains('bp-literal-bool')) { span.style.color = '#ff9cac'; }
            else if (classes.contains('bp-literal-string')) { span.style.color = '#c3e88d'; }
            else if (classes.contains('bp-literal-object')) { span.style.color = '#ffcb6b'; }
            else if (classes.contains('bp-flow')) { span.style.color = '#f78c6c'; }
            else if (classes.contains('bp-arrow')) { span.style.color = '#ff9cac'; span.style.fontWeight = 'bold'; }
            else if (classes.contains('bp-branch-True')) { span.style.color = '#26a566'; span.style.fontWeight = 'bold'; }
            else if (classes.contains('bp-branch-False')) { span.style.color = '#ef5350'; span.style.fontWeight = 'bold'; }
            else if (classes.contains('bp-delegate-name')) { span.style.color = '#89ddff'; span.style.fontWeight = 'bold'; }
            else if (classes.contains('bp-operator')) { span.style.color = '#89ddff'; }
            else if (classes.contains('bp-pin-name')) { span.style.color = '#c3e88d'; }
            else if (classes.contains('bp-struct-kw') || classes.contains('bp-struct-val')) { span.style.color = '#80cbc4'; }
            else if (classes.contains('bp-class-name') || classes.contains('bp-component-name') || classes.contains('bp-widget-name')) { span.style.color = '#c3e88d'; span.style.fontWeight = 'bold'; }
            else if (classes.contains('bp-timeline-name') || classes.contains('bp-montage-name') || classes.contains('bp-action-name')) { span.style.color = '#f07178'; span.style.fontWeight = 'bold'; }
            else if (classes.contains('bp-macro-name')) { span.style.color = '#f78c6c'; span.style.fontWeight = 'bold'; }
            else if (classes.contains('bp-section')) { span.style.color = '#c3e88d'; span.style.fontWeight = 'bold'; }
        });
    });
     console.log("Blueprint highlighting fix attempt complete.");
}

/**
 * Fixes event header rendering
 */
function fixEventRendering() {
    // Look for custom event headers in the HTML
    document.querySelectorAll('pre.blueprint code').forEach(block => {
        // Process spans if they aren't rendering correctly
        if (block.innerHTML.includes('&lt;span class="')) {
            block.innerHTML = block.innerHTML
                .replace(/&lt;span class="([^"]+)"&gt;/g, '<span class="$1">')
                .replace(/&lt;\/span&gt;/g, '</span>');
            console.log("Fixed HTML-encoded spans");
        }
        
        // Look for Custom Event patterns and enhance them directly
        const eventPattern = /Custom Event ([A-Za-z0-9_]+) Args:\(([^)]+)\)/g;
        if (eventPattern.test(block.innerHTML)) {
            block.innerHTML = block.innerHTML.replace(
                eventPattern,
                'Custom Event <span class="event-name">$1</span> Args:(<span class="event-args">$2</span>)'
            );
        }
    });
}

/**
 * Fixes table display issues
 */
function fixTables() {
    // Make function call parameter cells scrollable
    document.querySelectorAll('table td:nth-child(3)').forEach(cell => {
        if (cell.textContent.length > 100) {
            // For very long parameter text, add horizontal scrolling
            cell.style.maxWidth = '0';
            cell.style.overflow = 'auto';
            cell.style.whiteSpace = 'nowrap';
            
            // Ensure spans render correctly
            if (cell.innerHTML.includes('&lt;span')) {
                cell.innerHTML = cell.innerHTML
                    .replace(/&lt;span class="([^"]+)"&gt;/g, '<span class="$1">')
                    .replace(/&lt;\/span&gt;/g, '</span>');
            }
        }
    });
    
    // Fix display of inline spans in all table cells
    document.querySelectorAll('table td span').forEach(span => {
        span.style.display = 'inline';
    });
    
    // Color variable names in first column
    document.querySelectorAll('table td:first-child').forEach(cell => {
        if (cell.textContent.trim() && /[A-Za-z]/.test(cell.textContent)) {
            // Simple heuristic - if it starts with a letter, it's probably a name
            if (!cell.innerHTML.includes('<span')) {
                cell.innerHTML = `<span class="bp-var">${cell.innerHTML}</span>`;
                cell.querySelector('.bp-var').style.color = '#79d0ff';
            }
        }
    });
}

/**
 * Debug function to check blueprint spans
 */
function debugBlueprintSpans() {
    console.log("Checking for blueprint spans...");
    const blueprintBlocks = document.querySelectorAll('pre.blueprint');
    let totalSpans = 0;
    
    blueprintBlocks.forEach((block, index) => {
        const spans = block.querySelectorAll('span[class^="bp-"]');
        console.log(`Blueprint block ${index+1}: Found ${spans.length} spans with bp- classes`);
        totalSpans += spans.length;
        
        if (spans.length < 5) {
            console.warn(`WARNING: Block ${index+1} has very few spans found - syntax highlighting may be broken`);
            // Check raw HTML
            console.log(`Block ${index+1} raw HTML:`, block.innerHTML.substring(0, 200) + "...");
        }
        
        // Check specific classes
        const eventNameSpans = block.querySelectorAll('.bp-event-name');
        const funcNameSpans = block.querySelectorAll('.bp-func-name');
        const varSpans = block.querySelectorAll('.bp-var');
        
        console.log(`  Block ${index+1}: Event name spans: ${eventNameSpans.length}, Function name spans: ${funcNameSpans.length}, Variable spans: ${varSpans.length}`);
    });
    
    console.log(`SUMMARY: Found ${totalSpans} total bp-class spans across ${blueprintBlocks.length} code blocks`);
}

/**
 * Check if CSS styles are properly applied
 */
function checkCssStyles() {
    console.log("Checking CSS for span styles:");
    
    // Test each span class style
    const testClasses = [
        'bp-event-name', 'bp-func-name', 'bp-param-name', 'bp-var',
        'bp-delegate-name', 'bp-class-name', 'bp-component-name',
        'bp-widget-name', 'bp-timeline-name', 'bp-montage-name'
    ];
    
    testClasses.forEach(className => {
        // Create a test element
        const testSpan = document.createElement('span');
        testSpan.className = className;
        testSpan.style.visibility = 'hidden';
        testSpan.textContent = 'test';
        document.body.appendChild(testSpan);
        
        // Get computed style
        const style = window.getComputedStyle(testSpan);
        console.log(`${className}: color=${style.color}, display=${style.display}`);
        
        // Clean up
        document.body.removeChild(testSpan);
    });
}

/**
 * Check if a DOM node has a parent with the specified selector
 */
function hasParent(element, selector) {
    let parent = element.parentElement;
    while (parent) {
        if (parent.matches(selector)) {
            return true;
        }
        parent = parent.parentElement;
    }
    return false;
}