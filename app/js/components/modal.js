/**
 * Modal dialog system for errors, confirmations, and notifications.
 */
const Modal = (() => {
  let _overlay, _title, _body, _footer, _closeBtn;

  function init() {
    _overlay = document.getElementById('modal-overlay');
    _title = document.getElementById('modal-title');
    _body = document.getElementById('modal-body');
    _footer = document.getElementById('modal-footer');
    _closeBtn = document.getElementById('modal-close');
    _closeBtn?.addEventListener('click', hide);
    _overlay?.addEventListener('click', (e) => { if (e.target === _overlay) hide(); });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !_overlay?.classList.contains('hidden')) hide(); });
  }

  function show(opts) {
    _title.textContent = opts.title || '';
    _body.innerHTML = '';
    if (typeof opts.body === 'string') { const p = document.createElement('p'); p.textContent = opts.body; _body.appendChild(p); }
    if (opts.actions?.length) {
      const d = document.createElement('div'); d.className = 'modal-actions';
      opts.actions.forEach(a => {
        const btn = document.createElement('button');
        btn.className = 'modal-action-btn'; btn.textContent = a.label;
        btn.addEventListener('click', () => { if (a.callback) a.callback(); hide(); });
        d.appendChild(btn);
      });
      _body.appendChild(d);
    }
    _footer.innerHTML = '';
    if (opts.footer) opts.footer.forEach(a => {
      const btn = document.createElement('button');
      btn.className = a.type === 'primary' ? 'btn btn-primary' : 'btn btn-secondary';
      btn.textContent = a.label; btn.style.fontSize = 'var(--font-size-sm)';
      btn.addEventListener('click', () => { if (a.callback) a.callback(); hide(); });
      _footer.appendChild(btn);
    });
    _overlay?.classList.remove('hidden');
  }

  function hide() { _overlay?.classList.add('hidden'); }
  return { init, show, hide };
})();
