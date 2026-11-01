<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue';
import { MessageSquare, Send, Sparkles, LoaderCircle, Quote } from 'lucide-vue-next';
const props = defineProps<{sessionId:string; taskId:string; demo:boolean}>();
const emit = defineEmits(['cite']);
const messages = ref<any[]>([]), draft = ref(''), error = ref(''), sending = ref(false);
const list = ref<HTMLElement|null>(null);
const working = computed(() => sending.value || messages.value.some(m => m.status === 'running'));
let timer: ReturnType<typeof setInterval>;
let disposed = false, refreshing = false;
async function refresh() {
  if(refreshing || disposed) return;
  refreshing = true;
  try {
  const response = await fetch('/api/sessions/' + props.sessionId);
  if(!response.ok) throw new Error('会话读取失败，请刷新重试');
  const data = await response.json();
  if(disposed) return;
  const nearBottom = !list.value || list.value.scrollHeight-list.value.scrollTop-list.value.clientHeight<80;
  const firstLoad = !messages.value.length;
  const changed = JSON.stringify(messages.value) !== JSON.stringify(data.messages);
  messages.value = data.messages;
  if(changed) { await nextTick(); if(list.value && (nearBottom || firstLoad)) list.value.scrollTo({top:list.value.scrollHeight,behavior:firstLoad || matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth'}); }
  if(error.value==='会话读取失败，请刷新重试' || error.value==='Failed to fetch') error.value='';
  } finally {refreshing=false;}
}
async function send() {
  if(!draft.value.trim() || working.value || props.demo) return;
  sending.value = true; error.value = '';
  try {
    const response = await fetch('/api/sessions/' + props.sessionId + '/messages', {method:'POST', headers:{'Content-Type':'application/json'},body:JSON.stringify({content:draft.value,task_id:props.taskId})});
    const data = await response.json();
    if(!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '发送失败，请检查内容');
    draft.value = ''; await refresh();
  } catch(e) {error.value=(e as Error).message;} finally {sending.value=false;}
}
function keydown(e: KeyboardEvent) { if(e.key==='Enter' && !e.shiftKey && !e.isComposing) {e.preventDefault();send();} }
onMounted(async () => {
  timer=setInterval(() => { if(!document.hidden) refresh().catch(e => error.value=e.message); },3000);
  try {await refresh();} catch(e) {error.value=(e as Error).message;}
});
onUnmounted(() => {disposed=true;clearInterval(timer);});
</script>

<template>
  <aside class="chat-pane" aria-label="研究会话">
    <header class="chat-header"><div><MessageSquare :size="18"/><b>研究对话</b></div><span>自动保存</span></header>
    <p class="chat-context">围绕当前版本的文献与证据追问。新检索请使用「追加调研」。</p>
    <div class="chat-messages" ref="list" role="log" aria-label="会话消息" aria-live="polite">
      <div v-if="!messages.length" class="chat-empty"><div><Sparkles :size="25"/></div><h3>让研究继续深入</h3><p>报告只是起点。比较方法、追问实验条件，或请 Agent 解释一条结论。</p><button @click="draft='请比较本次论文的方法差异，并说明哪些结果不能直接比较。'">比较方法与实验条件</button><button @click="draft='这份报告还有哪些证据缺口？请给出下一步阅读建议。'">梳理证据缺口</button></div>
      <article v-for="message in messages" :key="message.id" :class="['chat-message', message.role, message.status]">
        <div class="message-label"><span>{{message.role==='user' ? '你' : '知序 Agent'}}</span><time>{{new Date(message.created).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'})}}</time></div>
        <div v-if="message.status==='running'" class="chat-thinking"><LoaderCircle class="spin" :size="16"/>正在结合文献与会话思考…</div>
        <p v-else>{{message.content}}</p>
        <div v-if="message.evidence_ids.length" class="chat-citations"><button v-for="(id,i) in message.evidence_ids" :key="id" :title="id" @click="emit('cite',{id,taskId:message.task_id})"><Quote :size="12"/>证据 {{i+1}}</button></div>
        <small v-if="message.role==='assistant' && message.status==='completed'">基于调研 {{message.task_id.slice(0,6)}} · {{Object.values(message.usage).reduce((n:number,u:any)=>n+u.input_tokens+u.output_tokens,0)}} tokens</small>
      </article>
    </div>
    <div v-if="error" class="chat-error" role="alert">{{error}}<button @click="refresh().then(()=>error='').catch(()=>{})">重新连接</button></div>
    <form class="chat-composer" @submit.prevent="send"><label for="followup">{{demo ? '离线演示不调用模型' : '继续追问'}}</label><textarea id="followup" v-model="draft" :disabled="demo" maxlength="4000" rows="3" placeholder="例如：这个结论有哪些原文支持？" @keydown="keydown"></textarea><footer><span>Enter 发送 · Shift+Enter 换行</span><button class="primary" :disabled="working || !draft.trim() || demo" aria-label="发送追问"><Send :size="16"/></button></footer></form>
  </aside>
</template>
