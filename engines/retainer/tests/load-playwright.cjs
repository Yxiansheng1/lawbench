'use strict';
/*
 * 统一加载 Playwright，便于在不同机器上运行测试。
 *
 * 查找顺序：
 *   1) 环境变量 PLAYWRIGHT_PATH 指向的模块
 *   2) 项目内安装的 playwright / playwright-core
 *   3) 本机 Codex 运行时内置的 playwright（开发机默认位置）
 *
 * 用法： const { chromium } = require('./load-playwright.cjs');
 */
const os = require('os');
const path = require('path');
const HOME_NODE = path.join(os.homedir(), '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules');
const CANDIDATES = [
  process.env.PLAYWRIGHT_PATH,
  'playwright',
  'playwright-core',
  path.join(HOME_NODE, 'playwright'),
  path.join(HOME_NODE, 'playwright-core')
].filter(Boolean);

function load() {
  const tried = [];
  for (const c of CANDIDATES) {
    try {
      return require(c);
    } catch (e) {
      tried.push('  - ' + c + '（' + (e.code || (e.message || '').split('\n')[0]) + '）');
    }
  }
  throw new Error(
    '未找到 Playwright，无法运行浏览器测试。\n' +
    '请任选一种方式：\n' +
    '  1) 设置环境变量 PLAYWRIGHT_PATH 指向 playwright 模块路径；\n' +
    '  2) 在项目内执行 npm install playwright。\n' +
    '已尝试：\n' + tried.join('\n')
  );
}

module.exports = load();
