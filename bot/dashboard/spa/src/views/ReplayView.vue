<template>
  <div class="breadcrumb"><router-link to="/live">Dashboard</router-link> / Replay</div>
  <h1>Replay</h1>

  <div v-if="error" class="error-banner">{{ error }}</div>

  <div class="filters">
    <div class="filter-group">
      <label for="file-select">Signal CSV</label>
      <select id="file-select" v-model="selectedFile" @change="load" :disabled="files.length === 0">
        <option value="">{{ files.length === 0 ? 'No CSVs found' : '-- select --' }}</option>
        <option v-for="f in files" :key="f.name" :value="f.name">
          {{ f.name }} ({{ (f.size / 1024).toFixed(1) }} KB)
        </option>
      </select>
    </div>
    <button class="btn btn-secondary" @click="load" :disabled="!selectedFile || loading">
      {{ loading ? 'Loading…' : 'Load CSV' }}
    </button>
    <span style="font-size: 0.875rem; color: var(--color-text-muted); margin-left: auto;">
      {{ rows.length }} rows
    </span>
  </div>

  <div class="card">
    <PlotlyChart :traces="traces" :layout="layout" height="500px" />
  </div>

  <div class="table-wrap" v-if="rows.length > 0">
    <table>
      <thead>
        <tr>
          <th>Source</th><th>Run ID</th><th>Signal ID</th><th>Event</th>
          <th>Symbol</th><th>TF</th><th>Side</th><th>Level</th>
          <th>State</th><th>Bar Time</th><th>Decision</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="(r, i) in rows.slice(0, 100)" :key="i">
          <td>{{ r.source }}</td>
          <td><code class="signal-id">{{ shortId(r.run_id) }}</code></td>
          <td><code class="signal-id">{{ shortId(r.signal_id) }}</code></td>
          <td>{{ r.event }}</td>
          <td>{{ r.symbol }}</td>
          <td>{{ r.tf }}</td>
          <td>{{ r.side }}</td>
          <td><code>{{ r.level }}</code></td>
          <td>{{ r.state }}</td>
          <td>{{ r.bar_time }}</td>
          <td>{{ r.decision || '—' }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue';
import { api } from '../api/client.js';
import PlotlyChart from '../components/PlotlyChart.vue';

const files = ref([]);
const selectedFile = ref('');
const rows = ref([]);
const loading = ref(false);
const error = ref('');

const traces = computed(() => {
  if (!rows.value.length) return [];
  const x = rows.value.map(r => Number(r.bar_time)).filter(Number.isFinite);
  const y = rows.value.map(r => Number(r.level)).filter(Number.isFinite);
  const c = rows.value.map(r => {
    if (r.decision === 'accept') return '#22C55E';
    if (r.decision === 'reject') return '#EF4444';
    return '#94A3B8';
  });
  return [{
    x, y, mode: 'markers', type: 'scatter',
    marker: { size: 10, color: c, line: { width: 1, color: '#1E293B' } },
    text: rows.value.map(r => `${r.event} ${r.symbol} ${r.decision || ''}`),
    hovertemplate: '<b>%{text}</b><br>level=%{y}<br>bar=%{x}<extra></extra>',
  }];
});

const layout = computed(() => ({
  xaxis: { title: 'Bar Time (epoch)' },
  yaxis: { title: 'Level' },
}));

function shortId(s) { return (s || '').slice(0, 12) + '…'; }

async function load() {
  if (!selectedFile.value) return;
  loading.value = true;
  error.value = '';
  try {
    const data = await api.replayCsv(selectedFile.value);
    rows.value = data.rows || [];
  } catch (e) {
    error.value = 'Error: ' + (e.message || e);
  } finally {
    loading.value = false;
  }
}

async function loadFiles() {
  try {
    const data = await api.replay();
    files.value = data.files || [];
  } catch (e) {
    error.value = 'Error: ' + (e.message || e);
  }
}

onMounted(loadFiles);
</script>
