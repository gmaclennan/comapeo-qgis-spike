// Usage: node run.js <client command> [args...]
// Starts server.js, waits for READY, runs the client command with
// SPIKE_PATH / SPIKE_NAME in its environment, then stops the server.
import { spawn } from 'node:child_process'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const clientCmd = process.argv.slice(2)
if (clientCmd.length === 0) {
  console.error('usage: node run.js <client command> [args...]')
  process.exit(2)
}

const name = `spike-${process.pid}`
const socketPath =
  process.platform === 'win32'
    ? `\\\\.\\pipe\\${name}`
    : path.join(process.env.SPIKE_SOCKET_DIR || os.tmpdir(), name)
console.log(
  `[run] socket path: ${socketPath} (${Buffer.byteLength(socketPath)} bytes)`
)

const serverJs = fileURLToPath(new URL('./server.js', import.meta.url))
const server = spawn(process.execPath, [serverJs, socketPath], {
  stdio: ['ignore', 'pipe', 'inherit'],
})

let exiting = false
/** @param {number} code */
function finish(code) {
  if (exiting) return
  exiting = true
  server.kill()
  process.exit(code)
}

const readyTimeout = setTimeout(() => {
  console.error('[run] server did not print READY within 10s')
  finish(1)
}, 10_000)

let started = false
let out = ''
server.stdout.on('data', (chunk) => {
  process.stdout.write(`[server] ${chunk}`)
  if (started) return
  out += chunk
  if (!/^READY /m.test(out)) return
  started = true
  clearTimeout(readyTimeout)
  const client = spawn(clientCmd[0], clientCmd.slice(1), {
    stdio: 'inherit',
    env: { ...process.env, SPIKE_PATH: socketPath, SPIKE_NAME: name },
  })
  client.on('error', (err) => {
    console.error('[run] failed to start client:', err)
    finish(1)
  })
  client.on('exit', (code, signal) => {
    console.log(`[run] client exited code=${code} signal=${signal}`)
    finish(code ?? 1)
  })
})

server.on('exit', (code) => {
  if (!exiting) {
    console.error(`[run] server exited early with code ${code}`)
    finish(1)
  }
})
