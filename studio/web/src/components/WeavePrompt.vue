<template>
  <section class="weaveprompt" role="dialog" aria-label="Weave a reel">
    <span class="ico" aria-hidden="true">⧉</span>
    <div class="text">
      <b>You brought in {{ videos }} video{{ videos === 1 ? '' : 's' }}<template v-if="long"> ({{ long }} of 15s or more)</template><template
        v-if="photos"> and {{ photos }} photo{{ photos === 1 ? '' : 's' }}</template>.</b>
      <template v-if="draft">You have a weave draft for this shoot; they'll be added to it.</template>
      <template v-else>
        Want help cutting them into parts and weaving them into a reel? A bit of each clip, then the next,
        then back for a later bit, on the beat if there's a song.
      </template>
    </div>
    <button class="btn primary" @click="$emit('weave')">{{ draft ? 'Continue weave' : 'Weave a reel' }}</button>
    <button class="btn" @click="$emit('dismiss')">Not now</button>
  </section>
</template>

<script setup>
// Shown on the shoot page right after an import that's worth weaving.
defineProps({
  videos: { type: Number, required: true },
  long: { type: Number, default: 0 },     // how many run over the split length
  photos: { type: Number, default: 0 },
  draft: Boolean,                         // this shoot has a Weave draft already
})
defineEmits(['weave', 'dismiss'])
</script>

<style scoped>
.weaveprompt {
  display: flex; align-items: center; gap: 14px; flex-wrap: wrap; margin-top: 14px; padding: 12px 16px;
  border-radius: var(--radius); background: var(--sage-soft); border: 1px solid var(--sage);
}
.ico { font-size: 22px; color: var(--forest); }
.text { flex: 1; min-width: 260px; font-size: 14px; }
.text b { color: var(--forest); }
</style>
