<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import {
  ArrowLeft,
  Check,
  KeyRound,
  Plus,
  ShieldCheck,
  Cpu,
  Database,
  Workflow,
  ArrowUpRight,
  LoaderCircle,
} from "lucide-vue-next";
type Data = Record<string, any>;
const emit = defineEmits(["close"]);
const config = ref<Data | null>(null),
  selected = ref(""),
  section = ref("model");
const pending = ref(false),
  error = ref(""),
  message = ref(""),
  dirty = ref(false);
const tested = ref<Record<string, string>>({});
const provider = computed(() => config.value?.providers[selected.value]);
const stages = [
  { id: "search", name: "文献检索" },
  { id: "read", name: "渐进阅读" },
  { id: "analyse", name: "综合分析" },
  { id: "outline", name: "章节大纲" },
  { id: "write", name: "证据写作" },
];
async function request(path: string, options: RequestInit = {}) {
  const response = await fetch("/api/settings" + path, {
    ...options,
    headers: { "Content-Type": "application/json" },
  });
  const result = await response.json();
  if (!response.ok)
    throw new Error(
      typeof result.detail === "string"
        ? result.detail
        : "配置格式不正确，请检查地址、模型名及数值范围。",
    );
  return result;
}
function changed() {
  dirty.value = true;
  message.value = "";
  tested.value = {};
}
function signature() {
  return JSON.stringify(config.value);
}
function add() {
  if (!config.value) return;
  const id = "provider-" + Date.now();
  config.value.providers[id] = {
    name: "新模型服务",
    backend: "openai_compat",
    base_url: "",
    api_key: "",
    model: "",
    json_mode: true,
    max_output_tokens: 8192,
    timeout: 120,
    thinking: "auto",
  };
  selected.value = id;
  changed();
}
function assignAll() {
  for (const stage of stages) config.value!.agents[stage.id] = selected.value;
  changed();
}
async function save(test = false) {
  if (!config.value || pending.value) return;
  pending.value = true;
  error.value = "";
  message.value = "";
  try {
    for (const p of Object.values(config.value.providers) as Data[]) {
      const url = new URL(p.base_url);
      if (!["http:", "https:"].includes(url.protocol))
        throw new Error("服务地址必须使用 http 或 https。");
      if (!p.model.trim()) throw new Error("请填写每个服务的模型名称。");
    }
    config.value = await request("", {
      method: "PUT",
      body: JSON.stringify(config.value),
    });
    dirty.value = false;
    message.value =
      "配置已保存到本机。可以返回聊天，让我继续进行真实测试与调优。";
    if (test) {
      const result = await request(
        "/test/" + encodeURIComponent(selected.value),
        { method: "POST" },
      );
      if (!result.ok) throw new Error("模型响应未通过结构化检查。");
      tested.value[selected.value] = signature();
      message.value =
        "连接成功，结构化输出检查通过。配置已保存，可以返回聊天继续测试。";
    }
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    pending.value = false;
  }
}
function close() {
  if (pending.value) return;
  if (dirty.value && !window.confirm("尚有未保存的配置，确定离开吗？")) return;
  emit("close");
}
function unload(e: BeforeUnloadEvent) {
  if (dirty.value) {
    e.preventDefault();
    e.returnValue = "";
  }
}
onMounted(async () => {
  window.addEventListener("beforeunload", unload);
  try {
    config.value = await request("");
    selected.value = Object.keys(config.value!.providers)[0];
  } catch (e) {
    error.value = (e as Error).message;
  }
});
onUnmounted(() => window.removeEventListener("beforeunload", unload));
</script>

<template>
  <div class="connection-page">
    <header class="connection-top">
      <button class="secondary" @click="close" :disabled="pending">
        <ArrowLeft :size="16" /> 返回工作台</button
      ><span><ShieldCheck :size="16" /> 本机配置 · 密钥不回显</span>
    </header>
    <section class="connection-hero">
      <div>
        <div class="eyebrow">WORKSPACE / CONNECTIONS</div>
        <h1>连接你的研究能力<span>。</span></h1>
        <p>配置模型与文献来源，让 Agent 从这里开始工作。</p>
      </div>
      <div class="connection-symbol"><KeyRound :size="32" /></div>
    </section>
    <div class="connection-steps">
      <span class="active"><b>01</b> 填写模型服务</span
      ><span><b>02</b> 保存与连接检查</span
      ><span><b>03</b> 真实调研与调优</span>
    </div>
    <div v-if="error" class="alert error" role="alert">{{ error }}</div>
    <p v-if="!config && !error" role="status">正在读取本机配置…</p>
    <div v-if="config" class="connection-layout">
      <nav class="connection-nav" aria-label="连接设置分类">
        <button
          :class="{ active: section === 'model' }"
          @click="section = 'model'"
        >
          <Cpu :size="18" /><span
            >模型服务<small>API 与生成模型</small></span
          ></button
        ><button
          :class="{ active: section === 'sources' }"
          @click="section = 'sources'"
        >
          <Database :size="18" /><span
            >文献与向量<small>检索源与 Embedding</small></span
          ></button
        ><button
          :class="{ active: section === 'agents' }"
          @click="section = 'agents'"
        >
          <Workflow :size="18" /><span
            >Agent 分配<small>阶段模型与回退</small></span
          >
        </button>
        <div class="connection-note">
          <ShieldCheck :size="20" /><b>你的密钥，留在本机</b>
          <p>
            本地数据库保存凭据，网页仅接收掩码。调用时，密钥发送给你配置的服务。不要在聊天中粘贴。
          </p>
        </div>
      </nav>
      <form
        class="connection-card"
        @submit.prevent="save(false)"
        @input="changed"
        @change="changed"
      >
        <fieldset :disabled="pending">
          <template v-if="section === 'model'">
            <div class="connection-card-title">
              <div>
                <h2>模型服务</h2>
                <p>支持 DeepSeek 及 OpenAI / Anthropic 兼容接口。</p>
              </div>
              <button type="button" class="secondary" @click="add">
                <Plus :size="16" /> 添加
              </button>
            </div>
            <div class="provider-tabs">
              <button
                type="button"
                v-for="(p, id) in config.providers"
                :key="id"
                :class="{ active: selected === String(id) }"
                @click="selected = String(id)"
              >
                {{ p.name }}
              </button>
            </div>
            <div v-if="provider" class="connection-fields">
              <div class="connection-status">
                <span
                  ><i></i
                  >{{
                    tested[selected] === signature()
                      ? "本次连接检查已通过"
                      : provider.api_key
                        ? "已填写凭据 · 本次尚未验证"
                        : "等待填写 API Key"
                  }}</span
                ><small>保存不会自动启动调研</small>
              </div>
              <div class="settings-grid">
                <label
                  >服务名称<input
                    v-model="provider.name"
                    required
                    maxlength="80"
                    placeholder="例如：DeepSeek" /></label
                ><label
                  >接口协议<select v-model="provider.backend">
                    <option value="openai_compat">
                      OpenAI 兼容（DeepSeek 等）
                    </option>
                    <option value="openai">OpenAI</option>
                    <option value="anthropic">Anthropic</option>
                    <option value="anthropic_compat">Anthropic 兼容</option>
                  </select></label
                ><label class="full"
                  >API Base URL<input
                    v-model="provider.base_url"
                    type="url"
                    required
                    placeholder="https://api.deepseek.com"
                  /><small
                    >填写服务根地址，不包含 /chat/completions。</small
                  ></label
                ><label class="full"
                  >API Key<input
                    v-model="provider.api_key"
                    type="password"
                    autocomplete="new-password"
                    spellcheck="false"
                    placeholder="在这里粘贴密钥，仅保存到本机"
                  /><small
                    >星号表示已保存，保留即可；清空后保存会移除密钥。修改服务地址时需重新输入。</small
                  ></label
                ><label class="full"
                  >模型名称<input
                    v-model="provider.model"
                    required
                    placeholder="填写服务商提供的模型 ID"
                  /><small
                    >模型名称需要与你的 API 账户可用模型一致。</small
                  ></label
                >
              </div>
              <details class="connection-advanced">
                <summary>高级参数</summary>
                <div class="settings-grid">
                  <label
                    >最大输出 tokens<input
                      type="number"
                      v-model.number="provider.max_output_tokens"
                      min="256"
                      max="16384"
                      required /></label
                  ><label
                    >请求超时（秒）<input
                      type="number"
                      v-model.number="provider.timeout"
                      min="5"
                      max="180"
                      required /></label
                  ><label
                    >思考模式<select v-model="provider.thinking">
                      <option value="auto">服务默认</option>
                      <option value="disabled">关闭</option>
                      <option value="enabled">开启（需服务支持）</option>
                    </select></label
                  ><label class="check-label"
                    ><input type="checkbox" v-model="provider.json_mode" /> JSON
                    输出模式</label
                  >
                </div>
              </details>
              <button class="text-button" type="button" @click="assignAll">
                将此服务用于全部五个 Agent <ArrowUpRight :size="15" />
              </button>
            </div>
          </template>
          <template v-if="section === 'sources'"
            ><div class="connection-card-title">
              <div>
                <h2>文献来源与向量检索</h2>
                <p>先连接生成模型；以下服务可以随后补充。</p>
              </div>
            </div>
            <div class="source-service">
              <b>arXiv</b><span class="small-tag">无需 API Key</span>
              <p>可直接检索公开论文；可用性受网络及来源限流影响。</p>
            </div>
            <div class="settings-grid">
              <label class="full"
                >OpenAlex API Key<input
                  type="password"
                  v-model="config.openalex_key"
                  autocomplete="new-password"
                  placeholder="选填：扩展文献覆盖" /></label
              ><label class="full"
                >Semantic Scholar API Key<input
                  type="password"
                  v-model="config.semantic_scholar_key"
                  autocomplete="new-password"
                  placeholder="选填：扩展文献覆盖" /></label
              ><label
                >向量服务<select v-model="config.embedding_provider">
                  <option value="">本地词项向量 · 免 API</option>
                  <option v-for="(p, id) in config.providers" :value="id">
                    {{ p.name }}
                  </option>
                </select></label
              ><label
                >Embedding 模型<input
                  v-model="config.embedding_model"
                  placeholder="语义向量模式下填写"
              /></label>
            </div>
            <p class="connection-help">
              本地词项向量可直接运行。语义向量需要独立支持 Embedding
              的服务，不能直接使用 DeepSeek 生成模型替代。
            </p></template
          >
          <template v-if="section === 'agents'"
            ><div class="connection-card-title">
              <div>
                <h2>五个阶段，有序协作</h2>
                <p>可共用一个模型，也可以为不同阶段分配服务。</p>
              </div>
            </div>
            <div
              class="assignment"
              v-for="(stage, i) in stages"
              :key="stage.id"
            >
              <div>
                <span>0{{ i + 1 }}</span
                ><b>{{ stage.name }}</b>
              </div>
              <label
                >主模型<select v-model="config.agents[stage.id]">
                  <option v-for="(p, id) in config.providers" :value="id">
                    {{ p.name }}
                  </option>
                </select></label
              ><label
                >回退模型<select
                  :value="config.fallbacks[stage.id] || ''"
                  @change="
                    ($event.target as HTMLSelectElement).value
                      ? (config.fallbacks[stage.id] = (
                          $event.target as HTMLSelectElement
                        ).value)
                      : delete config.fallbacks[stage.id]
                  "
                >
                  <option value="">不回退</option>
                  <option v-for="(p, id) in config.providers" :value="id">
                    {{ p.name }}
                  </option>
                </select></label
              >
            </div></template
          >
        </fieldset>
        <p v-if="message" class="connection-success" role="status">
          <Check :size="18" />{{ message }}
        </p>
        <footer class="connection-footer">
          <span
            >{{ dirty ? "有未保存的更改" : "配置保存在当前电脑"
            }}<small v-if="section === 'model'"
              >连接检查会发起一次小规模模型请求。</small
            ></span
          >
          <div>
            <button
              v-if="section === 'model'"
              class="secondary"
              type="button"
              @click="save(true)"
              :disabled="pending"
            >
              保存并测试连接</button
            ><button class="primary" type="submit" :disabled="pending">
              <LoaderCircle v-if="pending" class="spin" :size="16" /><Check
                v-else
                :size="16"
              />{{ pending ? "处理中…" : "保存配置" }}
            </button>
          </div>
        </footer>
      </form>
    </div>
  </div>
</template>
