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
    
    // Fix Blueprint syntax highlighting (do this AFTER highlight.js processes)
    setTimeout(fixBlueprintHighlighting, 200);
    
    // Also fix highlighting when switching tabs
    const tabs = document.querySelectorAll('.nav-link');
    tabs.forEach(tab => {
        tab.addEventListener('click', () => setTimeout(fixBlueprintHighlighting, 200));
    });
    
    // Debug Blueprint spans
    debugBlueprintSpans();
    
    // Check CSS for span styles
    checkCssStyles();
});

/**
 * Fix Blueprint highlighting after it might have been processed by highlight.js
 */
function fixBlueprintHighlighting() {
    // Process all blueprint code blocks to ensure our classes are respected
    document.querySelectorAll('pre.blueprint code').forEach(block => {
        // Remove any hljs-specific styling
        if (block.classList.contains('hljs')) {
            // First try to restore from original content if available
            const originalContent = block.getAttribute('data-original-content');
            if (originalContent) {
                // Decode HTML entities in the original content
                const tempDiv = document.createElement('div');
                tempDiv.innerHTML = originalContent;
                const decodedContent = tempDiv.textContent || tempDiv.innerHTML;
                
                if (decodedContent && decodedContent.includes('class="bp-')) {
                    // Set the decoded content back
                    block.innerHTML = decodedContent;
                    
                    // Remove highlight.js classes but keep the nohighlight attribute
                    block.classList.remove('hljs', 'language-markdown', 'language-javascript');
                    block.removeAttribute('data-highlighted');
                    console.log("Restored original content for blueprint block");
                }
            }
        }
        
        // Now explicitly apply styling based on class
        block.querySelectorAll('span[class^="bp-"]').forEach(span => {
            // Ensure inline display
            span.style.display = 'inline';
            
            // Apply specific colors based on the Blueprint class
            if (span.classList.contains('bp-keyword')) {
                span.style.color = '#c792ea';
                span.style.fontWeight = 'bold';
            }
            else if (span.classList.contains('bp-event-name')) {
                span.style.color = '#ffcb6b';
                span.style.fontWeight = 'bold';
            }
            else if (span.classList.contains('bp-var')) {
                span.style.color = '#79d0ff';
            }
            else if (span.classList.contains('bp-func-name')) {
                span.style.color = '#c792ea';
                span.style.fontWeight = 'bold';
            }
            else if (span.classList.contains('bp-param-name')) {
                span.style.color = '#ff9cac';
                span.style.fontStyle = 'italic';
            }
            else if (span.classList.contains('bp-data-type')) {
                span.style.color = '#89ddff';
            }
            else if (span.classList.contains('bp-literal-number')) {
                span.style.color = '#f78c6c';
            }
            else if (span.classList.contains('bp-literal-bool')) {
                span.style.color = '#ff9cac';
            }
            else if (span.classList.contains('bp-literal-string')) {
                span.style.color = '#c3e88d';
            }
            // Add more class-specific styling as needed
        });
        
        // Process spans that should be re-created as BP styles
        block.querySelectorAll('span:not([class^="bp-"])').forEach(span => {
            const text = span.textContent;
            
            // Simple heuristics to identify content types
            if (text.startsWith('`') && text.endsWith('`') && text.length > 2) {
                // Likely a variable or entity name
                span.className = 'bp-var';
                span.style.color = '#79d0ff';
            }
            else if (text.startsWith('**') && text.endsWith('**') && text.length > 4) {
                // Likely a keyword
                span.className = 'bp-keyword';
                span.style.color = '#c792ea';
                span.style.fontWeight = 'bold';
            }
        });
    });
    
    // Update check after fixing
    debugBlueprintSpans();
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