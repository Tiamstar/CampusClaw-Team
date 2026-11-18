import { createApp } from 'vue'
import App from './App.vue'
import {createAppRouter} from './router'
import './style.css'
import './agent.css'
import './agent-rich.css'
import './workspace.css'
import 'katex/dist/katex.min.css'
import './math.css'
const router=createAppRouter()
const app=createApp(App).use(router)
void router.isReady().then(()=>app.mount('#app'))
