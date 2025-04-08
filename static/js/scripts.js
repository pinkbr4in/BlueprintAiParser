/ static/js/scripts.js

document.addEventListener('DOMContentLoaded', function() {
    // You can add any other blueprint-parser specific JS here if needed.
    console.log('Blueprint parser custom scripts loaded.');

    // Example: Maybe add focus styling to the textarea
    const blueprintTextArea = document.getElementById('blueprintText');
    if (blueprintTextArea) {
        blueprintTextArea.addEventListener('focus', () => {
            blueprintTextArea.classList.add('focused'); // You'd need to define '.focused' in CSS
        });
        blueprintTextArea.addEventListener('blur', () => {
            blueprintTextArea.classList.remove('focused');
        });
    }
});

document.getElementById('copy-output-btn').addEventListener('click', function() {
    const outputContent = document.querySelector('.result-box').innerText;
    
    // Create a temporary textarea to copy from
    const textarea = document.createElement('textarea');
    textarea.value = outputContent;
    document.body.appendChild(textarea);
    textarea.select();
    
    try {
      document.execCommand('copy');
      // Show success feedback
      this.innerHTML = '<i class="fas fa-check"></i> Copied!';
      setTimeout(() => {
        this.innerHTML = '<i class="fas fa-copy"></i> Copy to Clipboard';
      }, 2000);
    } catch (err) {
      console.error('Failed to copy: ', err);
    } finally {
      document.body.removeChild(textarea);
    }
  });