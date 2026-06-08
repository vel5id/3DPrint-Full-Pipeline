/**
 * Bottom status bar — GPU, model, VRAM, connection info.
 */
const StatusBar = (() => {
  function init() {
    setInterval(() => { if (!AppState.get('gpu.busy')) API.health().catch(() => {}); }, 30000);
    API.health().catch(() => {});
  }

  function updateModel(name) {
    const el = document.getElementById('status-model-name'); if (el) el.textContent = name;
    const s = document.getElementById('model-display-name'); if (s) s.textContent = name;
  }

  function updateMeshStats(stats) {
    if (!stats) return;
    const el = document.getElementById('status-mesh-info');
    if (el) {
      const p = [];
      if (stats.verts) p.push(`${(stats.verts/1000).toFixed(0)}K verts`);
      if (stats.faces) p.push(`${(stats.faces/1000).toFixed(0)}K faces`);
      if (stats.time_shape) p.push(`${stats.time_shape}s`);
      el.textContent = p.join(' · ') || 'No mesh';
    }
  }

  function setGpuBusy(phase) {
    const ind = document.getElementById('status-gpu-indicator'), txt = document.getElementById('status-gpu-text');
    if (ind) ind.className = 'status-gpu-indicator busy';
    if (txt) txt.textContent = `GPU: ${phase || 'busy'}`;
    AppState.set('gpu.busy', true);
  }

  function setGpuIdle() {
    const ind = document.getElementById('status-gpu-indicator'), txt = document.getElementById('status-gpu-text');
    if (ind) ind.className = 'status-gpu-indicator idle';
    if (txt) txt.textContent = 'GPU idle';
    AppState.set('gpu.busy', false);
  }

  function setWsStatus(status) {
    const el = document.getElementById('status-ws-indicator');
    if (!el) return;
    el.className = 'status-ws-indicator';
    if (status === 'connected') el.classList.add('connected');
    if (status === 'reconnecting') el.classList.add('reconnecting');
  }

  return { init, updateModel, updateMeshStats, setGpuBusy, setGpuIdle, setWsStatus };
})();
