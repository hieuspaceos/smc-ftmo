<template>
  <div class="breadcrumb"><router-link to="/live">Dashboard</router-link> / Live</div>
  <h1>Live Queue</h1>

  <div class="kpi" v-if="!error">
    <div class="kpi-card">
      <div class="kpi-value">{{ rows.length }}</div>
      <div class="kpi-label">Total Alerts</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-value" style="color: var(--color-warning);">{{ pendingCount }}</div>
      <div class="kpi-label">Pending Decision</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-value" style="color: var(--color-success);">{{ acceptedCount }}</div>
      <div class="kpi-label">Accepted</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-value" style="color: var(--color-danger);">{{ rejectedCount }}</div>
      <div class="kpi-label">Rejected</div>
    </div>
  </div>

  <div v-if="error" class="error-banner">{{ error }}</div>

  <div class="filters">
    <div class="filter-group">
      <label for="state">State</label>
      <select id="state" v-model="state" @change="load">
        <option value="">All states</option>
        <option value="chart-qualified">Chart-qualified</option>
        <option value="watch">Watch</option>
        <option value="blocked">Blocked</option>
        <option value="no-signal">No-signal</option>
      </select>
    </div>
    <div class="filter-group">
      <label for="limit">Limit</label>
      <select id="limit" v-model.number="limit" @change="load">
        <option :value="50">50</option>
        <option :value="100">100</option>
        <option :value="200">200</option>
        <option :value="500">500</option>
      </select>
    </div>
    <button class="btn btn-secondary" @click="load" :disabled="loading">{{ loading ? 'Loading…' : 'Refresh' }}</button>
    <span style="font-size: 0.8rem; color: var(--color-text-muted); margin-left: auto;">
      Updated {{ updatedAt || '—' }}
    </span>
  </div>

  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>Signal ID</th>
          <th>Symbol</th><th>TF</th><th>Side</th>
          <th>Event</th><th>State</th>
          <th>Level</th><th>Decision</th>
          <th>Actor</th><th>Received</th>
        </tr>
      </thead>
      <tbody>
        <tr v-if="rows.length === 0">
          <td colspan="10" class="empty">
            <h3>No alerts yet</h3>
            <p>Send a test alert via <code>POST /webhooks/tradingview</code></p>
          </td>
        </tr>
        <tr v-for="r in rows" :key="r.signal_id">
          <td><code class="signal-id">{{ shortId(r.signal_id) }}</code></td>
          <td>{{ r.symbol }}</td><td>{{ r.tf }}</td><td>{{ r.side }}</td>
          <td>{{ r.event }}</td>
          <td><span class="badge" :class="badgeClass(r.state)">{{ r.state }}</span></td>
          <td><code>{{ r.level }}</code></td>
          <td v-html="decisionBadge(r.decision)"></td>
          <td>{{ r.decision_actor || '—' }}</td>
          <td>{{ fmtTime(r.received_at) }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue';
import { api, badgeClass, decisionBadge, escape, fmtTime } from '../api/client.js';

const state = ref('');
const limit = ref(100);
const rows = ref([]);
const loading = ref(false);
const error = ref('');
const updatedAt = ref('');

const pendingCount = computed(() => rows.value.filter(r => !r.decision).length);
const acceptedCount = computed(() => rows.value.filter(r => r.decision === 'accept').length);
const rejectedCount = computed(() => rows.value.filter(r => r.decision === 'reject').length);

async function load() {
  loading.value = true;
  error.value = '';
  try {
    const data = await api.alerts({ state: state.value, limit: limit.value });
    rows.value = data.rows || [];
    updatedAt.value = new Date().toLocaleTimeString();
  } catch (e) {
    error.value = 'Error: ' + (e.message || e);
  } finally {
    loading.value = false;
  }
}

function shortId(s) { return (s || '').slice(0, 12) + '…'; }

let timer = null;
onMounted(() => { load(); timer = setInterval(load, 10000); });
onBeforeUnmount(() => { if (timer) clearInterval(timer); });
</script>
