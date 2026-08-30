import { defineStore } from 'pinia';

export const useFiltersStore = defineStore('filters', {
  state: () => ({
    live: { state: '', limit: 100 },
    audit: { decision: '', user: '', signal_csv: '' },
    replay: { selectedFile: '' },
  }),
  actions: {
    resetLive() {
      this.live = { state: '', limit: 100 };
    },
    resetAudit() {
      this.audit = { decision: '', user: '', signal_csv: '' };
    },
  },
});
