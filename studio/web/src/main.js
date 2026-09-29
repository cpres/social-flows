import { createApp } from 'vue'
import { createRouter, createWebHashHistory } from 'vue-router'
import App from './App.vue'
import FolderGrid from './views/FolderGrid.vue'
import FolderView from './views/FolderView.vue'
import './style.css'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', component: FolderGrid },
    { path: '/folder/:name', component: FolderView, props: true },
  ],
})

createApp(App).use(router).mount('#app')
