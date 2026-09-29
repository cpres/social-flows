<template>
  <div class="modal" @click.self="$emit('close')">
    <div class="dialog phone">
      <h2>Send to phone</h2>
      <p class="muted" v-if="loading">Making a link…</p>
      <p class="err" v-else-if="error">{{ error }}</p>
      <template v-else>
        <p class="muted">Scan with your phone's camera. It has to be on the same Wi-Fi as this Mac.</p>
        <img class="qr" :src="qr" alt="QR code for the download link" />
        <p class="mono link">{{ url }}</p>
        <p class="muted small">
          Only this video is shared. The link stops working in {{ minutes }} minutes.
          If macOS asks whether Python may accept incoming connections, allow it once.
        </p>
      </template>
      <div class="controls">
        <button class="btn" v-if="url" @click="copy">{{ copied ? 'Copied' : 'Copy link' }}</button>
        <button class="btn primary" @click="$emit('close')">Done</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import QRCode from 'qrcode'
import { api } from '../api'

const props = defineProps({ name: { type: String, required: true } })   // file in the renders folder
defineEmits(['close'])

const loading = ref(true)
const error = ref('')
const url = ref('')
const qr = ref('')
const minutes = ref(60)
const copied = ref(false)

onMounted(async () => {
  try {
    const r = await api.shareRendered(props.name)
    url.value = r.url
    minutes.value = r.minutes
    qr.value = await QRCode.toDataURL(r.url, { width: 280, margin: 1, errorCorrectionLevel: 'M' })
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
})

async function copy() {
  try {
    await navigator.clipboard.writeText(url.value)
    copied.value = true
  } catch { /* clipboard not allowed */ }
}
</script>

<style scoped>
.phone { width: min(420px, 100%); text-align: center; }
.qr { width: 280px; height: 280px; background: #fff; padding: 10px; border-radius: 12px; margin: 8px auto; display: block; }
.link { word-break: break-all; font-size: 12px; }
.small { font-size: 12px; }
.err { color: var(--danger); }
.controls { justify-content: center; }
</style>
