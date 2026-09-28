'use strict';
/*
 * tools/build.cjs —— Go 构建脚本不可用时的等价备用脚本
 *
 * 首选仍为 tools/build.go（在包根目录执行：go run tools/build.go）。
 * 本脚本与其逻辑等价：遍历 original-skill 收集模板与文档、校验模板数为 13、
 * 重建 resources/templates 副本、生成 data/builtin.js 与 data/source-manifest.json，
 * 并由 data/config.json、data/rules.json 生成对应的本地加载脚本 data/*.js。
 *
 * 用法：node tools/build.cjs [--root <包根目录>] [--check-only]
 *   --check-only  只比对将生成的内容与现有文件是否一致，不写入任何文件。
 */
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const args = process.argv.slice(2);
const getArg = (k, d) => { const i = args.indexOf(k); return i >= 0 && args[i + 1] ? args[i + 1] : d; };
const ROOT = path.resolve(getArg('--root', path.join(__dirname, '..')));
const CHECK_ONLY = args.includes('--check-only');

const sha256hex = b => crypto.createHash('sha256').update(b).digest('hex');

/* Go 的 json.Marshal 对 map 键按名称字节序排序，Node 保留插入序，此处递归排序；
   同时 Go 会转义 < > & 与 U+2028/U+2029，并把 \b \f 写作 \u0008 \u000c，一并补齐。 */
function sortDeep(v) {
  if (Array.isArray(v)) return v.map(sortDeep);
  if (v && typeof v === 'object') {
    const o = {};
    for (const k of Object.keys(v).sort()) o[k] = sortDeep(v[k]);
    return o;
  }
  return v;
}
function goJson(v) {
  return JSON.stringify(sortDeep(v))
    .replace(/\\b/g, '\\u0008')
    .replace(/\\f/g, '\\u000c')
    .replace(/</g, '\\u003c')
    .replace(/>/g, '\\u003e')
    .replace(/&/g, '\\u0026')
    .replace(/\u2028/g, '\\u2028')
    .replace(/\u2029/g, '\\u2029');
}

/* 与 Go filepath.WalkDir 等价：目录内条目按名称排序，遇目录即递归进入 */
function walk(dir, rel, out) {
  let ents;
  try { ents = fs.readdirSync(dir, { withFileTypes: true }); } catch (e) { return out; }
  ents = ents
    .filter(e => e.name !== '.DS_Store' && !e.name.startsWith('~$'))
    .sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));
  for (const e of ents) {
    const abs = path.join(dir, e.name);
    const r = rel ? rel + '/' + e.name : e.name;
    if (e.isDirectory()) { if (e.name === '__pycache__') continue; walk(abs, r, out); }
    else out.push({ abs, rel: r, name: e.name });
  }
  return out;
}

function tagOf(name) {
  if (name.includes('合同')) return 'contract';
  if (name.includes('授权')) return 'auth';
  if (name.includes('身份证明')) return 'legalrep';
  if (name.includes('所函')) return 'letter';
  if (name.includes('会见')) return 'meeting_letter';
  return 'checklist';
}

function collect() {
  const templates = [], docs = {}, sourceFiles = [];
  for (const entry of walk(path.join(ROOT, 'original-skill'), '', [])) {
    const b = fs.readFileSync(entry.abs);
    sourceFiles.push({ path: entry.rel, sha256: sha256hex(b) });
    if (entry.rel.endsWith('.docx')) {
      const parts = entry.rel.split('/');
      const name = parts[parts.length - 1], group = parts[parts.length - 2];
      templates.push({
        id: group + '/' + name, group, name, tag: tagOf(name),
        base64: b.toString('base64'), sha256: sha256hex(b), builtin: true
      });
    } else if (/\.(md|json|py)$/.test(entry.rel)) {
      docs[entry.rel] = b.toString('utf8');
    }
  }
  return { templates, docs, sourceFiles };
}

const { templates, docs, sourceFiles } = collect();
if (templates.length !== 13) {
  console.error('expected 13 templates, got ' + templates.length);
  process.exit(1);
}

const appDocs = {};
for (const p of fs.readdirSync(path.join(ROOT, 'docs')).filter(f => f.endsWith('.md')).sort()
  .map(f => 'docs/' + f).concat(['使用说明.md', 'CHANGELOG.md'])) {
  appDocs[p] = fs.readFileSync(path.join(ROOT, p), 'utf8');
}

const version = JSON.parse(fs.readFileSync(path.join(ROOT, 'data/config.json'), 'utf8')).version;
const data = { version, sourceVersion: '3.2.0', templates, originalDocs: docs, appDocs, sourceFiles };

const outputs = {
  'data/builtin.js': 'window.RETAINER_BUILTIN=' + goJson(data) + ';\n',
  'data/source-manifest.json': JSON.stringify(sourceFiles, null, 2)
};
for (const name of ['config', 'rules']) {
  const parsed = JSON.parse(fs.readFileSync(path.join(ROOT, 'data/' + name + '.json'), 'utf8'));
  outputs['data/' + name + '.js'] = 'window.RETAINER_' + name.toUpperCase() + '=' + goJson(parsed) + ';\n';
}

const identical = [], changed = [];
for (const rel of Object.keys(outputs)) {
  const target = path.join(ROOT, rel);
  const old = fs.existsSync(target) ? fs.readFileSync(target, 'utf8') : null;
  if (old === outputs[rel]) { identical.push(rel); continue; }
  changed.push(rel);
  if (!CHECK_ONLY) fs.writeFileSync(target, outputs[rel]);
}

if (!CHECK_ONLY) {
  const dst = path.join(ROOT, 'resources', 'templates');
  fs.rmSync(dst, { recursive: true, force: true });
  for (const t of templates) {
    const target = path.join(dst, t.group, t.name);
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.writeFileSync(target, fs.readFileSync(path.join(ROOT, 'original-skill', 'templates', t.group, t.name)));
  }
}

console.log(JSON.stringify({
  root: ROOT, mode: CHECK_ONLY ? 'check-only' : 'write', version,
  templates: templates.length, sourceFiles: sourceFiles.length,
  originalDocs: Object.keys(docs).length, appDocs: Object.keys(appDocs).length,
  identical, changed
}, null, 1));
