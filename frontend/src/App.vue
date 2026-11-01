<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import Connections from "./Connections.vue";
import ChatPane from "./ChatPane.vue";
import ExecutionTrace from "./ExecutionTrace.vue";
import {
  BookOpen,
  Plus,
  Settings2,
  ArrowUpRight,
  Search,
  FileText,
  Layers,
  Quote,
  Activity,
  Check,
  Download,
  Play,
  Square,
  RotateCcw,
  ChevronRight,
  Upload,
  FlaskConical,
  CircleDot,
  ExternalLink,
  LoaderCircle,
} from "lucide-vue-next";
import { marked } from "marked";
import DOMPurify from "dompurify";

type Data = Record<string, any>;
const sessions = ref<Data[]>([]), conversation = ref<Data | null>(null), historyQuery = ref(""), parentSession = ref(""), sessionTitle = ref("");
const filteredSessions = computed(() => sessions.value.filter(s => s.title.toLowerCase().includes(historyQuery.value.toLowerCase())));
const tasks = ref<Data[]>([]),
  current = ref<Data | null>(null),
  events = ref<Data[]>([]);
const settingsOpen = ref(false),
  tab = ref("report"),
  busy = ref(false),
  notice = ref(""),
  error = ref("");
const topic = ref(""),
  focus = ref(""),
  mode = ref("live"),
  yearFrom = ref(2017),
  yearTo = ref(2026),
  maxPapers = ref(5);
const tokenBudget = ref(600000),
  callBudget = ref(120);
const sources = ref(["arxiv", "openalex", "semantic_scholar"]),
  exclude = ref(""),
  required = ref(false),
  uploads = ref<Data[]>([]);
const sideExpanded = ref(false);
const vectorQuery = ref(""),
  hits = ref<Data[]>([]),
  selectedEvidence = ref(""),
  showAdvanced = ref(false);
let stream: EventSource | null = null;
const stages = [
  { id: "search", name: "文献检索", icon: Search },
  { id: "read", name: "渐进阅读", icon: BookOpen },
  { id: "analyse", name: "综合分析", icon: Layers },
  { id: "outline", name: "章节大纲", icon: FileText },
  { id: "write", name: "证据写作", icon: Quote },
];
const labels: Record<string, string> = {
  queued: "等待中",
  running: "调研中",
  completed: "已完成",
  failed: "待处理",
  interrupted: "已中断",
  cancelled: "已停止",
  cancelling: "正在停止",
};
const levels: Record<string, string> = {
  synthetic: "合成材料",
  abstract: "摘要阅读",
  fulltext: "全文已解析",
  unavailable: "未读取",
};
const state = computed(() => current.value?.state || {});
const working = computed(() =>
  ["running", "queued", "cancelling"].includes(current.value?.status || ""),
);
const rendered = computed(() =>
  DOMPurify.sanitize(
    marked.parse(
      (state.value.report || "").replace(
        /\[(E-[a-zA-Z0-9-]+)\]/g,
        (_match: string, id: string) =>
          `<a href="#${id}" data-evidence="${id}" title="${id}">[证据 ${state.value.evidence?.findIndex((e: Data) => e.id === id) + 1 || id}]</a>`,
      ),
    ) as string,
    { FORBID_TAGS: ["img", "iframe", "video", "audio", "source", "style"] },
  ),
);
const totals = computed(
  () =>
    Object.values(state.value.usage || {}).reduce(
      (a: any, v: any) => ({
        calls: a.calls + v.calls,
        tokens: a.tokens + v.input_tokens + v.output_tokens,
      }),
      { calls: 0, tokens: 0 },
    ) as { calls: number; tokens: number },
);
async function api(path: string, options: RequestInit = {}) {
  const res = await fetch("/api" + path, {
    ...options,
    headers:
      options.body instanceof FormData
        ? options.headers
        : { "Content-Type": "application/json", ...options.headers },
  });
  const data = await res.json();
  if (!res.ok)
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : JSON.stringify(data.detail),
    );
  return data;
}
async function action(fn: () => Promise<void>) {
  error.value = "";
  busy.value = true;
  try {
    await fn();
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    busy.value = false;
  }
}
async function refreshList() {
  [tasks.value, sessions.value] = await Promise.all([api("/tasks"), api("/sessions")]);
}
async function refreshTask(id: string) {
  const value = await api("/tasks/" + id);
  if (current.value?.id === id) current.value = value;
}
async function selectTask(id: string) {
  sideExpanded.value = false;
  stream?.close();
  current.value = await api("/tasks/" + id);
  conversation.value = await api("/sessions/" + current.value!.session_id);
  sessionTitle.value = conversation.value!.title;
  events.value = [];
  tab.value = "report";
  selectedEvidence.value = "";
  hits.value = [];
  localStorage.setItem("litresearch-task", id);
  if (!settingsOpen.value) history.replaceState(null, "", "#task/" + id);
  const taskStream = new EventSource("/api/tasks/" + id + "/events");
  stream = taskStream;
  taskStream.addEventListener("progress", (e) => {
    if (current.value?.id !== id) return;
    const item = JSON.parse((e as MessageEvent).data);
    if (!events.value.some((x) => x.id === item.id)) events.value.push(item);
    if (item.kind === "usage" && current.value?.id === id)
      current.value.state.usage = item.detail;
    if (["checkpoint", "stage"].includes(item.kind))
      refreshTask(id).catch(() => {});
  });
  taskStream.addEventListener("done", () => {
    taskStream.close();
    if (current.value?.id !== id) return;
    refreshTask(id).catch(() => {});
    refreshList().catch(() => {});
    api('/sessions/' + current.value!.session_id).then(value => { if(current.value?.id === id) conversation.value = value; }).catch(() => {});
  });
  taskStream.onerror = () => {
    if (current.value?.id !== id) return;
    notice.value = "正在重新连接进度流；已保存的任务不受影响。";
  };
}
function newTask() {
  parentSession.value = "";
  conversation.value = null;
  history.replaceState(null, "", window.location.pathname);
  stream?.close();
  current.value = null;
  events.value = [];
  localStorage.removeItem("litresearch-task");
  error.value = "";
  notice.value = "";
}
async function start(demo = false) {
  await action(async () => {
    if (!topic.value.trim()) topic.value = demo ? "证据约束的文献调研方法" : "";
    if (!topic.value.trim()) throw new Error("请先输入研究主题");
    const result = await api("/tasks", {
      method: "POST",
      body: JSON.stringify({
        session_id: parentSession.value,
        topic: topic.value,
        focus: focus.value,
        mode: demo ? "demo" : mode.value,
        sources: sources.value,
        year_from: yearFrom.value,
        year_to: yearTo.value,
        max_papers: maxPapers.value,
        exclude: exclude.value
          .split(/[,，]/)
          .map((x) => x.trim())
          .filter(Boolean),
        fulltext_required: required.value,
        token_budget: tokenBudget.value,
        max_calls: callBudget.value,
        uploads: uploads.value.map((x) => x.id),
      }),
    });
    await refreshList();
    await selectTask(result.id);
  });
}
async function renameConversation() {
  await action(async () => {
    conversation.value = await api('/sessions/' + current.value!.session_id, {method:'PUT',body:JSON.stringify({title:sessionTitle.value})});
    await refreshList();
  });
}
function continueResearch() {
  const previous = current.value!;
  newTask();
  parentSession.value = previous.session_id;
  topic.value = previous.topic;
  focus.value = previous.request.focus;
  mode.value = previous.request.mode;
  yearFrom.value = previous.request.year_from;
  yearTo.value = previous.request.year_to;
  maxPapers.value = previous.request.max_papers;
  sources.value = [...previous.request.sources];
  required.value = previous.request.fulltext_required;
  tokenBudget.value = previous.request.token_budget;
  callBudget.value = previous.request.max_calls;
  exclude.value = previous.request.exclude.join(',');
  uploads.value = [];
}
async function chatCitation(value: {id:string; taskId:string}) {
  await action(async () => {
    if(current.value?.id !== value.taskId) await selectTask(value.taskId);
    viewEvidence(value.id);
  });
}
async function resume() {
  await action(async () => {
    const id = current.value!.id;
    await api("/tasks/" + id + "/resume", { method: "POST" });
    await selectTask(id);
    await refreshList();
  });
}
async function stop() {
  await action(async () => {
    await api("/tasks/" + current.value!.id + "/cancel", { method: "POST" });
    await refreshTask(current.value!.id);
  });
}
function openSettings() {
  window.location.hash = "settings";
  settingsOpen.value = true;
}
function closeSettings() {
  window.location.hash = current.value ? "task/" + current.value.id : "";
  settingsOpen.value = false;
}
function syncRoute() {
  settingsOpen.value = window.location.hash === "#settings";
  const id = window.location.hash.match(/^#task\/([a-f0-9]{32})$/)?.[1];
  if (id && current.value?.id !== id) action(() => selectTask(id));
}
async function uploadFiles(event: Event) {
  const input = event.target as HTMLInputElement;
  await action(async () => {
    for (const file of Array.from(input.files || [])) {
      const form = new FormData();
      form.append("file", file);
      uploads.value.push(await api("/uploads", { method: "POST", body: form }));
    }
  });
  input.value = "";
}
async function findEvidence() {
  await action(async () => {
    hits.value = await api(
      "/tasks/" +
        current.value!.id +
        "/evidence/search?q=" +
        encodeURIComponent(vectorQuery.value),
    );
  });
}
function viewEvidence(id: string) {
  tab.value = "evidence";
  selectedEvidence.value = id;
  setTimeout(
    () =>
      document
        .getElementById(id)
        ?.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? "instant" : "smooth", block: "center" }),
    360,
  );
}
function reportClick(event: MouseEvent) {
  const target = (event.target as HTMLElement).closest(
    "[data-evidence]",
  ) as HTMLElement | null;
  if (target?.dataset.evidence) {
    event.preventDefault();
    viewEvidence(target.dataset.evidence);
  }
}
function navigateArtifact(value: string | {target:string;paperId?:string;evidenceId?:string}) {
  const target = typeof value === 'string' ? value : value.target;
  if(typeof value !== 'string' && value.evidenceId) {viewEvidence(value.evidenceId);return;}
  tab.value = target === 'comparison' ? 'report' : target;
  setTimeout(() => {
    const node = typeof value !== 'string' && value.paperId ? document.getElementById('paper-'+value.paperId) : target === 'comparison' ? Array.from(document.querySelectorAll('.report h2')).find(e => e.textContent?.includes('文献比较')) : document.querySelector('.content-toolbar');
    node?.scrollIntoView({behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth',block:'start'});
  }, 360);
}
function safeUrl(url: string) {
  return /^https?:\/\//i.test(url) ? url : undefined;
}
onMounted(async () => {
  settingsOpen.value = window.location.hash === "#settings";
  window.addEventListener("hashchange", syncRoute);
  await action(async () => {
    await refreshList();
    const id =
      window.location.hash.match(/^#task\/([a-f0-9]{32})$/)?.[1] ||
      localStorage.getItem("litresearch-task");
    if (id) await selectTask(id);
  });
});
onUnmounted(() => {
  stream?.close();
  window.removeEventListener("hashchange", syncRoute);
});
</script>

<template>
  <Transition name="surface" mode="out-in">
  <Connections v-if="settingsOpen" @close="closeSettings" />
  <div v-else class="shell">
    <aside :class="['sidebar', { expanded: sideExpanded }]">
      <div class="brand">
        <div class="brand-mark"><BookOpen :size="24" /></div>
        <div><b>知序</b><span>RESEARCH WORKSPACE</span></div>
      </div>
      <button class="new-button" @click="newTask">
        <Plus :size="18" /> 新建会话 <span>↗</span>
      </button>
      <button
        class="mobile-history"
        aria-label="展开调研历史"
        @click="sideExpanded = !sideExpanded"
      >
        <Activity :size="18" />
      </button>
      <div class="side-caption">
        研究会话 <span>{{ sessions.length }}</span>
      </div>
      <label class="history-search"><Search :size="15"/><input v-model="historyQuery" aria-label="搜索历史会话" placeholder="搜索会话…"/></label>
      <nav class="history">
        <button
          v-for="task in filteredSessions"
          :key="task.id"
          :class="['history-item', { active: current?.session_id === task.id }]"
          @click="action(() => selectTask(task.latest_task_id))"
        >
          <FileText :size="16" />
          <div>
            <strong>{{ task.title }}</strong
            ><small
              >{{ task.task_count }} 个调研版本 ·
              {{
                new Date(task.updated).toLocaleDateString("zh-CN", {
                  month: "numeric",
                  day: "numeric",
                })
              }}</small
            >
          </div>
        </button>
        <p v-if="!filteredSessions.length" class="muted empty-history">
          你的研究，从一个问题开始。<br />会话与每次调研都会保存在这里。
        </p>
      </nav>
      <div class="sidebar-bottom">
        <div class="local-status">
          <span></span> 本地工作空间 <small>AGENT</small>
        </div>
        <button class="plain" @click="openSettings">
          <Settings2 :size="17" /> 连接中心
        </button>
      </div>
    </aside>
    <div
      v-if="sideExpanded"
      class="sidebar-scrim"
      @click="sideExpanded = false"
    ></div>
    <main>
      <header class="topbar">
        <span
          >工作空间 <ChevronRight :size="14" />
          {{ current ? "调研详情" : "新建调研" }}</span
        >
        <div>
          <span class="small-tag">证据可追溯</span
          ><button
            class="icon-button"
            title="模型设置"
            aria-label="模型设置"
            @click="openSettings"
          >
            <Settings2 :size="18" />
          </button>
        </div>
      </header>
      <div v-if="busy" class="ui-working" role="status"><LoaderCircle class="spin" :size="16"/>正在加载并保存工作区…</div>
      <div v-if="error" class="alert error" role="alert">
        {{ error }}<button aria-label="关闭错误" @click="error = ''">×</button>
      </div>
      <div v-if="notice" class="alert info" role="status">
        {{ notice
        }}<button aria-label="关闭提示" @click="notice = ''">×</button>
      </div>
      <section v-if="!current" class="welcome">
        <div v-if="parentSession" class="append-banner">追加到现有会话 · 本次将生成新版本，旧报告和过程会保留。</div>
        <div class="eyebrow">
          <span></span> 知序 RESEARCH AGENT · 你的文献研究空间
        </div>
        <h1>把一个研究问题，<br />变成一份<span>有依据的综述。</span></h1>
        <p class="lead">
          检索多源文献，逐层阅读与分析。让每一条结论，都能回到它的证据。
        </p>
        <div class="welcome-capabilities">
          <span><Search :size="16" /> 多源文献</span
          ><span><Layers :size="16" /> 五阶段协作</span
          ><span><Quote :size="16" /> 原文可追溯</span
          ><button @click="openSettings">
            <Settings2 :size="16" /> 配置 API <ArrowUpRight :size="14" />
          </button>
        </div>
        <form class="research-form" @submit.prevent="start(false)">
          <label class="field-title" for="topic">你想研究什么？</label
          ><textarea
            id="topic"
            v-model="topic"
            class="topic-input"
            placeholder="例如：检索增强生成中的事实一致性与幻觉评估"
            rows="2"
            required
            maxlength="500"
          ></textarea>
          <div class="focus-field">
            <label for="focus">重点关注 <small>选填</small></label
            ><input
              id="focus"
              v-model="focus"
              placeholder="方法差异、数据集、实验结果，或你想进一步了解的问题"
              maxlength="2000"
            />
          </div>
          <div class="form-divider"></div>
          <div class="form-row">
            <label
              >时间范围
              <div class="year-range">
                <input
                  aria-label="起始年份"
                  v-model.number="yearFrom"
                  type="number"
                  min="1900"
                  max="2100"
                /><span>—</span
                ><input
                  aria-label="结束年份"
                  v-model.number="yearTo"
                  type="number"
                  min="1900"
                  max="2100"
                /></div></label
            ><label
              >论文数量<select v-model.number="maxPapers">
                <option :value="3">3 篇 · 快速验证</option>
                <option :value="5">5 篇 · 标准调研</option>
                <option :value="10">10 篇 · 深入比较</option>
              </select></label
            ><label
              >运行方式<select v-model="mode">
                <option value="live">真实调研</option>
                <option value="demo">离线合成演示</option>
              </select></label
            >
          </div>
          <div class="source-row">
            <span>学术来源</span
            ><label
              v-for="(name, key) in {
                arxiv: 'arXiv',
                openalex: 'OpenAlex',
                semantic_scholar: 'Semantic Scholar',
              }"
              :key="key"
              ><input type="checkbox" :value="key" v-model="sources" />{{
                name
              }}</label
            >
          </div>
          <button
            type="button"
            class="text-button"
            @click="showAdvanced = !showAdvanced"
          >
            {{ showAdvanced ? "收起" : "展开" }}筛选与本地论文
            <ChevronRight :size="14" />
          </button>
          <div v-if="showAdvanced" class="advanced">
            <div class="settings-grid">
              <label
                >模型 token 预算（含输入与输出）<input
                  type="number"
                  min="1000"
                  max="1000000"
                  step="10000"
                  v-model.number="tokenBudget" /></label
              ><label
                >模型调用上限<input
                  type="number"
                  min="5"
                  max="200"
                  v-model.number="callBudget"
              /></label>
            </div>
            <label
              >排除词<input v-model="exclude" placeholder="用逗号分隔" /></label
            ><label class="check-label"
              ><input
                type="checkbox"
                v-model="required"
              />必须获取全文；失败时暂停，修复后恢复</label
            ><label class="upload-button"
              ><Upload :size="16" />上传固定论文 PDF<input
                type="file"
                accept="application/pdf"
                multiple
                @change="uploadFiles"
                hidden
            /></label>
            <p class="muted">
              上传后本任务仅分析固定论文，不执行在线检索。单份不超过 30 MB。
            </p>
            <div v-for="file in uploads" :key="file.id" class="upload-file">
              {{ file.name
              }}<button
                type="button"
                @click="uploads = uploads.filter((f) => f.id !== file.id)"
              >
                ×
              </button>
            </div>
          </div>
          <div class="form-footer">
            <span
              ><CircleDot :size="14" /> 原文证据 · 分阶段保存 · 实时进度</span
            ><button class="primary" :disabled="busy || !sources.length">
              <span>{{ busy ? "准备中…" : "开始调研" }}</span
              ><ArrowUpRight :size="18" />
            </button>
          </div>
        </form>
        <div class="quick-topics">
          <span>试试这些主题</span
          ><button
            @click="
              topic = 'Retrieval augmented generation factuality evaluation'
            "
          >
            RAG 事实一致性 ↗</button
          ><button @click="topic = 'Large language model agents tool use'">
            大模型工具调用 ↗</button
          ><button @click="topic = 'Graph neural networks survey'">
            图神经网络综述 ↗
          </button>
        </div>
        <div class="welcome-bottom">
          <div>
            <FlaskConical :size="22" />
            <div>
              <b>先了解完整流程</b>
              <p>无需 API，使用明确标注的合成材料体验工作台。</p>
            </div>
          </div>
          <button class="secondary" :disabled="busy" @click="start(true)">
            运行离线演示 <Play :size="14" />
          </button>
        </div>
        <p class="footnote">
          系统输出用于辅助调研。原文定位检查与模型审查通过后，仍需人工核验结论的语义支持。
        </p>
      </section>
      <section v-else class="detail">
        <div v-if="conversation" class="session-bar">
          <form @submit.prevent="renameConversation"><label for="session-title">会话名称</label><input id="session-title" v-model="sessionTitle" maxlength="160" required/><button class="icon-button" title="保存会话名称" aria-label="保存会话名称" :disabled="busy"><Check :size="16"/></button></form>
          <label class="version-picker">调研版本<select :value="current.id" @change="action(() => selectTask(($event.target as HTMLSelectElement).value))"><option v-for="(run,i) in conversation.tasks" :key="run.id" :value="run.id">版本 {{conversation.tasks.length-i}} · {{new Date(run.created).toLocaleDateString('zh-CN')}} · {{labels[run.status]}}</option></select></label>
          <button class="secondary" @click="continueResearch"><Plus :size="16"/>追加调研</button>
        </div>
        <div class="detail-heading">
          <div>
            <div class="eyebrow">
              {{
                current.request.mode === "demo"
                  ? "OFFLINE DEMO · 合成演示"
                  : "LITERATURE REVIEW · 文献调研"
              }}
            </div>
            <h2>{{ current.topic }}</h2>
            <p>
              {{ current.request.year_from }} — {{ current.request.year_to }}
              <span>·</span> 最多 {{ current.request.max_papers }} 篇
              <span>·</span>
              {{ new Date(current.created).toLocaleString("zh-CN") }}
            </p>
          </div>
          <span :class="['status-pill', current.status]"
            ><i></i>{{ labels[current.status] }}</span
          >
        </div>
        <div v-if="current.request.mode === 'demo'" class="demo-banner">
          <FlaskConical
            :size="17"
          />此任务使用合成材料与确定性输出，仅演示系统流程，不代表真实研究效果。
        </div>
        <p v-if="current.request.focus" class="research-focus">调研要求：{{current.request.focus}}</p>
        <div class="pipeline">
          <div
            v-for="(stage, i) in stages"
            :key="stage.id"
            :class="[
              'stage',
              {
                done: state.done?.includes(stage.id),
                current: current.stage === stage.id && working,
              },
            ]"
          >
            <div class="stage-icon">
              <Check
                v-if="state.done?.includes(stage.id)"
                :size="18"
              /><component v-else :is="stage.icon" :size="18" />
            </div>
            <div>
              <b>{{ stage.name }}</b
              ><small>{{
                state.done?.includes(stage.id)
                  ? "已完成"
                  : current.stage === stage.id && working
                    ? "处理中"
                    : "等待执行"
              }}</small>
            </div>
            <ChevronRight v-if="i < 4" class="stage-arrow" :size="14" />
          </div>
        </div>
        <div class="metrics">
          <div>
            <span>候选文献</span
            ><b>{{ state.papers?.length || 0 }}<small>篇</small></b>
          </div>
          <div>
            <span>已定位证据</span
            ><b>{{ state.evidence?.length || 0 }}<small>条</small></b>
          </div>
          <div>
            <span>模型用量</span
            ><b>{{ totals.tokens.toLocaleString() }}<small>tokens</small></b>
          </div>
          <div>
            <span>模型调用</span><b>{{ totals.calls }}<small>次</small></b>
          </div>
        </div>
        <div v-if="current.error" class="task-error">
          <b>任务需要处理</b>
          <p>{{ current.error }}</p>
          <span>已保存的阶段产物会保留。修复服务配置后，可从检查点继续。</span>
        </div>
        <div class="research-workspace"><div class="artifact-space">
        <div class="content-toolbar">
          <div class="tabs">
            <button
              v-for="item in [
                { id: 'report', name: '调研报告' },
                { id: 'papers', name: '文献库' },
                { id: 'evidence', name: '证据索引' },
                { id: 'process', name: '执行链路' },
              ]"
              :key="item.id"
              :class="{ active: tab === item.id }"
              @click="tab = item.id"
            >
              {{ item.name }}
            </button>
          </div>
          <div class="actions">
            <button
              v-if="working"
              class="secondary"
              @click="stop"
              :disabled="busy || current.status === 'cancelling'"
            >
              <Square :size="14" />停止</button
            ><button
              v-if="
                ['failed', 'interrupted', 'cancelled'].includes(current.status)
              "
              class="primary"
              @click="resume"
              :disabled="busy"
            >
              <RotateCcw :size="14" />恢复执行</button
            ><a
              v-if="current.status === 'completed'"
              class="secondary"
              :href="'/api/tasks/' + current.id + '/export/md'"
              ><Download :size="15" /> Markdown</a
            ><a
              v-if="current.status === 'completed'"
              class="icon-button"
              :href="'/api/tasks/' + current.id + '/export/json'"
              title="下载完整 JSON"
              >JSON</a
            >
            <a v-if="state.report" class="primary" :href="'/api/tasks/' + current.id + '/export/pdf'"><Download :size="15"/>下载论文 PDF</a>
            <a v-if="state.report" class="secondary" :href="'/api/tasks/' + current.id + '/export/html'">HTML</a>
          </div>
        </div>
        <Transition name="panel" mode="out-in"><div class="content-panel" :key="current.id + tab">
          <template v-if="tab === 'report'"
            ><article
              v-if="state.report"
              class="report"
              @click="reportClick"
              v-html="rendered"
            ></article>
            <div v-else-if="state.sections?.length" class="report">
              <div v-for="section in state.sections" :key="section.title">
                <h2>{{ section.title }}</h2>
                <p v-for="p in section.paragraphs">
                  {{ p.text }}
                  <button
                    class="citation"
                    v-for="id in p.evidence_ids"
                    @click="viewEvidence(id)"
                  >
                    {{ id }}
                  </button>
                </p>
              </div>
            </div>
            <div v-else class="empty-panel">
              <div class="empty-icon"><FileText :size="32" /></div>
              <h3>{{ working ? "正在为报告准备证据" : "报告尚未生成" }}</h3>
              <p>
                检索、阅读与分析产物会逐步保存。<br />你可以先查看文献库、证据索引和运行记录。
              </p>
              <button class="text-button" @click="tab = 'process'">
                查看当前进度 <ChevronRight :size="15" />
              </button>
            </div>
            <div v-if="state.outline && !state.report" class="outline-preview">
              <h3>章节大纲</h3>
              <div v-for="(s, i) in state.outline.sections">
                <span>0{{ Number(i) + 1 }}</span
                >{{ s.title }}<small>{{ s.evidence_ids.length }} 条证据</small>
              </div>
            </div></template
          >
          <template v-if="tab === 'papers'"
            ><div class="panel-title">
              <h3>本次调研文献</h3>
              <span>来源、阅读层级与覆盖情况</span>
            </div>
            <div
              v-for="(paper, i) in state.papers"
              :key="paper.id"
              :id="'paper-'+paper.id"
              class="paper-card"
            >
              <span class="paper-number">{{
                String(Number(i) + 1).padStart(2, "0")
              }}</span>
              <div>
                <div class="paper-tags">
                  <span>{{ paper.year || "年份未知" }}</span
                  ><span v-for="source in paper.sources">{{ source }}</span
                  ><span class="green">{{
                    levels[state.readings?.[paper.id]?.level] || "等待读取"
                  }}</span>
                </div>
                <h3>
                  <a
                    v-if="safeUrl(paper.url)"
                    :href="safeUrl(paper.url)"
                    target="_blank"
                    rel="noopener"
                    >{{ paper.title }} <ExternalLink :size="13" /></a
                  ><span v-else>{{ paper.title }}</span>
                </h3>
                <p class="authors">
                  {{ paper.authors?.join(" · ") || "作者信息未提供" }}
                </p>
                <p class="abstract">
                  {{ paper.abstract || "本地论文：请查看提取的证据与页码。" }}
                </p>
                <div class="paper-meta">
                  <a v-if="state.readings?.[paper.id]?.level === 'fulltext'" class="text-button" :href="'/api/tasks/' + current.id + '/papers/' + paper.id + '/pdf'" target="_blank" rel="noopener"><FileText :size="14"/> 查看原文 PDF</a>
                  <span>相关性启发式分数 {{ paper.score }}</span
                  ><span v-if="state.readings?.[paper.id]"
                    >分析
                    {{ state.readings[paper.id].analysed_blocks.length }} /
                    {{ state.readings[paper.id].blocks.length }} 块</span
                  >
                </div>
                <p
                  v-for="warning in state.readings?.[paper.id]?.warnings"
                  class="warning-text"
                >
                  {{ warning }}
                </p>
              </div>
            </div>
            <p v-if="!state.papers?.length" class="muted">
              尚未取得文献。
            </p></template
          >
          <template v-if="tab === 'evidence'"
            ><div class="panel-title">
              <h3>结论与原文之间的连接</h3>
              <span>{{
                state.vector_mode === "semantic"
                  ? "语义向量检索"
                  : "词项向量检索 · 非语义 Embedding"
              }}</span>
            </div>
            <form class="evidence-search" @submit.prevent="findEvidence">
              <Search :size="17" /><input
                aria-label="搜索原文证据"
                v-model="vectorQuery"
                placeholder="在已索引的论文片段中搜索…"
                required
              /><button class="secondary" :disabled="busy">检索片段</button>
            </form>
            <div v-for="hit in hits" class="hit">
              <small
                >{{ hit.paper_id }} ·
                {{ hit.page ? `第 ${hit.page} 页` : "摘要" }} ·
                {{ hit.block_id }}</small
              >
              <p>{{ hit.text }}</p>
            </div>
            <div
              v-for="e in state.evidence"
              :id="e.id"
              :key="e.id"
              :class="[
                'evidence-card',
                { selected: selectedEvidence === e.id },
              ]"
            >
              <div class="evidence-head">
                <span>{{ e.id }}</span
                ><small
                  >{{ e.dimension }} ·
                  {{ e.page ? `第 ${e.page} 页` : "摘要/示例段落" }}</small
                >
              </div>
              <h4>{{ e.claim }}</h4>
              <blockquote>{{ e.quote }}</blockquote>
              <footer>
                <Check :size="14" />原文片段匹配通过
                <span>语义支持待人工核验</span>
              </footer>
            </div>
            <p v-if="!state.evidence?.length" class="muted">
              证据抽取完成后将出现在这里。
            </p></template
          >
          <template v-if="tab === 'process'"
            ><ExecutionTrace :task="current" :events="events" @navigate="navigateArtifact"/><details class="raw-events"><summary>完整运行记录 · {{events.length}} 条事件</summary><div class="panel-title">
              <h3>可回放的调研过程</h3>
              <span>事件与阶段产物已保存在本机</span>
            </div>
            <div v-if="state.plan" class="plan-box">
              <b>检索计划</b>
              <p v-for="query in state.plan.queries">{{ query }}</p>
              <small>子主题：{{ state.plan.subtopics.join(" / ") }}</small>
              <div class="plan-dimensions"><span v-for="dimension in state.plan.dimensions" :key="dimension">{{dimension}}</span></div>
            </div>
            <div class="usage-table" v-if="totals.calls">
              <div v-for="(meter, stage) in state.usage">
                <b>{{
                  stages.find((s) => s.id === String(stage))?.name || stage
                }}</b
                ><span>{{ meter.calls }} 次调用</span
                ><span
                  >{{ meter.input_tokens }} 输入 /
                  {{ meter.output_tokens }} 输出 tokens</span
                ><span v-if="meter.unknown_usage_calls"
                  >{{ meter.unknown_usage_calls }} 次用量未返回</span
                >
              </div>
            </div>
            <div class="timeline">
              <div v-for="event in events" :key="event.id" class="event">
                <i :class="event.kind"></i
                ><time>{{
                  new Date(event.at).toLocaleTimeString("zh-CN")
                }}</time
                ><span>{{ event.message }}</span
                ><small>{{ event.stage }}</small>
                <details v-if="event.detail && Object.keys(event.detail).length" class="event-detail"><summary>查看阶段详情</summary><pre>{{JSON.stringify(event.detail,null,2)}}</pre></details>
              </div>
            </div></details></template
          >
        </div>
        </Transition></div><ChatPane :key="current.session_id" :session-id="current.session_id" :task-id="current.id" :demo="current.request.mode === 'demo'" @cite="chatCitation"/></div>
      </section>
    </main>
  </div>
  </Transition>
</template>
