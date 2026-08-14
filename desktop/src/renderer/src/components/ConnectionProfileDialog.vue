<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { CircleAlert, CircleCheck, X } from 'lucide-vue-next'
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
    form.telnetSecret = ''
    form.sshHost = profile?.ssh.host || ''
    form.sshPort = profile?.ssh.port || 22
    form.sshUsername = profile?.ssh.username || (props.profileType === 'server' ? 'root' : '')
    form.sshSecret = ''
    form.serialHost = profile?.serial.host || ''
    form.serialPort = profile?.serial.port || 23
    form.serialUsername = profile?.serial.username || ''
    form.serialSecret = ''
  },
  { immediate: true }
)

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
  const secrets: ConnectionProfileSecrets = props.profileType === 'temporary' && !props.profile
    ? {
        telnet: form.telnetHost.trim() ? form.telnetSecret : '',
        ssh: form.sshHost.trim() ? form.sshSecret : '',
        serial: form.serialHost.trim() ? form.serialSecret : ''
      }
    : {}
  emit('save', payload, connectAfterSave, secrets)
}
</script>

<template>
  <div class="dialog-backdrop" role="presentation" @mousedown.self="emit('close')">
    <form ref="dialog" class="profile-dialog" :class="{ 'server-dialog': profileType === 'server' }" role="dialog" aria-modal="true" aria-labelledby="profile-dialog-title" tabindex="-1" @submit.prevent="submit(!profile)" @keydown="handleDialogKeydown" @keydown.esc.prevent="emit('close')">
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
          <input v-model.number="form.telnetPort" type="number" min="1" max="65535" aria-label="Telnet 端口" />
          <label class="protocol-field protocol-user-field"><span>用户名</span><input v-model="form.telnetUsername" placeholder="输入 Telnet 用户名" :required="Boolean(form.telnetHost)" /></label>
          <label v-if="!profile" class="protocol-field protocol-secret-field"><span>密码（可选）</span><input v-model="form.telnetSecret" data-testid="temporary-telnet-password" type="password" maxlength="4096" autocomplete="new-password" placeholder="直接输入，保存后不再弹窗" /></label>
          <p v-else class="protocol-secret-state">凭据：{{ profile.telnet.has_password ? '已存于系统凭据库' : '未保存，可在详情中设置' }}</p>
        </fieldset>

        <fieldset class="protocol-form">
          <legend>SSH</legend>
          <label class="protocol-field protocol-host-field"><span>主机地址</span><input v-model="form.sshHost" placeholder="例如 192.0.2.10" :required="profileType === 'server'" /></label>
          <input v-model.number="form.sshPort" type="number" min="1" max="65535" aria-label="SSH 端口" />
          <label class="protocol-field protocol-user-field"><span>用户名</span><input v-model="form.sshUsername" placeholder="输入 SSH 用户名" :required="profileType === 'temporary' && Boolean(form.sshHost)" /></label>
          <label v-if="!profile && profileType === 'temporary'" class="protocol-field protocol-secret-field"><span>密码（可选）</span><input v-model="form.sshSecret" data-testid="temporary-ssh-password" type="password" maxlength="4096" autocomplete="new-password" placeholder="直接输入，保存后不再弹窗" /></label>
          <p v-else class="protocol-secret-state">凭据：{{ profile?.ssh.has_password ? '已存于系统凭据库' : '未保存，可在详情中设置' }}</p>
        </fieldset>

        <fieldset v-if="profileType === 'temporary'" class="protocol-form">
          <legend>串口转 Telnet</legend>
          <label class="protocol-field protocol-host-field"><span>串口服务器地址</span><input v-model="form.serialHost" placeholder="例如 192.0.2.20" /></label>
          <input v-model.number="form.serialPort" type="number" min="1" max="65535" aria-label="串口端口" />
          <label class="protocol-field protocol-user-field"><span>用户名（可选）</span><input v-model="form.serialUsername" placeholder="可留空" /></label>
          <label v-if="!profile" class="protocol-field protocol-secret-field"><span>密码（可选）</span><input v-model="form.serialSecret" data-testid="temporary-serial-password" type="password" maxlength="4096" autocomplete="new-password" placeholder="直接输入，保存后不再弹窗" /></label>
          <p v-else class="protocol-secret-state">凭据：{{ profile.serial.has_password ? '已存于系统凭据库' : '未保存，可在详情中设置' }}</p>
        </fieldset>

        <label class="form-field form-field-wide">
          <span>备注</span>
          <textarea v-model="form.notes" rows="3" maxlength="4000"></textarea>
        </label>
        <p class="secret-hint">{{ !profile && profileType === 'temporary' ? '新建时填写的密码会直接写入操作系统凭据库，保存完成后表单立即销毁；密码不会写入 SQLite 或日志。' : '已保存密码不会回显；需要更换或删除时，请通过详情面板管理系统凭据。' }}</p>
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
