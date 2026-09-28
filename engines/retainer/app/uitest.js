'use strict';
/*
 * UI 端到端自检
 *
 * 地址栏加 #uitest 触发：依次以「固定 / 半风险 / 全风险」三种收费模式生成合同，
 * 把每一步结果写进 document.title，供无头浏览器读取判定。
 * 不带 #uitest 时本脚本不做任何事。
 */
(() => {
  if (location.hash.indexOf('uitest') < 0) return;
  const $ = id => document.getElementById(id);
  const R = window.Retainer;
  const steps = [];
  const done = (tag, extra) => { document.title = tag + ' ' + steps.join(' | ') + (extra ? ' | ' + extra : ''); };
  const sleep = ms => new Promise(r => setTimeout(r, ms));

  const FEE = [['固定', '25000元'], ['半风险', '前期2万+12.5%'], ['全风险', '回款额的15%']];

  /* 刑事案件的委托合同不含收费模式锚点，不应被注入民商事收费条款。
     若 generate 的注入条件写漏 case_type，此处会因「未找到收费条款锚点」而失败。 */
  async function criminalCheck() {
    const st = RETAINER_UI.getState();
    const rec = st.records[st.index];
    if (!rec) return 'criminal:no-record';
    Object.assign(rec.row, {
      case_type: '刑事', party_type: '个人',
      plaintiff: '测试张三', defendant: '测试李四', cause: '集资诈骗',
      fee_desc: '30000元', fee_type: '自动识别', stage: '侦查',
      court: '', legal_rep: '', legal_rep_position: '', detention: '测试看守所'
    });
    RETAINER_UI.setState(st);
    await sleep(200);
    $('checkCase').click();
    await sleep(300);
    $('generate').click();
    await sleep(2500);
    return 'criminal[files=' + $('outputFiles').children.length
      + '][notice=' + ($('notice').textContent || '').replace(/\s+/g, ' ').slice(0, 60) + ']';
  }

  /* 构造一个模拟 3.3.0 的工作包（旧 feeClauses 结构、旧模板组名、旧版本号），
     验证变通导入：只接收案件数据，模板与收费条款改用本版内置资源。 */
  async function legacyImportCheck() {
    const cur = await R.pack('work', RETAINER_UI.getState());
    const z = await JSZip.loadAsync(cur);
    const payload = JSON.parse(await z.file('payload.json').async('string'));
    payload.version = '3.3.0';
    payload.config.version = '3.3.0';
    payload.config.feeClauses = {
      fixed: '六、经双方商定，本合同律师费约定如下：{{UPFRONT_FEE}}。',
      semi_risk: '六、经双方商定，本合同律师费约定如下：{{UPFRONT_FEE}}／{{RISK_RATE}}。'
    };
    payload.rules.version = '3.3.0';
    payload.templates = payload.templates.map(t => Object.assign({}, t, { group: t.group.replace('个人委托', '个人-固定') }));
    const nb = new TextEncoder().encode(JSON.stringify(payload));
    const nz = new JSZip();
    nz.file('payload.json', nb);
    nz.file('manifest.json', JSON.stringify({ format: 'retainer-offline', version: '3.3.0', kind: 'work', sha256: await R.hash(nb) }));
    const legacy = await nz.generateAsync({ type: 'uint8array' });
    const p = await R.unpack(legacy, 'work');
    return 'legacyImport=from' + (p.importedFrom || '?') + ',records=' + p.state.records.length + ',templates=' + p.templates.length;
  }

  async function runOne(feeType, feeDesc) {
    const st = RETAINER_UI.getState();
    const rec = st.records[st.index];
    if (!rec) return feeType + ':no-record';
    Object.assign(rec.row, {
      case_type: '民商事', party_type: '个人',
      plaintiff: '测试张三', defendant: '测试李四', cause: '买卖合同纠纷',
      fee_desc: feeDesc, fee_type: feeType, stage: '一审',
      court: '测试人民法院', legal_rep: '测试王五', legal_rep_position: '经理'
    });
    RETAINER_UI.setState(st);
    await sleep(200);
    $('checkCase').click();
    await sleep(300);
    const checked = $('caseCheck').textContent.replace(/\s+/g, ' ').slice(0, 60);
    $('generate').click();
    await sleep(2500);
    const files = $('outputFiles').children.length;
    const notice = ($('notice').textContent || '').replace(/\s+/g, ' ').slice(0, 50);
    return feeType + '[check=' + checked + '][files=' + files + '][notice=' + notice + ']';
  }

  setTimeout(async () => {
    try {
      if (!R || !window.RETAINER_UI) return done('UITEST-FAIL', 'missing globals');
      steps.push('templates=' + R.templates.length);
      steps.push('groups=' + [...new Set(R.templates.map(t => t.group))].join('/'));
      try { R.validateConfig(R.config, R.rules); steps.push('validateConfig=ok'); }
      catch (e) { steps.push('validateConfig=FAIL[' + (e && e.message ? e.message : String(e)) + ']'); }
      try {
        const g = await RETAINER_UI.integrity();
        steps.push('integrity=' + (g.success ? 'ok' + g.details.length : 'FAIL[' + g.errors.join(';').slice(0, 90) + ']'));
      } catch (e) { steps.push('integrity=ERR[' + (e && e.message ? e.message : String(e)) + ']'); }
      try { steps.push(await legacyImportCheck()); }
      catch (e) { steps.push('legacyImport=FAIL[' + (e && e.message ? e.message : String(e)) + ']'); }
      try { steps.push(await criminalCheck()); }
      catch (e) { steps.push('criminal=FAIL[' + (e && e.message ? e.message : String(e)) + ']'); }
      for (const [ft, fd] of FEE) steps.push(await runOne(ft, fd));
      done('UITEST');
    } catch (e) {
      done('UITEST-FAIL', e && e.message ? e.message : String(e));
    }
  }, 1800);
})();
