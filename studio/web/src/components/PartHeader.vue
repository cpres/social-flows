<template>
  <div class="parthead" :class="`lane-${info.lane}`">
    <div class="band">
      <span class="badge">{{ info.lane }}</span>
      <div class="lines">
        <b>{{ info.title }}</b>
        <small v-if="info.scene">{{ info.scene }}</small>
      </div>
    </div>
    <p class="shows" :class="{ hidden: info.hidden }" v-html="info.shows"></p>
    <div class="lane" v-if="info.canMove">
      <span class="muted small">Lane</span>
      <div class="toggle">
        <button class="la" :class="{ on: info.lane === 'A' }" :disabled="info.lane === 'A'" @click="$emit('lane', 'A')">A · {{ wide ? 'left' : 'top' }}</button>
        <button class="lb" :class="{ on: info.lane === 'B' }" :disabled="info.lane === 'B'" @click="$emit('lane', 'B')">B · {{ wide ? 'right' : 'bottom' }}</button>
      </div>
      <small class="muted">{{ info.moveHint }}</small>
    </div>
  </div>
</template>

<script setup>
// The inspector's header: which lane the selected part is on (a band in the
// lane's colour), where it sits, whether it's seen, and the Lane toggle.
defineProps({
  // {lane: 'A' | 'B', title, scene, shows (may hold <b>), hidden, canMove, moveHint}
  info: { type: Object, required: true },
  wide: Boolean,
})
defineEmits(['lane'])
</script>

<style scoped>
.parthead { border-radius: var(--radius); overflow: hidden; border: 1px solid var(--line); background: var(--paper); margin-bottom: 30px; }
.band { display: flex; align-items: center; gap: 12px; padding: 12px 14px; }
.lane-A .band { background: var(--lane-a-soft); border-bottom: 2px solid var(--lane-a); }
.lane-B .band { background: var(--lane-b-soft); border-bottom: 2px solid var(--lane-b); }
.badge {
  display: grid; place-items: center; width: 36px; height: 36px; border-radius: 9px; font-weight: 800; font-size: 20px; color: var(--on-lane);
}
.lane-A .badge { background: var(--lane-a); }
.lane-B .badge { background: var(--lane-b); }
.lines { display: flex; flex-direction: column; gap: 2px; }
.lines b { font-size: 15px; }
.lines small { color: var(--muted); font-size: 12px; }
.shows { margin: 10px 14px; font-size: 14px; }
.shows.hidden { color: var(--muted); }
.lane { display: flex; flex-direction: column; gap: 6px; padding: 0 14px 12px; }
.toggle { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
.toggle button {
  padding: 8px; border-radius: 8px; border: 1px solid var(--line); background: transparent; color: inherit; font: inherit; cursor: pointer;
}
.toggle button:disabled { cursor: default; }
.toggle .la.on { background: var(--lane-a); border-color: var(--lane-a); color: var(--on-lane); font-weight: 600; }
.toggle .lb.on { background: var(--lane-b); border-color: var(--lane-b); color: var(--on-lane); font-weight: 600; }
</style>
