// Usage: node server.js <pipe path | unix socket path>
// Frames: 4-byte unsigned little-endian length + UTF-8 JSON.
import net from 'node:net'
import fs from 'node:fs'

const socketPath = process.argv[2]
if (!socketPath) {
  console.error('usage: node server.js <path>')
  process.exit(2)
}
const isWindows = process.platform === 'win32'

/** @param {unknown} msg */
function encodeFrame(msg) {
  const body = Buffer.from(JSON.stringify(msg), 'utf8')
  const header = Buffer.alloc(4)
  header.writeUInt32LE(body.length, 0)
  return Buffer.concat([header, body])
}

const server = net.createServer((socket) => {
  let buffered = Buffer.alloc(0)
  /** @type {Set<NodeJS.Timeout>} */
  const timers = new Set()
  console.log('client connected')

  /** @param {unknown} msg */
  const send = (msg) => {
    if (!socket.destroyed) socket.write(encodeFrame(msg))
  }

  /** @param {any} msg */
  const onMessage = (msg) => {
    send({ echo: msg })
    if (msg && msg.subscribe === true) {
      const delayMs = typeof msg.delayMs === 'number' ? msg.delayMs : 500
      for (let n = 1; n <= 3; n++) {
        const t = setTimeout(
          () => {
            timers.delete(t)
            send({ event: n })
          },
          delayMs + (n - 1) * 200
        )
        timers.add(t)
      }
    }
    if (msg && msg.bye === true) socket.end()
  }

  socket.on('data', (chunk) => {
    buffered = buffered.length ? Buffer.concat([buffered, chunk]) : chunk
    while (buffered.length >= 4) {
      const len = buffered.readUInt32LE(0)
      if (buffered.length < 4 + len) break
      const body = buffered.subarray(4, 4 + len)
      buffered = buffered.subarray(4 + len)
      onMessage(JSON.parse(body.toString('utf8')))
    }
  })
  socket.on('error', (err) => console.log('client socket error:', err.message))
  socket.on('close', () => {
    for (const t of timers) clearTimeout(t)
    console.log('client disconnected')
  })
})

if (!isWindows) {
  try {
    fs.unlinkSync(socketPath)
  } catch (err) {
    if (/** @type {NodeJS.ErrnoException} */ (err).code !== 'ENOENT') throw err
  }
}

server.on('error', (err) => {
  console.error('server error:', err)
  process.exit(1)
})

server.listen(socketPath, () => {
  let mode = 'n/a'
  if (!isWindows) {
    const before = (fs.statSync(socketPath).mode & 0o777).toString(8)
    fs.chmodSync(socketPath, 0o600)
    const after = (fs.statSync(socketPath).mode & 0o777).toString(8)
    mode = `${before}->${after}`
  }
  console.log(`READY path=${socketPath} mode=${mode} node=${process.version}`)
})

for (const sig of ['SIGINT', 'SIGTERM']) {
  process.on(sig, () => {
    server.close()
    if (!isWindows) fs.rmSync(socketPath, { force: true })
    process.exit(0)
  })
}
