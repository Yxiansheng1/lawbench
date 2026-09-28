'use strict';
/*
 * 证件识别入口（可选功能）
 *
 * 依赖本机驱动 http://127.0.0.1:17801。驱动未启动时本卡片降级为提示并自动重试探测，
 * 不影响工具的其他功能。
 *
 * 职责边界：驱动只回传「带坐标的文本行」，字段解析、证种推断与业务规则在此完成。
 * 识别结果仅作预填，必须人工核对后才用于生成文书。
 *
 * 注意：营业执照的「名称」是单位名称，身份证的「姓名」是自然人姓名，二者语义不同，
 * 因此结果按证种分组保存与展示，不做同名字段合并。
 */
(() => {
  const R = Retainer;
  const BASE = 'http://127.0.0.1:17801';
  const $ = id => document.getElementById(id);

  const CERT_ORDER = ['auto', 'business_license', 'social_org_cert', 'private_nonenterprise_cert', 'id_card_front', 'id_card_back'];
  const ORG_CERTS = ['business_license', 'social_org_cert', 'private_nonenterprise_cert'];

  const CERT_LABEL = {
    auto: '自动识别',
    business_license: '营业执照',
    social_org_cert: '社会团体法人登记证书',
    private_nonenterprise_cert: '民办非企业单位登记证书',
    id_card_front: '居民身份证（人像面）',
    id_card_back: '居民身份证（国徽面）'
  };

  const FIELDS = {
    business_license: {
      name: ['名称', '企业名称', '单位名称'],
      credit_code: ['统一社会信用代码', '统一代码', '社会信用代码'],
      org_type: ['类型', '公司类型', '企业类型', '主体类型'],
      legal_rep: ['法定代表人', '负责人', '执行事务合伙人', '投资人', '经营者'],
      capital: ['注册资本', '注册资金', '出资额'],
      address: ['住所', '地址', '经营场所', '主要经营场所'],
      established: ['成立日期', '注册日期', '成立时间'],
      scope: ['经营范围', '业务范围']
    },
    social_org_cert: {
      name: ['名称', '社团名称', '单位名称'],
      credit_code: ['统一社会信用代码', '统一代码', '社会信用代码'],
      org_type: ['类型', '社团类型'],
      legal_rep: ['法定代表人', '负责人'],
      address: ['住所', '办公住所', '地址'],
      established: ['成立日期', '登记日期'],
      scope: ['业务范围', '宗旨和业务范围']
    },
    private_nonenterprise_cert: {
      name: ['名称', '单位名称'],
      credit_code: ['统一社会信用代码', '统一代码'],
      legal_rep: ['法定代表人', '负责人'],
      address: ['住所', '地址'],
      established: ['成立日期', '登记日期'],
      scope: ['业务范围']
    },
    id_card_front: {
      name: ['姓名'],
      gender: ['性别'],
      ethnicity: ['民族'],
      birth: ['出生'],
      address: ['住址', '地址'],
      id_number: ['公民身份号码', '公民身份证号码', '身份号码', '身份证号']
    },
    id_card_back: {
      issuing_authority: ['签发机关'],
      valid_period: ['有效期限', '有效期']
    }
  };

  const TITLE = {
    name: '名称/姓名', credit_code: '统一社会信用代码', org_type: '类型',
    legal_rep: '法定代表人/负责人', capital: '注册资本', address: '住所',
    established: '成立日期', scope: '经营范围', gender: '性别',
    ethnicity: '民族', birth: '出生日期', id_number: '公民身份号码',
    issuing_authority: '签发机关', valid_period: '有效期限'
  };

  const FORM_TITLE = { plaintiff: '委托方', legal_rep: '法定代表人', legal_rep_position: '法定代表人职务' };

  const CERT_HINT = {
    business_license: ['统一社会信用代码', '营业执照', '注册资本', '经营范围', '法定代表人'],
    social_org_cert: ['社会团体法人登记证书', '社团', '业务主管单位'],
    private_nonenterprise_cert: ['民办非企业单位登记证书', '民办非企业'],
    id_card_front: ['公民身份号码', '姓名', '住址', '出生', '民族'],
    id_card_back: ['签发机关', '有效期限']
  };

  /** 登记类型 → 主体形态判据 */
  const ORG_UNINCORPORATED = /合伙|个人独资|事务所|分支机构|分公司|营业部|代表处|办事处|合作社|协会|社会团体|民办非企业|基金会|村民委员会|居民委员会|农村集体经济组织/;
  const ORG_COMPANY = /有限责任公司|股份有限公司|有限公司|集团|控股/;
  /** 单位印章与单位名称线索 */
  const SEAL_HINT = /公章|专用章|盖章|印章|财务章|合同章/;
  const ORG_NAME_HINT = /有限公司|股份有限公司|集团|事务所|合作社|分公司|个体工商户|厂|银行|医院|学校|中心/;

  const CODE_FIELDS = { credit_code: 'uscc', id_number: 'idcard' };
  const USCC_CHARS = '0123456789ABCDEFGHJKLMNPQRTUWXY';
  const ID_W = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2];
  const ID_MAP = '10X98765432';
  const DIGIT_FIX = { O: '0', o: '0', D: '0', Q: '0', I: '1', l: '1', '|': '1', i: '1', Z: '2', z: '2', A: '4', S: '5', s: '5', G: '6', b: '6', T: '7', B: '8', g: '9', q: '9' };

  const squeeze = s => String(s == null ? '' : s).replace(/[\s\u3000]+/g, ' ').trim();
  const stripNoise = s => squeeze(s).replace(/[\s\u3000:：]/g, '');

  let engineReady = false;
  let probeTimer = null;
  let results = [];         // 每份文件一条：{name, certType, fields, status, warnings, lines, format, usedOcr, durationMs}
  let sealed = false;       // 身份证是否按「有单位盖章」处理
  let busy = false;

  /* ---------------- 文本解析 ---------------- */

  function compactMap(text) {
    const chars = [], idx = [];
    for (let i = 0; i < text.length; i++) {
      const c = text[i];
      if (c === ' ' || c === '\u3000' || c === '\t') continue;
      chars.push(c);
      idx.push(i);
    }
    return { text: chars.join(''), idx };
  }

  function findLoose(text, label) {
    const t = compactMap(text), l = compactMap(label).text;
    if (!l) return null;
    const p = t.text.indexOf(l);
    if (p < 0) return null;
    return [t.idx[p], t.idx[p + l.length - 1] + 1];
  }

  function scanLabels(text, certType) {
    const spec = FIELDS[certType] || {};
    const hits = [];
    for (const field of Object.keys(spec)) {
      let best = null;
      for (const lab of spec[field]) {
        const span = findLoose(text, lab);
        if (span && (!best || span[0] < best[0])) best = span;
      }
      if (best) hits.push({ field, start: best[0], end: best[1] });
    }
    hits.sort((a, b) => a.start - b.start || (b.end - b.start) - (a.end - a.start));
    const out = [];
    for (const h of hits) {
      if (out.length && h.start < out[out.length - 1].end) continue;
      out.push(h);
    }
    return out;
  }

  /** 值可能跨多行的字段：值为最大续行数。住址最典型，身份证与执照上的地址常被排版成 2—3 行 */
  const MULTILINE = { address: 3, scope: 5 };
  /** 住址末端标识：缺少这些词通常意味着没有取全 */
  const ADDR_TAIL = /[号组村路巷弄栋室楼队区县旗盟]/;
  const PROVINCE = {
    11: '北京', 12: '天津', 13: '河北', 14: '山西', 15: '内蒙古', 21: '辽宁', 22: '吉林',
    23: '黑龙江', 31: '上海', 32: '江苏', 33: '浙江', 34: '安徽', 35: '福建', 36: '江西',
    37: '山东', 41: '河南', 42: '湖北', 43: '湖南', 44: '广东', 45: '广西', 46: '海南',
    50: '重庆', 51: '四川', 52: '贵州', 53: '云南', 54: '西藏', 61: '陕西', 62: '甘肃',
    63: '青海', 64: '宁夏', 65: '新疆'
  };

  function buildRows(lines) {
    const items = [];
    for (const ln of lines) {
      const text = squeeze(ln.text);
      if (!text) continue;
      const box = ln.box;
      if (!box || !box.length) { items.push({ text, top: 0, bottom: 0, left: 0, right: 0, h: 1 }); continue; }
      const ys = box.map(p => p[1]), xs = box.map(p => p[0]);
      const top = Math.min.apply(null, ys), bottom = Math.max.apply(null, ys);
      const left = Math.min.apply(null, xs), right = Math.max.apply(null, xs);
      items.push({ text, top, bottom, left, right, h: Math.max(1, bottom - top) });
    }
    if (!items.length) return [];
    items.sort((a, b) => a.top - b.top || a.left - b.left);
    const rows = [];
    for (const it of items) {
      let placed = false;
      for (const row of rows) {
        const overlap = Math.min(row.bottom, it.bottom) - Math.max(row.top, it.top);
        if (overlap > 0.5 * Math.min(row.h, it.h)) {
          row.items.push(it);
          row.top = Math.min(row.top, it.top);
          row.bottom = Math.max(row.bottom, it.bottom);
          row.h = Math.max(row.h, it.h);
          placed = true;
          break;
        }
      }
      if (!placed) rows.push({ items: [it], top: it.top, bottom: it.bottom, h: it.h });
    }
    for (const row of rows) row.items.sort((a, b) => a.left - b.left);
    rows.sort((a, b) => a.top - b.top);
    return rows.map(r => ({
      text: r.items.map(i => i.text).join(' '),
      left: Math.min.apply(null, r.items.map(i => i.left)),
      right: Math.max.apply(null, r.items.map(i => i.right)),
      items: r.items
    }));
  }

  function usccCheck(c17) {
    let total = 0;
    for (let i = 0; i < 17; i++) {
      const k = USCC_CHARS.indexOf(c17[i]);
      if (k < 0) return null;
      total = (total + k * Math.pow(3, i)) % 31;
    }
    const c = 31 - total;
    return USCC_CHARS[c === 31 ? 0 : c];
  }

  function fixUscc(raw) {
    let s = stripNoise(raw).toUpperCase();
    for (const ch of s) if (DIGIT_FIX[ch] && USCC_CHARS.indexOf(ch) < 0) s = s.replace(ch, DIGIT_FIX[ch]);
    if (s.length !== 18 || [...s].some(c => USCC_CHARS.indexOf(c) < 0)) return [s, 'invalid'];
    if (usccCheck(s.slice(0, 17)) === s[17]) return [s, 'ok'];
    const hits = [];
    for (let i = 0; i < 18; i++) {
      for (const c of USCC_CHARS) {
        if (c === s[i]) continue;
        const cand = s.slice(0, i) + c + s.slice(i + 1);
        if (usccCheck(cand.slice(0, 17)) === cand[17]) hits.push(cand);
      }
    }
    return hits.length === 1 ? [hits[0], 'fixed'] : [s, 'invalid'];
  }

  function idCheck(id17) {
    let total = 0;
    for (let i = 0; i < 17; i++) {
      const d = id17.charCodeAt(i) - 48;
      if (d < 0 || d > 9) return null;
      total += d * ID_W[i];
    }
    return ID_MAP[total % 11];
  }

  function fixIdCard(raw) {
    let s = stripNoise(raw).toUpperCase();
    for (const ch of s) if (DIGIT_FIX[ch] && '0123456789X'.indexOf(ch) < 0) s = s.replace(ch, DIGIT_FIX[ch]);
    if (s.length !== 18 || [...s].some(c => '0123456789X'.indexOf(c) < 0)) return [s, 'invalid'];
    if (idCheck(s.slice(0, 17)) === s[17]) return [s, 'ok'];
    const hits = [];
    for (let i = 0; i < 18; i++) {
      const alphabet = i < 17 ? '0123456789' : '0123456789X';
      for (const c of alphabet) {
        if (c === s[i]) continue;
        const cand = s.slice(0, i) + c + s.slice(i + 1);
        if (idCheck(cand.slice(0, 17)) === cand[17]) hits.push(cand);
      }
    }
    return hits.length === 1 ? [hits[0], 'fixed'] : [s, 'invalid'];
  }

  function extract(certType, lines) {
    const rows = buildRows(lines);
    const fields = {}, status = {}, warnings = [];
    const used = new Set();

    // 第一遍：同行按标签切段取值，并对多行字段吸收其后的续行
    for (let i = 0; i < rows.length; i++) {
      const hits = scanLabels(rows[i].text, certType);
      for (let j = 0; j < hits.length; j++) {
        const start = hits[j].end;
        const end = (j + 1 < hits.length) ? hits[j + 1].start : rows[i].text.length;
        let val = squeeze(rows[i].text.slice(start, end)).replace(/^[\s:：]+|[\s:：]+$/g, '');
        if (!val) continue;
        const field = hits[j].field;

        const maxMore = MULTILINE[field] || 0;
        if (maxMore) {
          let more = 0, k = i + 1;
          while (k < rows.length && more < maxMore) {
            if (used.has(k)) break;
            if (scanLabels(rows[k].text, certType).length) break;
            const t = squeeze(rows[k].text);
            if (!t) break;
            if (rows[k].left < rows[i].left - 20) break;
            val += t;
            used.add(k);
            more++; k++;
          }
        }
        if (!fields[field]) { fields[field] = val; used.add(i); }
      }
    }

    // 第二遍：标签与值分处两行的情形
    for (let i = 0; i < rows.length; i++) {
      if (used.has(i)) continue;
      const hits = scanLabels(rows[i].text, certType);
      if (hits.length !== 1) continue;
      const h = hits[0];
      const tail = squeeze(rows[i].text.slice(h.end)).replace(/^[\s:：]+|[\s:：]+$/g, '');
      if (tail) { if (!fields[h.field]) fields[h.field] = tail; used.add(i); continue; }
      if (i + 1 < rows.length && !used.has(i + 1) && !scanLabels(rows[i + 1].text, certType).length) {
        if (!fields[h.field]) fields[h.field] = squeeze(rows[i + 1].text);
        used.add(i); used.add(i + 1);
      }
    }

    for (const f of Object.keys(fields)) {
      if (CODE_FIELDS[f] === 'uscc') {
        const r = fixUscc(fields[f]);
        fields[f] = r[0]; status[f] = r[1];
        if (r[1] === 'invalid') warnings.push('统一社会信用代码校验未通过，请核对原件');
        else if (r[1] === 'fixed') warnings.push('统一社会信用代码已按校验位自动修正');
      } else if (CODE_FIELDS[f] === 'idcard') {
        const r = fixIdCard(fields[f]);
        fields[f] = r[0]; status[f] = r[1];
        if (r[1] === 'invalid') warnings.push('公民身份号码校验未通过，请核对原件');
        else if (r[1] === 'fixed') warnings.push('公民身份号码已按校验位自动修正');
      }
    }

    crossCheck(certType, fields, warnings);

    return { fields, status, warnings, texts: rows.map(r => r.text) };
  }

  /** 补正验证：住址完整性，以及身份证号与住址、出生日期的相互印证 */
  function crossCheck(certType, fields, warnings) {
    const addr = fields.address;
    if (addr) {
      if (addr.length < 6) warnings.push('住址识别结果过短（' + addr + '），可能未取全，请核对原件');
      else if (!ADDR_TAIL.test(addr)) warnings.push('住址「' + addr + '」未见村组或门牌等末端信息，可能未取全，请核对原件');
    }
    if (certType !== 'id_card_front') return;

    const id = fields.id_number || '';
    if (!/^\d{17}[\dXx]$/.test(id)) return;

    const prov = PROVINCE[id.slice(0, 2)];
    if (prov && addr && addr.indexOf(prov.slice(0, 2)) < 0) {
      warnings.push('住址与身份号码的行政区划不一致：号码归属' + prov + '，住址为「' + addr.slice(0, 14) + '…」，请核对原件');
    }
    const y = id.slice(6, 10), m = id.slice(10, 12), d = id.slice(12, 14);
    const birth = fields.birth || '';
    if (birth) {
      const digits = birth.replace(/[^\d]/g, '');
      if (digits.indexOf(y + m + d) < 0 && digits.indexOf(y) < 0) {
        warnings.push('出生日期「' + birth + '」与身份号码中的 ' + y + '年' + m + '月' + d + '日 不一致，请核对原件');
      }
    }
  }

  function guessCertType(lines) {
    const text = lines.map(l => l.text).join(' ');
    if (/公民身份号码|身份号码/.test(text) && /姓名/.test(text)) return 'id_card_front';
    if (/签发机关/.test(text) && /有效期限/.test(text)) return 'id_card_back';
    let best = null, bestN = 0;
    for (const k of Object.keys(CERT_HINT)) {
      const n = CERT_HINT[k].filter(h => text.indexOf(h) >= 0).length;
      if (n > bestN) { bestN = n; best = k; }
    }
    return bestN >= 2 ? best : null;
  }

  /* ---------------- 业务规则 ---------------- */

  const isOrgCert = t => ORG_CERTS.indexOf(t) >= 0;

  /** 单位证照只可能是法人、非法人组织或个人独资企业，绝不按自然人处理 */
  function judgeParty(fields, certType) {
    if (certType === 'id_card_front' || certType === 'id_card_back') {
      return { party: '个人', confidence: 'high', note: '自然人委托' };
    }
    const t = fields.org_type || '';
    if (!t) return { party: '公司', confidence: 'low', note: '证照上未见「类型」，主体形态请按登记证书确认' };
    if (ORG_COMPANY.test(t)) return { party: '公司', confidence: 'high', note: '法人（' + t + '）' };
    if (ORG_UNINCORPORATED.test(t)) {
      return {
        party: '公司', confidence: 'low',
        note: '登记类型为「' + t + '」，属非法人组织或个人独资企业，不是自然人；当前「主体类型」尚无该选项，'
          + '故暂按单位处理，签署人须按登记证书确认为负责人或执行事务合伙人'
      };
    }
    return { party: '公司', confidence: 'low', note: '登记类型未识别（' + t + '），请按登记证书确认主体形态' };
  }

  /** 某字段应填入案件表单的哪个键；返回 null 表示仅供核对 */
  function fieldTarget(certType, key) {
    if (isOrgCert(certType)) {
      if (key === 'name') return 'plaintiff';
      if (key === 'legal_rep') return sealed ? null : 'legal_rep';   // 有盖章身份证时以身份证为准
      return null;
    }
    if (certType === 'id_card_front') {
      if (key === 'name') return sealed ? 'legal_rep' : 'plaintiff';
      return null;
    }
    return null;
  }

  /* ---------------- UI ---------------- */

  function setState_(text, cls) {
    const el = $('scanState');
    el.hidden = false;
    el.className = 'inset' + (cls ? ' ' + cls : '');
    el.textContent = text;
  }

  function setEnabled(on) {
    $('scanFile').disabled = !on;
    $('scanCertType').disabled = !on;
    $('scanDrop').classList.toggle('disabled', !on);
  }

  async function probe(quiet) {
    try {
      const r = await fetch(BASE + '/health', { cache: 'no-store' });
      const health = await r.json();
      if (!health.ready) throw new Error((health.problems || []).map(x => x.engine + '：' + x.error).join('；') || '引擎未就绪');
      engineReady = true;
      setEnabled(true);
      setState_('本机识别引擎已就绪（' + health.engine + '）。把证件文件拖到下方虚线框即可，支持图片、PDF、Word，可一次拖多份。');
      if (probeTimer) { clearInterval(probeTimer); probeTimer = null; }
      return true;
    } catch (e) {
      engineReady = false;
      setEnabled(false);
      if (!quiet) {
        setState_('未检测到本机识别引擎。请双击工作台目录下的「启动委托工作台.bat」'
          + '（或 tools/ocr-driver/start-engine.bat）；启动后本页会自动接上，无需刷新。'
          + '不使用识别功能时，其余操作不受影响。');
      }
      startProbeLoop();
      return false;
    }
  }

  function startProbeLoop() {
    if (probeTimer) return;
    probeTimer = setInterval(() => { if (!engineReady) probe(true); else { clearInterval(probeTimer); probeTimer = null; } }, 3000);
  }

  /** 单个文件的识别请求超时（毫秒）。多页 PDF 会慢一些，给足余量 */
  const OCR_TIMEOUT_MS = 90000;

  async function uploadFiles(files) {
    const list = [...files].filter(f => f && f.size);
    if (!list.length || busy) return;
    if (!engineReady) { setState_('识别引擎尚未就绪，请先启动驱动。', 'text-danger'); return; }

    busy = true;
    results = [];
    sealed = false;
    let chosen = 'auto';
    const crossNotes = [];

    try {
      chosen = ($('scanCertType') && $('scanCertType').value) || 'auto';
      for (let i = 0; i < list.length; i++) {
        const f = list[i];
        setState_('正在识别（' + (i + 1) + '/' + list.length + '）：' + f.name + ' …');
        try {
          const ctl = new AbortController();
          const timer = setTimeout(() => ctl.abort(), OCR_TIMEOUT_MS);
          let r;
          try {
            r = await fetch(BASE + '/ocr', {
              method: 'POST',
              headers: { 'Content-Type': 'application/octet-stream', 'X-File-Name': encodeURIComponent(f.name) },
              body: f,
              signal: ctl.signal
            });
          } finally {
            clearTimeout(timer);
          }
          const j = await r.json();
          if (!j.ok) { crossNotes.push(f.name + '：' + j.error); continue; }

          const certType = (chosen && chosen !== 'auto') ? chosen : (guessCertType(j.lines || []) || null);
          if (!certType) {
            results.push({ name: f.name, certType: null, fields: {}, status: {}, warnings: [], lines: j.lines || [], format: j.format, usedOcr: j.usedOcr, durationMs: j.durationMs });
            crossNotes.push(f.name + '：识别到 ' + (j.lines || []).length + ' 行文字，但无法判定证件类型；请在上方指定证件类型后重新导入');
            continue;
          }
          const data = extract(certType, j.lines || []);
          if (j.notes && j.notes.length) data.warnings.push(...j.notes);
          results.push({ name: f.name, certType, fields: data.fields, status: data.status, warnings: data.warnings, lines: j.lines || [], format: j.format, usedOcr: j.usedOcr, durationMs: j.durationMs });
          if (data.warnings.length) crossNotes.push(f.name + '：' + data.warnings.join('；'));
        } catch (e) {
          if (e && e.name === 'AbortError') {
            crossNotes.push(f.name + '：识别超时（超过 ' + Math.round(OCR_TIMEOUT_MS / 1000) + ' 秒），请改用更小的文件或单独重试');
          } else {
            crossNotes.push(f.name + '：请求失败 ' + (e && e.name ? e.name : '') + ' — ' + (e && e.message ? e.message : String(e)));
          }
        }
      }

      // 同一证种出现多份时，检查关键字段是否相互矛盾
      const byCert = {};
      for (const r of results) if (r.certType) (byCert[r.certType] = byCert[r.certType] || []).push(r);
      for (const ct of Object.keys(byCert)) {
        if (byCert[ct].length < 2) continue;
        for (const k of Object.keys(byCert[ct][0].fields)) {
          const vals = [...new Set(byCert[ct].map(r => r.fields[k]).filter(Boolean))];
          if (vals.length > 1) crossNotes.push(CERT_LABEL[ct] + '的「' + (TITLE[k] || k) + '」在不同文件中不一致：' + vals.join(' / '));
        }
      }

      // 身份证若与单位名称或印章线索同现，提示很可能为法定代表人
      const allText = results.map(r => (r.lines || []).map(l => l.text).join(' ')).join(' ');
      const hasId = results.some(r => r.certType === 'id_card_front');
      const hasOrg = results.some(r => isOrgCert(r.certType));
      if (hasId && (hasOrg || SEAL_HINT.test(allText) || ORG_NAME_HINT.test(allText))) sealed = true;

      results.crossNotes = crossNotes;
      const ok = results.filter(r => r.certType).length;
      setState_(ok
        ? '完成 ' + results.length + ' 份，其中可解析 ' + ok + ' 份：' + results.map(r => r.name + '（' + (r.certType ? CERT_LABEL[r.certType] : '类型未判定') + '）').join('；')
        : '没有可用的识别结果');
    } catch (e) {
      results.crossNotes = crossNotes;
      setState_('识别过程出错：' + (e && e.message ? e.message : String(e)), 'text-danger');
    } finally {
      busy = false;
    }
    renderPreview();
  }

  function line(text, cls) {
    const d = document.createElement('div');
    d.className = cls || 'muted';
    d.style.margin = '6px 0';
    d.textContent = text;
    return d;
  }

  function renderPreview() {
    const box = $('scanFields');
    box.replaceChildren();

    const idRec = results.find(r => r.certType === 'id_card_front');
    const orgRec = results.find(r => isOrgCert(r.certType));

    if (idRec) {
      const wrap = document.createElement('label');
      wrap.className = 'check';
      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.checked = sealed;
      cb.onchange = () => { sealed = cb.checked; renderPreview(); };
      wrap.append(cb, document.createTextNode('该身份证加盖了单位公章（或本次同时提供了单位证照）—— 通常即该单位的法定代表人；勾选后姓名填入「法定代表人」'));
      box.append(wrap);
    }

    // 主体形态判定
    if (orgRec) {
      const j = judgeParty(orgRec.fields, orgRec.certType);
      box.append(line('主体形态：' + j.party + '（' + (j.confidence === 'high' ? '确定' : '需确认') + '）—— ' + j.note,
        j.confidence === 'high' ? 'muted' : 'warn'));
    }
    if (idRec) {
      box.append(line('主体形态：个人（确定）—— 自然人委托'
        + (sealed ? '；因有单位盖章线索，该自然人很可能为所涉单位的法定代表人' : '')));
    }
    if (idRec && orgRec && idRec.fields.name && orgRec.fields.legal_rep
      && squeeze(idRec.fields.name) === squeeze(orgRec.fields.legal_rep)) {
      box.append(line('交叉印证：身份证姓名与单位证照的法定代表人一致（' + idRec.fields.name + '），可确认为法定代表人本人。', 'ok'));
    }

    // 按证种分组列出字段
    for (const r of results) {
      if (!r.certType) { box.append(line('【' + r.name + '】未能判定证件类型，未解析字段')); continue; }
      const head = document.createElement('div');
      head.className = 'muted';
      head.style.margin = '10px 0 2px';
      head.style.fontWeight = '500';
      head.textContent = '【' + CERT_LABEL[r.certType] + '】' + r.name;
      box.append(head);
      for (const k of Object.keys(r.fields)) {
        const wrap = document.createElement('label');
        const target = fieldTarget(r.certType, k);
        wrap.textContent = (TITLE[k] || k) + (target ? '（填入「' + (FORM_TITLE[target] || target) + '」）' : '（供核对）');
        const input = document.createElement('input');
        input.value = r.fields[k];
        input.dataset.cert = r.certType;
        input.dataset.key = k;
        input.dataset.target = target || '';
        const st = r.status[k];
        if (st === 'fixed') { input.style.borderColor = '#BA7517'; input.title = '已按校验位自动修正'; }
        else if (st === 'invalid') { input.style.borderColor = '#A32D2D'; input.title = '校验未通过，请核对原件'; }
        wrap.append(input);
        box.append(wrap);
      }
    }

    $('scanRaw').textContent = results.map(r =>
      '【' + r.name + '】' + (r.certType ? CERT_LABEL[r.certType] : '类型未判定')
      + '　格式 ' + (r.format || '-') + '　' + (r.usedOcr ? 'OCR' : '文本层直接提取')
      + '\n' + r.lines.map((l, i) => '  ' + (i + 1) + '. ' + l.text).join('\n')
    ).join('\n\n');

    const notes = $('scanNotes');
    const tips = (results.crossNotes || []).slice();
    if (sealed) tips.push('已按「身份证＋单位盖章」处理：姓名填入法定代表人，委托方请填单位名称。');
    notes.textContent = tips.join('　');
    notes.hidden = !tips.length;
    $('scanPreview').hidden = false;
  }

  function applyToForm() {
    const state = RETAINER_UI.getState();
    const rec = state.records[state.index];
    if (!rec) { setState_('没有可写入的案件，请先新建案件。', 'text-danger'); return; }

    const applied = [], hints = [];
    const values = {};
    for (const input of $('scanFields').querySelectorAll('input[data-key]')) {
      const target = input.dataset.target;
      values[input.dataset.cert + '.' + input.dataset.key] = input.value;
      if (target) {
        rec.row[target] = input.value;
        applied.push((TITLE[input.dataset.key] || input.dataset.key) + '→' + (FORM_TITLE[target] || target));
      }
    }

    const idRec = results.find(r => r.certType === 'id_card_front');
    const orgRec = results.find(r => isOrgCert(r.certType));
    const idName = idRec ? (values['id_card_front.name'] || idRec.fields.name) : '';
    const orgName = orgRec ? (values[orgRec.certType + '.name'] || orgRec.fields.name) : '';

    if (idRec && !sealed) {
      if (rec.row.party_type === '自动识别') { rec.row.party_type = '个人'; hints.push('主体类型已按自然人设为「个人」'); }
    } else if (orgRec) {
      if (rec.row.party_type === '自动识别' || rec.row.party_type === '个人') {
        rec.row.party_type = '公司';
        hints.push('单位证照不作为自然人，主体类型已设为「公司」');
      }
      const j = judgeParty(orgRec.fields, orgRec.certType);
      if (j.confidence !== 'high') hints.push(j.note);
    }

    if (sealed && idName) {
      if (!rec.row.legal_rep) { rec.row.legal_rep = idName; applied.push('姓名→法定代表人'); }
      if (orgName && !rec.row.plaintiff) { rec.row.plaintiff = orgName; applied.push('单位名称→委托方'); }
      hints.push('按「身份证＋单位盖章」处理，请确认委托方为单位、签署人为该法定代表人');
    }

    if (!applied.length) { setState_('本次识别没有可自动填入的字段，请手工抄录上方内容。'); return; }
    RETAINER_UI.setState(state);
    setState_('已填入当前案件：' + applied.join('、') + '。'
      + (hints.length ? '　' + hints.join('；') + '。' : '') + '请核对后继续。');
  }

  /* ---------------- 拖拽 ---------------- */

  function setupDrop() {
    const zone = $('scanDrop');
    let depth = 0;
    const stop = e => { e.preventDefault(); e.stopPropagation(); };
    const highlight = on => zone.classList.toggle('over', on);

    zone.addEventListener('dragenter', e => { stop(e); if (engineReady) highlight(true); });
    zone.addEventListener('dragover', e => { stop(e); if (engineReady) { e.dataTransfer.dropEffect = 'copy'; highlight(true); } });
    zone.addEventListener('dragleave', e => { stop(e); highlight(false); });
    zone.addEventListener('drop', e => {
      stop(e); highlight(false);
      if (!engineReady) { setState_('识别引擎尚未就绪，请先启动驱动。', 'text-danger'); return; }
      uploadFiles(e.dataTransfer.files);
    });
    zone.addEventListener('click', () => { if (engineReady) $('scanFile').click(); });

    document.body.addEventListener('dragenter', e => { e.preventDefault(); depth++; if (engineReady) highlight(true); });
    document.body.addEventListener('dragover', e => { e.preventDefault(); if (engineReady) e.dataTransfer.dropEffect = 'copy'; });
    document.body.addEventListener('dragleave', e => { e.preventDefault(); if (--depth <= 0) { depth = 0; highlight(false); } });
    document.body.addEventListener('drop', e => {
      e.preventDefault(); depth = 0; highlight(false);
      const f = e.dataTransfer && e.dataTransfer.files;
      if (!f || !f.length) return;
      if (!engineReady) { setState_('识别引擎尚未就绪，请先启动驱动。', 'text-danger'); return; }
      if (!zone.contains(e.target)) uploadFiles(f);
    });
  }

  /* ---------------- 自检 ---------------- */

  async function selfTest() {
    try {
      const c = document.createElement('canvas');
      c.width = 1000;
      c.height = 380;
      const g = c.getContext('2d');
      g.fillStyle = '#fff';
      g.fillRect(0, 0, c.width, c.height);
      g.fillStyle = '#000';
      g.font = '26px "Microsoft YaHei", sans-serif';
      const body17 = '36098219850312001';
      const idno = body17 + idCheck(body17);
      const rows = [
        '居民身份证',
        '姓名 李四  性别 男  民族 汉',
        '出生 1985年3月12日',
        '住址 江西省樟树市义成镇淖港村',
        '　　　碰塘组15附1号',
        '公民身份号码 ' + idno
      ];
      rows.forEach((t, i) => g.fillText(t, 40, 50 + i * 50));
      const blob = await new Promise(r => c.toBlob(r, 'image/png'));
      await uploadFiles([new File([blob], 'selftest-idcard.png', { type: 'image/png' })]);
      const rec = results.find(r => r.certType === 'id_card_front') || {};
      const f = rec.fields || {};
      document.title = 'IDTEST address=[' + (f.address || '') + '] name=[' + (f.name || '')
        + '] id=[' + (f.id_number || '') + '] birth=[' + (f.birth || '') + ']'
        + ' warn=' + ((rec.warnings || []).join(' ; ') || 'none').slice(0, 120);
    } catch (e) {
      document.title = 'IDTEST-ERR ' + (e && e.message ? e.message : String(e));
    }
  }

  function init() {
    try {
      const sel = $('scanCertType');
      for (const k of CERT_ORDER) {
        const o = document.createElement('option');
        o.value = k;
        o.textContent = CERT_LABEL[k];
        sel.append(o);
      }
      $('scanFile').onchange = () => {
        const f = $('scanFile').files;
        if (f && f.length) uploadFiles(f);
        $('scanFile').value = '';
      };
      $('scanApply').onclick = applyToForm;
      $('scanDiscard').onclick = () => { $('scanPreview').hidden = true; setState_('已放弃本次识别结果。'); };
      setupDrop();
      probe().then(ok => { if (location.hash.indexOf('scantest') >= 0 && ok) selfTest(); });
    } catch (e) {
      setState_('证件识别模块初始化失败：' + (e && e.message ? e.message : String(e)), 'text-danger');
    }
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
