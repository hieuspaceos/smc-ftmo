<template>
  <div ref="container" :style="{ height: height }"></div>
</template>

<script setup>
import { onMounted, onBeforeUnmount, ref, watch } from 'vue';

const props = defineProps({
  traces: { type: Array, required: true },
  layout: { type: Object, default: () => ({}) },
  height: { type: String, default: '500px' },
});

const container = ref(null);

function render() {
  if (!container.value || !window.Plotly) return;
  window.Plotly.react(container.value, props.traces, {
    margin: { t: 30, l: 60, r: 20, b: 50 },
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    font: { family: 'Fira Sans, system-ui', color: '#1E293B' },
    showlegend: false,
    ...props.layout,
  }, { displayModeBar: true, responsive: true });
}

onMounted(render);
watch(() => [props.traces, props.layout], render, { deep: true });

onBeforeUnmount(() => {
  if (container.value && window.Plotly) window.Plotly.purge(container.value);
});
</script>
