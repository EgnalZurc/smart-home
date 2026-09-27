// Toast notification system (F0.29 + F0.31)
// Usage: showToast('Message', 'success' | 'error' | 'warning' | 'info')

let _timer = null;

export function showToast(message, type = 'info', duration = 3000) {
    const toast = document.getElementById('notification-toast');
    const text  = document.getElementById('notification-text');
    if (!toast || !text) return;

    text.textContent = message;
    toast.className = 'notification-toast show ' + type;

    if (_timer) clearTimeout(_timer);
    _timer = setTimeout(() => {
        toast.classList.remove('show');
    }, duration);
}
