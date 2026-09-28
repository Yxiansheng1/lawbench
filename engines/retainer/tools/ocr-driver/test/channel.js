'use strict';
(() => {
  const BASE = 'http://127.0.0.1:17801';
  const $ = id => document.getElementById(id);
  const stamp = () => new Date().toLocaleTimeString();

  function log(text, cls) {
    const line = document.createElement('div');
    line.className = 'line ' + (cls || '');
    line.innerHTML = '<span class="t">' + stamp() + '</span><span class="m"></span>';
    line.querySelector('.m').textContent = text;
    $('log').append(line);
    $('log').scrollTop = $('log').scrollHeight;
  }

  function verdict(ok, text) {
    const box = $('verdict');
    box.hidden = false;
    box.className = ok ? 'verdict pass' : 'verdict fail';
    box.textContent = text;
  }

  // 机器可读状态：供无头浏览器 dump-dom 后以 ASCII 判定，避免中文编码干扰
  function setMachine(state, detail) {
    document.title = 'CH-' + state;
    let el = document.getElementById('machine');
    if (!el) {
      el = document.createElement('div');
      el.id = 'machine';
      el.style.display = 'none';
      document.body.append(el);
    }
    el.textContent = 'MACHINE_STATE=' + state + ';DETAIL=' + detail;
  }

  function diagnose(e) {
    log('错误名称：' + e.name, 'err');
    log('错误消息：' + e.message, 'err');
    log('排查顺序：', 'hint');
    log('  1) 驱动是否已启动：命令行窗口应显示「驱动已启动」', 'hint');
    log('  2) 本页 CSP 是否放行：connect-src 需包含 ' + BASE, 'hint');
    log('  3) 服务端是否回 CORS 头：Access-Control-Allow-Origin', 'hint');
    log('  4) Chrome 私有网络预检：需 Access-Control-Allow-Private-Network: true', 'hint');
    log('  提示：按 F12 打开控制台，CSP 拦截会留下 "Refused to connect" 记录。', 'hint');
  }

  async function probe() {
    log('开始探测 ' + BASE + '/health');
    const t0 = performance.now();
    try {
      const r = await fetch(BASE + '/health', { cache: 'no-store' });
      const ms = Math.round(performance.now() - t0);
      const j = await r.json();
      log('HTTP ' + r.status + '，耗时 ' + ms + ' ms', 'ok');
      log('引擎=' + j.engine + '　版本=' + j.version + '　就绪=' + j.ready, 'ok');
      if (j.problems && j.problems.length) {
        for (const p of j.problems) log('  引擎 ' + p.engine + ' 失败：' + p.error, 'err');
      }
      verdict(true, '通道可用：已连通本机驱动，引擎为 ' + j.engine);
      setMachine('PASS', 'engine=' + j.engine + ',ready=' + j.ready + ',version=' + j.version);
      $('upload').disabled = !j.ready;
    } catch (e) {
      log('探测失败，耗时 ' + Math.round(performance.now() - t0) + ' ms', 'err');
      diagnose(e);
      verdict(false, '通道不可用：' + e.name + ' — ' + e.message);
      setMachine('FAIL', 'name=' + e.name + ',msg=' + String(e.message).slice(0, 80));
    }
  }

  async function recognize(file) {
    log('上传 ' + file.name + '（' + Math.round(file.size / 1024) + ' KB）');
    const t0 = performance.now();
    try {
      const r = await fetch(BASE + '/ocr', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/octet-stream',
          'X-File-Name': encodeURIComponent(file.name || 'upload.bin')
        },
        body: file
      });
      const ms = Math.round(performance.now() - t0);
      const j = await r.json();
      if (!j.ok) {
        log('HTTP ' + r.status + '，往返 ' + ms + ' ms', 'err');
        log('驱动报错：' + j.error, 'err');
        if (j.detail) log(j.detail, 'hint');
        setMachine('UPLOAD_FAIL', 'http=' + r.status + ',err=' + String(j.error).slice(0, 60));
        return;
      }
      log('HTTP ' + r.status + '，往返 ' + ms + ' ms，驱动内耗时 ' + j.durationMs + ' ms', 'ok');
      log('格式 ' + j.format + '　是否走 OCR：' + (j.usedOcr ? '是' : '否')
        + '　文本层 ' + (j.text || '').length + ' 字　OCR ' + j.lines.length + ' 行', 'ok');
      for (const n of (j.notes || [])) log('  · ' + n, 'hint');
      setMachine('UPLOAD_PASS', 'format=' + j.format + ',usedOcr=' + j.usedOcr
        + ',lines=' + j.lines.length + ',durationMs=' + j.durationMs + ',roundtripMs=' + ms);
      const list = $('lines');
      list.replaceChildren();
      if (j.text) {
        const row = document.createElement('div');
        row.className = 'row';
        row.innerHTML = '<span class="txt"></span><span class="meta">文本层直接提取</span>';
        row.querySelector('.txt').textContent = j.text.replace(/\s*\n\s*/g, ' / ');
        list.append(row);
      }
      for (const line of j.lines) {
        const row = document.createElement('div');
        row.className = 'row';
        const sc = line.score === null ? '—' : line.score.toFixed(3);
        const bx = line.box ? line.box[0][0] + ',' + line.box[0][1] : '—';
        row.innerHTML = '<span class="txt"></span><span class="meta"></span>';
        row.querySelector('.txt').textContent = line.text;
        row.querySelector('.meta').textContent = 'score ' + sc + '　起点 ' + bx;
        list.append(row);
      }
      $('result').hidden = false;
    } catch (e) {
      log('上传失败，耗时 ' + Math.round(performance.now() - t0) + ' ms', 'err');
      diagnose(e);
      setMachine('UPLOAD_FAIL', 'name=' + e.name + ',msg=' + String(e.message).slice(0, 60));
    }
  }

  // 页内生成测试图直接上传：用于无头环境下验证「上传 → 识别 → 返回」完整链路
  async function selftestUpload() {
    log('生成页内测试图（虚构内容）…');
    const c = document.createElement('canvas');
    c.width = 900;
    c.height = 300;
    const g = c.getContext('2d');
    g.fillStyle = '#fff';
    g.fillRect(0, 0, c.width, c.height);
    g.fillStyle = '#000';
    g.font = '28px "Microsoft YaHei", sans-serif';
    const rows = [
      '营业执照',
      '名称 深圳市示例科技有限公司',
      '统一社会信用代码 91440300MA5EXAMPLA',
      '法定代表人 张三'
    ];
    rows.forEach((t, i) => g.fillText(t, 40, 60 + i * 56));
    const blob = await new Promise(r => c.toBlob(r, 'image/png'));
    const file = new File([blob], 'selftest.png', { type: 'image/png' });
    log('测试图 ' + Math.round(blob.size / 1024) + ' KB，开始上传');
    await recognize(file);
  }

  $('probe').onclick = probe;
  $('upload').onchange = () => {
    const f = $('upload').files[0];
    if (f) recognize(f);
  };
  $('showCsp').onclick = () => {
    const meta = document.querySelector('meta[http-equiv="Content-Security-Policy"]');
    log('本页 CSP：' + (meta ? meta.content : '未设置'), 'hint');
  };

  const selftestBtn = document.createElement('button');
  selftestBtn.textContent = '生成测试图并识别';
  selftestBtn.onclick = selftestUpload;
  document.querySelector('.acts').append(selftestBtn);

  log('页面已加载（协议：' + location.protocol + '，源：' + location.origin + '）');
  if (location.protocol !== 'file:') {
    log('注意：本页并非以 file:// 打开，测试结果不反映双击打开的真实场景。', 'hint');
  }
  probe().then(() => {
    if (location.hash.indexOf('auto') >= 0) {
      log('检测到 #auto，自动执行完整链路测试');
      selftestUpload();
    }
  });
})();
