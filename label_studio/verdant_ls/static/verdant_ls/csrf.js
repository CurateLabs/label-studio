/* Apache-2.0. Optional native client hooks; no replaced globals or prototypes. */
(() => {
  let notice;
  function expired() {
    if (!notice) {
      notice = document.createElement('aside');
      notice.setAttribute('role', 'alert');
      notice.style.cssText = 'position:fixed;left:1rem;right:1rem;top:1rem;z-index:100000;background:#fff;color:#222;border:2px solid #8a5000;padding:1rem;box-shadow:0 2px 12px #0003';
      notice.append('Sign-in expired. Keep this labeling tab open. ');
      const link = document.createElement('a');
      link.href = '/oidc/login/?next=%2F';
      link.target = '_blank';
      link.rel = 'noopener';
      link.textContent = 'Sign in again in a new tab';
      notice.append(link, ', return here, then retry saving.');
      document.body.append(notice);
    }
    return true;
  }
  function csrfToken() {
    return document.cookie.split('; ').find(value => value.startsWith('__Host-ls_csrf='))?.split('=')[1];
  }
  window.LSBridgeAuth = {
    expired,
    csrfToken,
    prepareRequest(headers, method, url) {
      if (!/^(GET|HEAD|OPTIONS|TRACE)$/i.test(method) && new URL(url, location.href).origin === location.origin && csrfToken()) {
        headers.set('X-CSRFToken', csrfToken());
      }
    },
  };
  window.addEventListener('focus', async () => {
    if (!notice) return;
    try {
      const response = await fetch('/api/current-user/whoami', { credentials: 'same-origin' });
      if (response.ok) { notice.remove(); notice = null; }
    } catch { /* Preserve the explicit sign-in action during an outage. */ }
  });
})();
