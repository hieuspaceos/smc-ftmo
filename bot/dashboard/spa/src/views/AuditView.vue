<template>
  <div class="breadcrumb"><router-link to="/live">Dashboard</router-link> / Audit</div>
  <h1>Audit</h1>

  <div v-if="error" class="error-banner">{{ error }}</div>

  <div class="filters">
    <div class="filter-group">
      <label for="decision">Decision</label>
      <select id="decision" v-model="decision" @change="load">
        <option value="">All</option>
        <option value="accept">accept</option>
        <option value="reject">reject</option>
        <option value="blocked_chart">blocked_chart</option>
        <option value="expired">expired</option>
        <option value="edit_failed">edit_failed</option>
        <option value="notified_failed">notified_failed</option>
      </select>
    </div>
    <div class="filter-group">
      <label for="user">User (actor)</label>
      <input id="user" type="text" v-model="user" @keyup.enter="load" placeholder="e.g. tester1" />
    </div>
    <div class="filter-group">
      <label for="csv">Signal CSV</label>
      <select id="csv" v-model="signalCsv" @change="load">
        <option value="">(none)</option>
        <option v-for="f in csvFiles" :key="f.name" :value="f.name">{{ f.name }}</option>
      </select>
    </div>
    <button class="btn btn-primary" @click="load">Apply</button>
    <button class="btn btn-secondary" @click="exportCsv">Export CSV</button>
    <span style="font-size: 0.875rem; color: var(--color-text-muted); margin-left: auto;">
      {{ events.length }} events
    </span>
  </div>

  <div class="table-wrap">
    <table>
      <thead>
        <tr><th>When</th><th>Event</th><th>Actor</th><th>Signal ID</th><th>Payload</th></tr>
      </thead>
      <tbody>
        <tr v-if="events.length === 0">
          <td colspan="5" class="empty">No events match the filters.</td>
        </tr>
        <tr v-for="e in events" :key="e.signal_id + e.event_type + e.created_at">
          <td>{{ fmtTime(e.created_at) }}</td>
          <td><span class="badge" :class="auditBadge(e.event_type)">{{ e.event_type }}</span></td>
          <td>{{ e.actor || '—' }}</td>
          <td><code class="signal-id">{{ shortId(e.signal_id) }}</code></td>
          <td><code>{{ shortJson(e.payload) }}</code></td>
        </tr>
      </tbody>
    </table>
  </div>

  <div class="card" v-if="csvRows.length > 0">
    <div class="card-title">Signal CSV rows</div>
    <div class="table-wrap">
      <table>
        <thead><tr><th>Source</th><th>Signal ID</th><th>Event</th><th>Side</th><th>Level</th></tr></thead>
        <tbody>
          <tr v-for="(r, i) in csvRows.slice(0, 100)" :key="i">
            <td>{{ r.source }}</td>
            <td><code class="signal-id">{{ shortId(r.signal_id) }}</code></td>
            <td>{{ r.event }}</td>
            <td>{{ r.side }}</td>
            <td><code>{{ r.level }}</code></td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue';
import { api, escape, fmtTime } from '../api/client.js';

const decision = ref('');
const user = ref('');
const signalCsv = ref('');
const events = ref([]);
const csvRows = ref([]);
const csvFiles = ref([]);
const error = ref('');

function auditBadge(t) {
  if (t === 'accept') return 'badge-accept';
  if (t === 'reject') return 'badge-reject';
  if (t === 'blocked_chart' || t === 'expired') return 'badge-blocked';
  return 'badge-neutral';
}
function shortId(s) { return (s || '').slice(0, 12) + '…'; }
function shortJson(s) {
  if (!s) return '';
  return s.length > 60 ? escape(s.slice(0, 60)) + '…' : escape(s);
}

async function load() {
  error.value = '';
  try {
    const params = {};
    if (decision.value) params.decision = decision.value;
    if (user.value) params.user = user.value;
    if (signalCsv.value) params.signal_csv = signalCsv.value;
    const data = await api.audit(params);
    events.value = data.events || [];
    csvRows.value = data.csv_rows || [];
  } catch (e) {
    error.value = 'Error: ' + (e.message || e);
  }
}

async function loadCsvFiles() {
  try {
    const data = await api.replay();
    csvFiles.value = data.files || [];
  } catch (e) {
    error.value = 'Error: ' + (e.message || e);
  }
}

async function exportCsv() {
  const params = {};
  if (decision.value) params.decision = decision.value;
  if (user.value) params.user = user.value;
  if (signalCsv.value) params.signal_csv = signalCsv.value;
  params.limit = '200';
  try {
    const data = await api.audit(params);
    const rows = [['created_at', 'event_type', 'actor', 'signal_id', 'payload']];
    (data.events || []).forEach(e => rows.push([e.created_at, e.event_type, e.actor, e.signal_id, e.payload]));
    const csv = rows.map(r => r.map(c => '"' + String(c ?? '').replace(/"/g, '""') + '"').join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'audit_' + new Date().toISOString().replace(/[:.]/g, '-') + '.csv';
    a.click();
    URL.revokeObjectURL(url);
  } catch (e) {
    error.value = 'Export error: ' + (e.message || e);
  }
}

onMounted(() => { loadCsvFiles(); load(); });
</script>
