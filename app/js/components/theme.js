/**
 * Theme manager — toggle, persist, detect system preference.
 */
const Theme = (() => {
  const STORAGE_KEY = 'hunyuan3d-theme';

  function init() {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === 'light' || saved === 'dark') {
      set(saved);
    } else {
      const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
      set(prefersDark ? 'dark' : 'light');
    }
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
      if (!localStorage.getItem(STORAGE_KEY)) set(e.matches ? 'dark' : 'light');
    });
    const btn = document.getElementById('theme-toggle');
    if (btn) btn.addEventListener('click', toggle);
  }

  function set(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem(STORAGE_KEY, theme);
    AppState.set('theme', theme);
  }

  function toggle() {
    const current = document.documentElement.getAttribute('data-theme');
    set(current === 'dark' ? 'light' : 'dark');
  }

  return { init, set, toggle };
})();
