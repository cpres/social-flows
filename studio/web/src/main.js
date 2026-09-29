import { createApp } from 'vue'
import { createRouter, createWebHashHistory } from 'vue-router'
import App from './App.vue'
import Home from './views/Home.vue'
import ReelView from './views/ReelView.vue'
import RendersView from './views/RendersView.vue'
import ShootView from './views/ShootView.vue'
import './style.css'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', component: Home },
    { path: '/shoot/:name', component: ShootView, props: true },
    { path: '/reel/:id', component: ReelView, props: true },
    { path: '/renders', component: RendersView },
  ],
})

createApp(App).use(router).mount('#app')
