// =============================================================================
// Smart Campus Analytics — Master Client-Side JavaScript (Phase 4)
// =============================================================================

// Toggle password visibility on login page
function togglePassword() {
    const input = document.getElementById('password');
    const icon = document.getElementById('toggle-icon');
    if (!input || !icon) return;

    if (input.type === 'password') {
        input.type = 'text';
        icon.textContent = '🙈';
    } else {
        input.type = 'password';
        icon.textContent = '👁️';
    }
}

// Select a batch card and submit the hidden form
function selectBatch(batchCode) {
    const hiddenInput = document.getElementById('selected-batch');
    const form = document.getElementById('batch-form');
    if (hiddenInput && form) {
        hiddenInput.value = batchCode;
        form.submit();
    }
}

// Global alert dismisser & accessibility handlers
document.addEventListener('DOMContentLoaded', () => {
    // Enable enter key selection on batch cards for accessibility
    document.querySelectorAll('.batch-selection-card').forEach(card => {
        card.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                card.click();
            }
        });
    });

    // -------------------------------------------------------------------------
    // Phase 9: Auto-Logout after 15 Minutes of Inactivity
    // -------------------------------------------------------------------------
    (function setupInactivityTimer() {
        // Only run for authenticated pages (which render the app-header)
        const header = document.querySelector('.app-header');
        if (!header) return;

        // 15 minutes = 15 * 60 * 1000 ms = 900,000 ms
        const TIMEOUT_DURATION_MS = 15 * 60 * 1000;
        let inactivityTimer = null;

        function resetTimer() {
            if (inactivityTimer) {
                clearTimeout(inactivityTimer);
            }
            inactivityTimer = setTimeout(() => {
                // Redirect user to logout route with inactivity flag
                window.location.href = '/logout?inactivity=1';
            }, TIMEOUT_DURATION_MS);
        }

        // Track user presence events
        const userActivityEvents = ['mousemove', 'mousedown', 'keydown', 'touchstart', 'scroll', 'click'];
        userActivityEvents.forEach(eventName => {
            window.addEventListener(eventName, resetTimer, { passive: true });
        });

        // Initialize timer
        resetTimer();
    })();
});
