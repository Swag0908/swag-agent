import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import test from 'node:test'
import vm from 'node:vm'

test('真实前端聊天模块支持 Python、Java SSE 格式和跨块 UTF-8', async () => {
  const source = await fs.readFile(new URL('../../swag_agent_web/src/api/chat.js', import.meta.url), 'utf8')
  const module = new vm.SourceTextModule(source)
  await module.link(async () => new vm.SyntheticModule(['authHeaders', 'clearAuth'], function () {
    this.setExport('authHeaders', () => ({}))
    this.setExport('clearAuth', () => {})
  }))
  await module.evaluate()
  for (const java of [false, true]) {
    const payload = java ? { type: 'content', data: { text: '迁移成功' } } : { text: '迁移成功' }
    const bytes = new TextEncoder().encode(`event: ready\ndata: {}\n\nevent: content\ndata: ${JSON.stringify(payload)}\n\nevent: done\ndata: {}`)
    globalThis.fetch = async () => new Response(new ReadableStream({ start(controller) {
      // 按字节拆块，覆盖 UTF-8 多字节字符和 SSE 分隔符跨块。
      for (const byte of bytes) controller.enqueue(Uint8Array.of(byte))
      controller.close()
    } }), { headers: { 'Content-Type': 'text/event-stream' } })
    const deltas = [], events = []
    await module.namespace.streamChat({ model: 1, message: 'test',
      onDelta: text => deltas.push(text), onEvent: (name, data) => events.push([name, data]) })
    assert.equal(deltas.join(''), '迁移成功')
    assert.deepEqual(events.map(([name]) => name), ['ready', 'content', 'done'])
    assert.equal(events[1][1].text, '迁移成功')
  }
})
