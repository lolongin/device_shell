<script setup lang="ts">
import { ref } from 'vue'
import WorkflowCanvasPOC from '../components/WorkflowCanvasPOC.vue'

// 测试数据
const testWorkflow = ref({
  id: 'poc-test',
  name: 'Vue Flow POC 测试',
  nodes: [
    {
      id: 'start',
      action_id: 'device.connect',
      config: {},
      position: { x: 100, y: 50 }
    },
    {
      id: 'check',
      action_id: 'device.command',
      config: { command: 'display version' },
      position: { x: 100, y: 200 }
    },
    {
      id: 'condition',
      action_id: 'utility.condition',
      config: { expression: '${check.version} < "8.200"' },
      position: { x: 100, y: 350 }
    },
    {
      id: 'upgrade',
      action_id: 'file.upload',
      config: { local_path: 'firmware.bin' },
      position: { x: 300, y: 500 }
    },
    {
      id: 'skip',
      action_id: 'utility.wait',
      config: { seconds: 1 },
      position: { x: -100, y: 500 }
    }
  ],
  edges: [
    { source: 'start', target: 'check' },
    { source: 'check', target: 'condition' },
    { source: 'condition', target: 'upgrade', condition: 'true' },
    { source: 'condition', target: 'skip', condition: 'false' }
  ]
})

const selectedNodeId = ref<string | null>(null)
const log = ref<string[]>([])

function handleNodeSelect(nodeId: string) {
  selectedNodeId.value = nodeId
  addLog(`节点选中: ${nodeId}`)
}

function handleConnect(connection: { source: string; target: string }) {
  testWorkflow.value.edges?.push(connection)
  addLog(`连接: ${connection.source} → ${connection.target}`)
}

function handleNodePositionChange(nodeId: string, position: { x: number; y: number }) {
  const node = testWorkflow.value.nodes?.find(n => n.id === nodeId)
  if (node) {
    node.position = position
    addLog(`节点移动: ${nodeId} 到 (${Math.round(position.x)}, ${Math.round(position.y)})`)
  }
}

function handleNodeAdd(position: { x: number; y: number }) {
  const newId = `node-${Date.now()}`
  testWorkflow.value.nodes?.push({
    id: newId,
    action_id: 'device.command',
    config: { command: 'test' },
    position
  })
  addLog(`节点添加: ${newId}`)
}

function addLog(message: string) {
  log.value.unshift(`[${new Date().toLocaleTimeString()}] ${message}`)
  if (log.value.length > 10) log.value.pop()
}

function resetTest() {
  testWorkflow.value.nodes?.forEach((node, index) => {
    node.position = { x: 100, y: index * 150 + 50 }
  })
  addLog('重置节点位置')
}
</script>

<template>
  <div class="poc-test-page">
    <div class="poc-header">
      <h1>🚀 Vue Flow POC 验证</h1>
      <div class="poc-status">
        <span class="status-indicator">●</span>
        <span>Vue Flow 集成测试</span>
      </div>
    </div>

    <div class="poc-content">
      <!-- 左侧：画布 -->
      <div class="poc-canvas-area">
        <WorkflowCanvasPOC
          :workflow="testWorkflow"
          @node-select="handleNodeSelect"
          @connect="handleConnect"
          @node-position-change="handleNodePositionChange"
          @node-add="handleNodeAdd"
        />
      </div>

      <!-- 右侧：信息面板 -->
      <div class="poc-sidebar">
        <div class="info-section">
          <h3>测试说明</h3>
          <ul>
            <li>✅ 拖拽节点改变位置</li>
            <li>✅ 点击节点选中</li>
            <li>✅ 拖拽连接创建边</li>
            <li>✅ 使用控制按钮缩放</li>
            <li>✅ 查看缩略图导航</li>
          </ul>
        </div>

        <div class="info-section">
          <h3>当前状态</h3>
          <p><strong>节点数:</strong> {{ testWorkflow.nodes?.length }}</p>
          <p><strong>边数:</strong> {{ testWorkflow.edges?.length }}</p>
          <p><strong>选中节点:</strong> {{ selectedNodeId || '无' }}</p>
        </div>

        <div class="info-section">
          <h3>操作日志</h3>
          <div class="log-container">
            <div v-for="(entry, index) in log" :key="index" class="log-entry">
              {{ entry }}
            </div>
            <div v-if="log.length === 0" class="log-empty">
              等待操作...
            </div>
          </div>
        </div>

        <div class="info-section">
          <button @click="resetTest" class="action-button">
            重置位置
          </button>
        </div>

        <div class="info-section success-box">
          <h3>✅ POC 验证结果</h3>
          <p>如果您能看到上面的流程图并且可以：</p>
          <ul>
            <li>✓ 拖拽节点</li>
            <li>✓ 连接节点</li>
            <li>✓ 缩放画布</li>
          </ul>
          <p><strong>则 Vue Flow 集成成功！</strong></p>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.poc-test-page {
  width: 100%;
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: #0f172a;
  color: #e2e8f0;
  overflow: hidden;
}

.poc-header {
  padding: 16px 24px;
  background: #1e293b;
  border-bottom: 1px solid #334155;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.poc-header h1 {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
  color: #3b82f6;
}

.poc-status {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  color: #94a3b8;
}

.status-indicator {
  color: #22c55e;
  font-size: 18px;
  animation: pulse 2s infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

.poc-content {
  flex: 1;
  display: flex;
  min-height: 0;
}

.poc-canvas-area {
  flex: 1;
  min-width: 0;
  position: relative;
}

.poc-sidebar {
  width: 320px;
  background: #1e293b;
  border-left: 1px solid #334155;
  padding: 20px;
  overflow-y: auto;
}

.info-section {
  margin-bottom: 24px;
  padding-bottom: 24px;
  border-bottom: 1px solid #334155;
}

.info-section:last-child {
  border-bottom: none;
}

.info-section h3 {
  margin: 0 0 12px;
  font-size: 14px;
  font-weight: 600;
  color: #cbd5e1;
}

.info-section p {
  margin: 8px 0;
  font-size: 13px;
  color: #94a3b8;
}

.info-section ul {
  margin: 8px 0;
  padding-left: 20px;
  font-size: 13px;
  color: #94a3b8;
}

.info-section li {
  margin: 4px 0;
}

.log-container {
  background: #0f172a;
  border: 1px solid #334155;
  border-radius: 4px;
  padding: 8px;
  max-height: 200px;
  overflow-y: auto;
  font-family: monospace;
  font-size: 11px;
}

.log-entry {
  padding: 4px 0;
  color: #94a3b8;
  border-bottom: 1px solid #1e293b;
}

.log-entry:last-child {
  border-bottom: none;
}

.log-empty {
  color: #475569;
  text-align: center;
  padding: 12px 0;
}

.action-button {
  width: 100%;
  padding: 10px;
  background: #3b82f6;
  border: none;
  border-radius: 6px;
  color: white;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.2s;
}

.action-button:hover {
  background: #2563eb;
}

.success-box {
  background: rgba(34, 197, 94, 0.1);
  border: 1px solid rgba(34, 197, 94, 0.3);
  border-radius: 8px;
  padding: 16px;
}

.success-box h3 {
  color: #22c55e;
  margin-bottom: 12px;
}

.success-box p {
  color: #cbd5e1;
  margin: 8px 0;
}

.success-box ul {
  color: #cbd5e1;
}
</style>
