<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { CircleAlert, CircleCheck, Eye, EyeOff, X } from 'lucide-vue-next'
import { useDialogFocus } from '../composables/useDialogFocus'
import type {
  ConnectionProfilePayload,
  ConnectionProfileSecrets,
  ConnectionProfileSummary,
  ProfileType
} from '../types'

const props = defineProps<{
  profileType: ProfileType
  profile?: ConnectionProfileSummary | null
  groups: string[]
  saving?: boolean
  returnFocus?: HTMLElement | null
}>()
const emit = defineEmits<{
  close: []
  save: [payload: ConnectionProfilePayload, connectAfterSave: boolean, secrets: ConnectionProfileSecrets]
}>()
const dialog = ref<HTMLElement | null>(null)
const { handleDialogKeydown } = useDialogFocus(dialog, {
  initialFocus: '[data-dialog-initial-focus]',
  restoreFocus: () => props.returnFocus || null
})

const form = reactive({
  name: '',
  group: '',
  notes: '',
  preferredProtocol: 'ssh' as 'ssh' | 'telnet' | 'serial',
  telnetHost: '',
  telnetPort: 23,
  telnetUsername: '',
  telnetSecret: '',
  sshHost: '',
  sshPort: 22,
  sshUsername: '',
  sshSecret: '',
  serialHost: '',
  serialPort: 23,
  serialUsername: '',
  serialSecret: ''
})
const passwordVisible = reactive({ telnet: true, ssh: true, serial: true })
const hasAnyEndpoint = computed(() => props.profileType === 'server'
  ? Boolean(form.sshHost.trim())
  : Boolean(form.sshHost.trim() || form.telnetHost.trim() || form.serialHost.trim())
)
const endpointUsernamesValid = computed(() =>
  (!form.sshHost.trim() || Boolean(form.sshUsername.trim()) || props.profileType === 'server') &&
  (!form.telnetHost.trim() || Boolean(form.telnetUsername.trim()))
)
const formReady = computed(() => Boolean(
  form.name.trim() && hasAnyEndpoint.value && endpointUsernamesValid.value
))
const formReadinessText = computed(() => {
  if (!form.name.trim()) return '请先填写连接名称'
  if (!hasAnyEndpoint.value) return props.profileType === 'server' ? '请填写 SSH 主机地址' : '请至少配置一个连接地址'
  if (!endpointUsernamesValid.value) return 'SSH 或 Telnet 配置主机地址后必须填写用户名'
  return props.profile ? '连接配置已具备保存条件' : '连接配置已具备保存和连接条件'
})

watch(
  () => props.profile,
  (profile) => {
    form.name = profile?.name || ''
    form.group = profile?.group || ''
    form.notes = profile?.notes || ''
    form.preferredProtocol = profile?.preferred_protocol || 'ssh'
    form.telnetHost = profile?.telnet.host || ''
    form.telnetPort = profile?.telnet.port || 23
    form.telnetUsername = profile?.telnet.username || ''
    form.telnetSecret = profile?.telnet.password || ''
    passwordVisible.telnet = true
    form.sshHost = profile?.ssh.host || ''
    form.sshPort = profile?.ssh.port || 22
    form.sshUsername = profile?.ssh.username || (props.profileType === 'server' ? 'root' : '')
    form.sshSecret = profile?.ssh.password || ''
    passwordVisible.ssh = true
    form.serialHost = profile?.serial.host || ''
    form.serialPort = profile?.serial.port || 23
    form.serialUsername = profile?.serial.username || ''
    form.serialSecret = profile?.serial.password || ''
    passwordVisible.serial = true
  },
  { immediate: true }
)

function togglePassword(protocol: keyof typeof passwordVisible): void {
  passwordVisible[protocol] = !passwordVisible[protocol]
}

function submit(connectAfterSave = false): void {
  const payload: ConnectionProfilePayload = {
    profile_type: props.profileType,
    name: form.name.trim(),
    group: props.profileType === 'server' ? form.group.trim() : '',
    notes: form.notes.trim(),
    preferred_protocol: props.profileType === 'server' ? 'ssh' : form.preferredProtocol,
    telnet: {
      host: props.profileType === 'temporary' ? form.telnetHost.trim() : '',
      port: form.telnetPort,
      username: form.telnetUsername.trim()
    },
    ssh: {
      host: form.sshHost.trim(),
      port: form.sshPort,
      username: form.sshUsername.trim()
    },
    serial: {
      host: props.profileType === 'temporary' ? form.serialHost.trim() : '',
      port: form.serialPort,
      username: form.serialUsername.trim()
    }
  }
  const secrets: ConnectionProfileSecrets = {
    ...(form.telnetHost.trim() ? { telnet: form.telnetSecret } : {}),
    ...(form.sshHost.trim() ? { ssh: form.sshSecret } : {}),
    ...(form.serialHost.trim() ? { serial: form.serialSecret } : {})
  }
  emit('save', payload, connectAfterSave, secrets)
}
</script>

<template>
  <div class="dialog-backdrop" role="presentation" @mousedown.self="emit('close')">
    <form ref="dialog" class="profile-dialog" :class="{ 'server-dialog': profileType === 'server', 'temporary-dialog': profileType === 'temporary' }" role="dialog" aria-modal="true" aria-labelledby="profile-dialog-title" tabindex="-1" @submit.prevent="submit(!profile)" @keydown="handleDialogKeydown" @keydown.esc.prevent="emit('close')">
      <header>
        <div>
          <p class="eyebrow">CONNECTION PROFILE</p>
          <h2 id="profile-dialog-title">{{ profile ? '编辑' : '新增' }}{{ profileType === 'server' ? '服务器' : '临时连接' }}</h2>
        </div>
        <button class="icon-button" type="button" title="关闭" @click="emit('close')">
          <X :size="16" />
        </button>
      </header>

      <div class="profile-form-body">
        <label class="form-field">
          <span>名称</span>
          <input v-model="form.name" required maxlength="160" data-dialog-initial-focus />
        </label>
        <label v-if="profileType === 'server'" class="form-field">
          <span>分组</span>
          <input v-model="form.group" maxlength="160" list="profile-groups" placeholder="选择或输入分组" />
          <datalist id="profile-groups">
            <option v-for="group in groups" :key="group" :value="group" />
          </datalist>
        </label>
        <label v-if="profileType === 'temporary'" class="form-field">
          <span>默认协议</span>
          <select v-model="form.preferredProtocol">
            <option value="ssh">SSH</option>
            <option value="telnet">Telnet</option>
            <option value="serial">串口</option>
          </select>
        </label>

        <fieldset v-if="profileType === 'temporary'" class="protocol-form">
          <legend>Telnet</legend>
          <label class="protocol-field protocol-host-field"><span>主机地址</span><input v-model="form.telnetHost" placeholder="例如 192.0.2.10" /></label>
          <label class="protocol-field protocol-port-field"><span>端口</span><input v-model.number="form.telnetPort" type="number" min="1" max="65535" aria-label="Telnet 端口" /></label>
          <div class="protocol-credentials">
            <label class="protocol-field protocol-user-field"><span>用户名</span><input v-model="form.telnetUsername" placeholder="输入 Telnet 用户名" :required="Boolean(form.telnetHost)" /></label>
            <label class="protocol-field protocol-secret-field"><span>密码（可选）</span><span class="protocol-secret-input"><input v-model="form.telnetSecret" data-testid="temporary-telnet-password" :type="passwordVisible.telnet ? 'text' : 'password'" maxlength="4096" autocomplete="new-password" :placeholder="profile?.telnet.has_password ? '留空保留原密码；输入新密码将替换' : '直接输入并随连接保存'" /><button class="icon-button" type="button" :title="passwordVisible.telnet ? '隐藏 Telnet 密码' : '显示 Telnet 密码'" :aria-label="passwordVisible.telnet ? '隐藏 Telnet 密码' : '显示 Telnet 密码'" :aria-pressed="passwordVisible.telnet" @click="togglePassword('telnet')"><EyeOff v-if="passwordVisible.telnet" :size="14" /><Eye v-else :size="14" /></button></span></label>
          </div>
        </fieldset>

        <fieldset class="protocol-form">
          <legend>SSH</legend>
          <label class="protocol-field protocol-host-field"><span>主机地址</span><input v-model="form.sshHost" placeholder="例如 192.0.2.10" :required="profileType === 'server'" /></label>
          <label class="protocol-field protocol-port-field"><span>端口</span><input v-model.number="form.sshPort" type="number" min="1" max="65535" aria-label="SSH 端口" /></label>
          <div class="protocol-credentials">
            <label class="protocol-field protocol-user-field"><span>用户名</span><input v-model="form.sshUsername" placeholder="输入 SSH 用户名" :required="profileType === 'temporary' && Boolean(form.sshHost)" /></label>
            <label class="protocol-field protocol-secret-field"><span>密码（可选）</span><span class="protocol-secret-input"><input v-model="form.sshSecret" data-testid="temporary-ssh-password" :type="passwordVisible.ssh ? 'text' : 'password'" maxlength="4096" autocomplete="new-password" :placeholder="profile?.ssh.has_password ? '留空保留原密码；输入新密码将替换' : '直接输入并随连接保存'" /><button class="icon-button" type="button" :title="passwordVisible.ssh ? '隐藏 SSH 密码' : '显示 SSH 密码'" :aria-label="passwordVisible.ssh ? '隐藏 SSH 密码' : '显示 SSH 密码'" :aria-pressed="passwordVisible.ssh" @click="togglePassword('ssh')"><EyeOff v-if="passwordVisible.ssh" :size="14" /><Eye v-else :size="14" /></button></span></label>
          </div>
        </fieldset>

        <fieldset v-if="profileType === 'temporary'" class="protocol-form">
          <legend>串口转 Telnet</legend>
          <label class="protocol-field protocol-host-field"><span>串口服务器地址</span><input v-model="form.serialHost" placeholder="例如 192.0.2.20" /></label>
          <label class="protocol-field protocol-port-field"><span>端口</span><input v-model.number="form.serialPort" type="number" min="1" max="65535" aria-label="串口端口" /></label>
          <div class="protocol-credentials">
            <label class="protocol-field protocol-user-field"><span>用户名（可选）</span><input v-model="form.serialUsername" placeholder="可留空" /></label>
            <label class="protocol-field protocol-secret-field"><span>密码（可选）</span><span class="protocol-secret-input"><input v-model="form.serialSecret" data-testid="temporary-serial-password" :type="passwordVisible.serial ? 'text' : 'password'" maxlength="4096" autocomplete="new-password" :placeholder="profile?.serial.has_password ? '留空保留原密码；输入新密码将替换' : '直接输入并随连接保存'" /><button class="icon-button" type="button" :title="passwordVisible.serial ? '隐藏串口密码' : '显示串口密码'" :aria-label="passwordVisible.serial ? '隐藏串口密码' : '显示串口密码'" :aria-pressed="passwordVisible.serial" @click="togglePassword('serial')"><EyeOff v-if="passwordVisible.serial" :size="14" /><Eye v-else :size="14" /></button></span></label>
          </div>
        </fieldset>

        <label class="form-field form-field-wide">
          <span>备注</span>
          <textarea v-model="form.notes" rows="3" maxlength="4000"></textarea>
        </label>
        <p class="secret-hint">{{ profileType === 'temporary' ? '密码与账号一起保存；可直接查看、修改或清空。密码仅写入系统凭据库，不写入 SQLite 或日志。' : '密码可直接查看和修改，仅写入系统凭据库，不写入 SQLite 或日志。' }}</p>
      </div>

      <footer>
        <p class="profile-readiness" :data-ready="formReady" role="status">
          <CircleCheck v-if="formReady" :size="14" aria-hidden="true" />
          <CircleAlert v-else :size="14" aria-hidden="true" />
          {{ formReadinessText }}
        </p>
        <button class="secondary-button" type="button" @click="emit('close')">取消</button>
        <button v-if="!profile" class="secondary-button" type="button" :disabled="saving || !formReady" @click="submit(false)">
          仅保存
        </button>
        <button class="primary-button" type="submit" :disabled="saving || !formReady">
          {{ saving ? '保存中…' : profile ? '保存' : '保存并连接' }}
        </button>
      </footer>
    </form>
  </div>
</template>
