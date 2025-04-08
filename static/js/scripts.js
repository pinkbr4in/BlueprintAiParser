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