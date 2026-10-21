import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { createServer } from 'node:net';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const windows = process.platform === 'win32';
const children = [];
let shuttingDown = false;

function checkPort(port) {
  return new Promise((resolve, reject) => {
    const server = createServer();
    server.once('error', (error) => {
      reject(new Error(error.code === 'EADDRINUSE'
        ? `端口 ${port} 已被占用。请先在原来的启动终端按 Ctrl+C 停止服务，再运行 pnpm dev；已有服务也可以直接访问。`
        : `无法使用端口 ${port}：${error.message}`));
    });
    server.listen({ host: '127.0.0.1', port, exclusive: true }, () => server.close(resolve));
  });
}

async function stopTree(child) {
  if (!child.pid) return;
  if (windows) {
    // Only terminate a process tree created by this launcher. Killing a shell
    // alone leaves Vite and Uvicorn's reload worker running on Windows.
    await new Promise((resolve) => {
      const killer = spawn('taskkill.exe', ['/PID', String(child.pid), '/T', '/F'], {
        windowsHide: true, stdio: 'ignore',
      });
      killer.once('error', (error) => {
        console.error(`停止进程 ${child.pid} 失败：${error.message}`);
        resolve();
      });
      killer.once('exit', (code) => {
        if (code !== 0 && child.exitCode === null && child.signalCode === null) {
          console.error(`停止进程 ${child.pid} 失败，请在终端检查该项目进程。`);
        }
        resolve();
      });
    });
    return;
  }
  try { process.kill(-child.pid, 'SIGTERM'); } catch (error) {
    if (error.code !== 'ESRCH') console.error(error.message);
  }
  await new Promise((resolve) => {
    const timer = setTimeout(resolve, 1500);
    if (child.exitCode !== null || child.signalCode !== null) {
      clearTimeout(timer);
      resolve();
    } else child.once('exit', () => { clearTimeout(timer); resolve(); });
  });
  try { process.kill(-child.pid, 'SIGKILL'); } catch (error) {
    if (error.code !== 'ESRCH') console.error(error.message);
  }
}

async function stopChildren(exitCode = 0) {
  if (shuttingDown) return;
  shuttingDown = true;
  await Promise.all(children.map(stopTree));
  process.exit(exitCode);
}

function start(name, command, args, cwd = root) {
  const child = spawn(command, args, {
    cwd, stdio: 'inherit', shell: false, detached: true, windowsHide: true,
  });
  children.push(child);
  child.once('error', (error) => {
    console.error(`${name}启动失败：${error.message}`);
    void stopChildren(1);
  });
  child.once('exit', (code, signal) => {
    if (shuttingDown) return;
    console.error(`${name}已退出（${signal ?? code}），正在停止其余服务。`);
    void stopChildren(code === 0 ? 0 : 1);
  });
}

process.on('SIGINT', () => { void stopChildren(0); });
process.on('SIGTERM', () => { void stopChildren(0); });
process.on('SIGHUP', () => { void stopChildren(0); });

try {
  const vite = join(root, 'frontend', 'node_modules', 'vite', 'bin', 'vite.js');
  if (!existsSync(vite)) throw new Error('缺少前端依赖，请先在已激活的 Conda 环境中运行 pnpm run deps:install。');
  // Check both ports before starting either service, so a failed second launch
  // does not create another backend reloader.
  await checkPort(5173);
  await checkPort(8000);
  if (!shuttingDown) {
    const python = process.env.CONDA_PREFIX
      ? join(process.env.CONDA_PREFIX, windows ? 'python.exe' : 'bin/python')
      : 'python';
    console.log('启动前后端；按 Ctrl+C 同时停止。');
    start('后端', python, ['-m', 'uvicorn', 'app.main:app', '--reload', '--no-proxy-headers', '--host', '127.0.0.1', '--app-dir', 'backend', '--port', '8000']);
    start('前端', process.execPath, [vite], join(root, 'frontend'));
  }
} catch (error) {
  console.error(error.message);
  await stopChildren(1);
}
