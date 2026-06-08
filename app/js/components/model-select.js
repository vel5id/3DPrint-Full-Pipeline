/**
 * Model family, variant, and texture selector dropdowns.
 */
const ModelSelect = (() => {
  function init() {
    const area = document.getElementById('model-select-area');
    area.innerHTML = `
      <div class="model-select-group">
        <span class="model-select-label">Shape Model</span>
        <select id="model-family-select" class="model-select-dropdown"></select>
      </div>
      <div class="model-select-group">
        <span class="model-select-label">Speed Variant</span>
        <select id="model-variant-select" class="model-select-dropdown"></select>
      </div>
      <div class="model-select-group" id="tex-model-group">
        <span class="model-select-label">Texture Model</span>
        <select id="tex-model-select" class="model-select-dropdown"></select>
      </div>
    `;
    loadModelList();
  }

  async function loadModelList() {
    try {
      const data = await API.modelStatus();
      populateDropdown('model-family-select', data.families || [], data.shape_family);
      populateDropdown('model-variant-select', data.variants || [], data.shape_variant);
      populateDropdown('tex-model-select', data.tex_models || [], data.tex_key);

      document.getElementById('model-family-select').addEventListener('change', async function () {
        const family = this.value;
        // Fetch variants for the selected family
        const status = await API.modelStatus(family);
        populateDropdown('model-variant-select', status.variants || [], status.variants[0]?.key);
        // Auto-load the new family with first available variant
        const variant = status.variants[0]?.key || 'turbo';
        await switchModel(family, variant);
      });

      document.getElementById('model-variant-select').addEventListener('change', async function () {
        const family = document.getElementById('model-family-select').value;
        await switchModel(family, this.value);
      });

      document.getElementById('tex-model-select').addEventListener('change', function () {
        AppState.set('model.texKey', this.value);
      });
    } catch (e) {
      console.warn('Failed to load model list:', e);
    }
  }

  async function switchModel(family, variant) {
    try {
      const result = await API.loadModel(family, variant);
      AppState.setAll({
        'model.family': family,
        'model.variant': variant,
        'model.familyDisplay': result.model_display || family,
        'params.steps': result.default_steps || 15,
      });
      StatusBar.updateModel(result.model_display);
      document.getElementById('model-display-name').textContent = result.model_display;
      Params.syncFromState();
    } catch (e) {
      console.warn('Failed to switch model:', e);
      Modal.show({
        title: 'Model Switch Failed',
        body: e.message || 'Could not load the selected model.',
        footer: [{ label: 'OK', type: 'primary' }],
      });
    }
  }

  function populateDropdown(id, items, selectedKey) {
    const sel = document.getElementById(id);
    if (!sel) return;
    sel.innerHTML = '';
    items.forEach(item => {
      const opt = document.createElement('option');
      opt.value = item.key;
      opt.textContent = item.display || item.key;
      if (item.key === selectedKey) opt.selected = true;
      sel.appendChild(opt);
    });
  }

  return { init };
})();
