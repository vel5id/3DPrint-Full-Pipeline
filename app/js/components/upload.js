/**
 * Image upload zone — drag-drop, click-to-browse, paste.
 */
const Upload = (() => {
  let _zone, _input, _preview, _clear, _placeholder;

  function init() {
    _zone = document.getElementById('upload-zone');
    _input = document.getElementById('upload-input');
    _preview = document.getElementById('upload-preview');
    _clear = document.getElementById('upload-clear');
    _placeholder = _zone?.querySelector('.upload-placeholder');

    _zone?.addEventListener('click', () => _input.click());
    _input?.addEventListener('change', (e) => { if (e.target.files[0]) handleFile(e.target.files[0]); });

    _zone?.addEventListener('dragover', (e) => { e.preventDefault(); _zone.classList.add('drag-over'); });
    _zone?.addEventListener('dragleave', () => _zone.classList.remove('drag-over'));
    _zone?.addEventListener('drop', (e) => {
      e.preventDefault();
      _zone.classList.remove('drag-over');
      const file = e.dataTransfer.files[0];
      if (file && file.type.startsWith('image/')) handleFile(file);
    });

    document.addEventListener('paste', (e) => {
      for (const item of e.clipboardData?.items || []) {
        if (item.type.startsWith('image/')) { handleFile(item.getAsFile()); break; }
      }
    });

    _clear?.addEventListener('click', (e) => { e.stopPropagation(); clear(); });
  }

  function handleFile(file) {
    if (!file.type.match(/^image\/(png|jpeg|webp)$/)) {
      Modal.show({ title: 'Invalid File', body: 'Please use PNG, JPG, or WEBP images.', footer: [{ label: 'OK', type: 'primary' }] });
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      Modal.show({ title: 'File Too Large', body: 'Maximum file size is 10 MB.', footer: [{ label: 'OK', type: 'primary' }] });
      return;
    }
    AppState.set('image', file);
    const blobUrl = URL.createObjectURL(file);
    const old = AppState.get('imagePreview');
    if (old) URL.revokeObjectURL(old);
    AppState.set('imagePreview', blobUrl);
    _preview.src = blobUrl;
    _preview?.classList.remove('hidden');
    _placeholder?.classList.add('hidden');
    _clear?.classList.remove('hidden');
    const reader = new FileReader();
    reader.onload = () => AppState.set('imageDataUrl', reader.result);
    reader.readAsDataURL(file);
  }

  function clear() {
    const old = AppState.get('imagePreview');
    if (old) URL.revokeObjectURL(old);
    AppState.setAll({ 'image': null, 'imagePreview': null, 'imageDataUrl': null });
    _preview.src = '';
    _preview?.classList.add('hidden');
    _placeholder?.classList.remove('hidden');
    _clear?.classList.add('hidden');
    _input.value = '';
  }

  return { init, handleFile, clear };
})();
