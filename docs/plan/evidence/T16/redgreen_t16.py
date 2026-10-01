r"""T16 流水线与案件 wiki 红绿：逐条改坏即红、复原即绿。复用 T3 的 redgreen.py。

用法（在 service\ 目录）：.venv\Scripts\python ..\docs\plan\evidence\T16\redgreen_t16.py
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

_spec = importlib.util.spec_from_file_location(
    "redgreen_t3", pathlib.Path(__file__).resolve().parents[1] / "T3" / "redgreen.py")
rg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rg)

R = "tests/test_pipeline.py"
W = "pipeline/steps/wiki.py"
rg.TITLE = "T16 红绿验证"
rg.MUTATIONS = [
    ("律师修改块放回原位置", W, [("            if blocks:\n                text = put_lawyer_blocks(text, blocks)\n",
                                   "            pass\n")], f"{R} -k lawyer_blocks_kept"),
    ("更新只重跑变化材料", W, [('        if self.step == "wiki_update" and card is not None:', "        if False:")],
     f"{R} -k update_reruns_only_changed"),
    ("全新生成重跑全部材料", W, [("            redo = list(mats)\n", "            redo = []\n")],
     f"{R} -k build_reruns_everything"),
    ("表格类材料由程序筛选、不经模型", W, [("        mat.table = is_table(mat)", "        mat.table = False")],
     f"{R} -k table_material"),
    ("摘要里的出处补上材料名", W, [("expand=lambda t: expand_short(t, m.name)", "expand=None")], f"{R} -k test_build"),
    ("卡片出处不合格的丢掉", W, [("cites = [c for c in given if pat.match(c) and self._cite_ok(c, text)]",
                                 "cites = [c for c in given if pat.match(c)]")], f"{R} -k test_build"),
    ("卡片出处和条目文字一起核（不只看格式）", W, [('        return not any(p["class"] in "ABCDE" and p["severity"] == "must_fix"',
                                              '        return not any(p["class"] in "E" and p["severity"] == "must_fix"')],
     f"{R} -k test_build"),
    ("到预算时保存已完成的部分", "pipeline/runner.py", [("            exc.partial = out", "            exc.partial = None")],
     f"{R} -k budget_stop"),
    ("调用次数上限", "pipeline/runner.py", [("            if self.calls >= self.max_calls:", "            if False:")],
     f"{R} -k budget_stop"),
    ("修改只交问题句", "pipeline/runner.py", [
        ("            req = self.fix_request(bad, sources)",
         "            req = self.fix_request([(i, ln, []) for i, ln in enumerate(text.splitlines())], sources)")],
     f"{R} -k fix_round"),
    ("修改结果按序号换回原句", "pipeline/runner.py", [("                lines[i] = expand(new) if expand else new", "                pass")],
     f"{R} -k fix_parser"),
    ("取消", "pipeline/__init__.py", [("        live.cancel.set()\n        return {}", "        return {}")], f"{R} -k cancel"),
    ("服务重启后状态读 result.json", "pipeline/__init__.py", [
        ('        return {"status": STATUS_OF_RESULT.get(res["status"], "failed"),', '        return {"status": "failed",')],
     f"{R} -k status_after_restart"),
    ("同一案件在跑时不另起一次", "pipeline/__init__.py", [
        ('                    if live.case_id == case_id and live.progress.status == "running":', "                    if False:")],
     f"{R} -k second_run"),
    ('"高"发 xhigh', "pipeline/llm.py", [('EFFORT = {"低": "low", "中": "medium", "高": "xhigh"}',
                                         'EFFORT = {"低": "low", "中": "medium", "高": "high"}')], f"{R} -k request_shape"),
    ("401 报 KEY_INVALID", "pipeline/llm.py", [("    if r.status_code in (401, 403):", "    if False:")],
     f"{R} -k 'key_invalid or http_error'"),
    ("采纳与驳回分开记", "wiki/suggestions.py", [('        s["status"] = "accepted" if accept else "rejected"',
                                               '        s["status"] = "accepted"')], f"{R} -k wiki_suggestions"),
    ("失败材料照抄导入时的原因", W, [('            skipped.append((m, m.get("error") or "无法处理"))',
                                     '            skipped.append((m, "无法处理"))')], f"{R} -k failed_reason"),
    ("程序统计行的出处合并成范围", W, [('"、".join(f"{m.name} {p}" for p in _ranges(places)[:20])',
                                      '"、".join(f"{m.name} {p}" for p in places[:20])')], f"{R} -k table_summary_cites"),
    ("9B·核对不过超 20% 整体跳过", "pipeline/prep.py", [("        if n and bad / n > FAIL_RATIO:", "        if False:")],
     f"{R} -k prep_skipped"),
    ("9B·字段要在所标位置原样找到", "pipeline/prep.py", [
        ('                        if no is None or no not in nos or not _found(m, unit, no, f["value"]):',
         "                        if False:")], f"{R} -k prep_skipped"),
    ("9B·395 不可用整体跳过", "pipeline/prep.py", [('            raise Unavailable(f"http_{r.status_code}")',
                                               '            return {"task": "fields", "result": [], "elapsed_ms": 0}')],
     f"{R} -k prep_skipped"),
    ("9B·表格类材料不送", "pipeline/prep.py", [("                if m.table or unit not in WORD:",
                                             "                if unit not in WORD:")], f"{R} -k prep_skips_table"),
    ("9B·通过的字段交给摘要步骤", W, [("        if refs:\n", "        if False:\n")], f"{R} -k prep_good"),
    ("卡片被截断时精简重试一次", W, [("        if not data:\n            # 输出被截断或不是 JSON",
                                      "        if False:\n            # 输出被截断或不是 JSON")],
     f"{R} -k card_truncated_once"),
    ("卡片还是不行：不写空卡片、记失败", W, [("        if not data:\n            # 还是不行",
                                          "        if False:\n            # 还是不行")],
     f"{R} -k card_truncated_twice"),
    ("修改轮用完后程序兜底", "pipeline/runner.py", [("        text = self.settle(text, obj)\n", "")], f"{R} -k settle_b_moves"),
    ("兜底·A 类插注原文写法、不动出处", "pipeline/runner.py", [
        ("                        new = new.replace(cite, note + cite, 1) if cite and cite in new else new.rstrip() + note",
         "                        pass")], f"{R} -k settle_per_class"),
    ("兜底·C 类只改有问题的那组出处", "pipeline/runner.py", [
        ('                    new = new.replace(p["citation"], "〔未找到依据〕", 1)', "                    pass")],
     f"{R} -k settle_per_class"),
    ("兜底·还不过时整句改标未找到依据", "pipeline/runner.py", [
        ('                new = _replace_cites(line, "〔未找到依据〕")\n                if new == line:',
         "                new = line\n                if new == line:")], f"{R} -k settle_unfixable"),
    ("原件已删除的材料清单注明", W, [('"原件已删除（保留材料文本）" if m.meta["status"] == "source_deleted" else ""', '""')],
     f"{R} -k deleted_originals"),
]

# ---- 返修（执行令 20261001-2147） ----
L = "pipeline/llm.py"
N = "pipeline/runner.py"
P = "pipeline/prep.py"
I = "pipeline/__init__.py"
rg.MUTATIONS += [
    ("P2-1 等响应头时取消：后台读、本线程查取消", L, [
        ("        return abortable(read, self.cancel, REQUEST_SECONDS, client.close, self.clock)", "        return read()")],
     f"{R} -k 'cancel_while_waiting or cancel_closes'"),
    ("P2-1 取消时关掉连接（服务端看到断开）", L, [
        ("        return abortable(read, self.cancel, REQUEST_SECONDS, client.close, self.clock)",
         "        return abortable(read, self.cancel, REQUEST_SECONDS, None, self.clock)")], f"{R} -k cancel_closes"),
    ("P2-1 395 阶段也能取消", P, [("                return abortable(go, self.cancel, TIMEOUT, client.close)",
                                 "                return go()")], f"{R} -k cancel_during_395"),
    ("P2-2 开跑前建好目录", W, [('            gate.mkdir_work(self.root, rel, op="pipeline")', "            pass")],
     f"{R} -k dirs_made"),
    ("P2-3 锁内按案件占位", I, [("                if other is None:", "                if True:")],
     f"{R} -k same_case_started"),
    ("P2-4 停下不覆盖完整页", W, [('            keep = old == "full" or', '            keep = False and')],
     f"{R} -k stop_keeps_complete"),
    ("P2-4 半份页首注明部分", W, [('f"{PARTIAL_HEAD}{k_n}，运行中止，没有读完")', "None)")],
     f"{R} -k stop_without_old_page"),
    ("P2-4 停下时重写材料清单", W, [("            self._inventory(mats, skipped, summaries, partial, kept_old, stopped=True, stale=stale)\n", "")],
     f"{R} -k stop_without_old_page"),
    ("P3-1 运行记录对象写材料编号", W, [('f"{m.mid}#{i + 1}",', 'f"{m.name}#{i + 1}",')], f"{R} -k run_record"),
    ("P3-1 兜底记录不写原句", N, [('            done.append(f"第{i + 1}行 " + "、".join(dict.fromkeys(acts)))', "            done.append(line)")],
     f"{R} -k run_record"),
    ("P3-2 进程内最多 2 路", L, [("_slots = threading.BoundedSemaphore(SLOTS)", "_slots = threading.BoundedSemaphore(4)")],
     f"{R} -k two_cases"),
    ("P3-3 修改最多 2 轮", N, [("MAX_FIX = 2", "MAX_FIX = 3")], f"{R} -k fix_rounds_at_most"),
    ("P3-3 改完没变化就停", N, [("            if _same(new, text):\n                break", "            if False:\n                break")],
     f"{R} -k fix_stops"),
    ("P3-3 45 分钟上限", N, [("            if self.clock() - self.started - self.queue_s > self.minutes * 60:", "            if False:")],
     f"{R} -k minutes_limit"),
    ("P3-3 排队时间不计时", N, [("        self.budget.waited(t_call + local, (reply.queue_wait_ms or 0) / 1000)", "")],
     f"{R} -k queue_wait_not"),
    ("P3-3 预算公式", I, [("    return segments * 3 + articles * 3 + 10", "    return segments * 2 + articles * 3 + 10")],
     f"{R} -k test_build"),
    ("P3-3 6000D 地址经 Net 选", L, [('                base, _ = self.net.select("llm", force=attempt > 0)',
                                    '                base = self.net.candidates("llm")[0][0]')], f"{R} -k net_selection"),
    ("P3-3 律师确认的条目保留", W, [('            kept = [f for f in (old or {}).get(key, []) if f["status"] == "lawyer_confirmed"]',
                                  "            kept = []")], f"{R} -k lawyer_confirmed"),
    ("P3-3 本方立场保留", W, [('                "stance": (old or {}).get("stance"),', '                "stance": None,')],
     f"{R} -k lawyer_confirmed"),
    ("P3-3 9B 阈值 20%", P, [("FAIL_RATIO = 0.2", "FAIL_RATIO = 0.9")], f"{R} -k prep_threshold"),
    ("P3-3 更新时补跑没有完整摘要页的材料", W, [("or not self._complete_page(m)]", "or False]")],
     f"{R} -k update_reruns_missing"),
    ("P3-3 卡片 finish=length 不算成功", W, [
        ('"案件卡片", "案件卡片")\n        data = _json_object(raw) if finish != "length" else {}',
         '"案件卡片", "案件卡片")\n        data = _json_object(raw)')], f"{R} -k card_length_finish"),
    ("P3-3 status/cancel 查任务类型", I, [
        ('        _, root, task = self.tasks.locate(task_id)\n        if task["kind"] != "pipeline":',
         '        _, root, task = self.tasks.locate(task_id)\n        if False:'),
        ('            _, _, task = self.tasks.locate(task_id)\n            if task["kind"] != "pipeline":',
         '            _, _, task = self.tasks.locate(task_id)\n            if False:')], f"{R} -k status_checks_task_kind"),
    ("P3-4 连续律师块成组", W, [("        if out and end is not None and not old[end:m.start()].strip():", "        if False:")],
     f"{R} -k consecutive_lawyer"),
    ("P3-4 同一位置的几组按原先后", W, [("            after.setdefault(idx, []).append(block)", "            after.setdefault(idx, []).insert(0, block)")],
     f"{R} -k consecutive_lawyer"),
    ("P3-6 窗口超限不发", L, [('        if need > tokens.WINDOWS[params["window"]]:', "        if False:")], f"{R} -k window_exceeded"),
    ("P3-7 旧卡片不合契约整次报错", W, [('            raise ApiError("INVALID_ARGUMENT", "case_card_invalid") from None', "            return None")],
     f"{R} -k bad_old_card"),
    ("NOTE 目录也保护律师块", W, [('        self._write(f"{WIKI}/index.md", "\\n".join(idx) + "\\n")',
                                '        gate.write_bytes(self.root, f"{WIKI}/index.md", ("\\n".join(idx) + "\\n").encode(), op="pipeline")')],
     f"{R} -k index_lawyer"),
    ("NOTE 网络异常映射到 8.3 错误码", L, [
        ('                except httpx.TimeoutException:\n                    raise ApiError("TIMEOUT", "read_timeout") from None\n'
         '                except httpx.HTTPError:\n                    raise ApiError("SERVER_UNREACHABLE", "transport_error") from None\n', "")],
     f"{R} -k network_errors"),
    ("NOTE 某段 401 后其余不再发", N, [("        except (Cancelled, BudgetStop, ApiError) as e:", "        except (Cancelled, BudgetStop) as e:")],
     f"{R} -k key_invalid_stops"),
]

# ---- 小项（执行令 20261001-2352） ----
NET = "net.py"
rg.MUTATIONS += [
    ("小项 P2-A own_client 白名单钩子（复核 M1）", NET, [
        ('transport=self._transport, verify=_ssl_context(),\n            timeout=httpx.Timeout(REQUEST_TIMEOUT, connect=CONNECT_TIMEOUT),\n'
         '            event_hooks={"request": [lambda r: self.allow.check(r.url)], "response": [_check_redirect]})',
         'transport=self._transport, verify=_ssl_context(),\n            timeout=httpx.Timeout(REQUEST_TIMEOUT, connect=CONNECT_TIMEOUT),\n'
         '            event_hooks={"request": [], "response": [_check_redirect]})')], f"{R} -k own_client"),
    ("小项 P2-A own_client 不跟随重定向、3xx 报错（复核 M2）", NET, [
        ('follow_redirects=False, trust_env=False, transport=self._transport, verify=_ssl_context(),\n'
         '            timeout=httpx.Timeout(REQUEST_TIMEOUT, connect=CONNECT_TIMEOUT),\n'
         '            event_hooks={"request": [lambda r: self.allow.check(r.url)], "response": [_check_redirect]})',
         'follow_redirects=True, trust_env=False, transport=self._transport, verify=_ssl_context(),\n'
         '            timeout=httpx.Timeout(REQUEST_TIMEOUT, connect=CONNECT_TIMEOUT),\n'
         '            event_hooks={"request": [lambda r: self.allow.check(r.url)], "response": []})')], f"{R} -k own_client"),
    ("小项 P3-B 旧部分页只有段数更多才覆盖", W, [
        ("(not parts or (not changed and old[0] >= len(parts)))", "(not parts)")], f"{R} -k old_partial_page"),
    ("小项 P3-B 保留旧部分页时清单按旧页写", W, [
        ('                    partial[m.mid] = f"部分（{old[0]}/{old[1]} 段）"     # 清单按磁盘上的旧页写', "                    pass")],
     f"{R} -k old_partial_page_not_replaced"),
    ("小项 P3-C 材料改过的旧页清单写否", W, [("                if changed:\n                    stale.add(m.mid)", "                if False:\n                    stale.add(m.mid)")],
     f"{R} -k changed_material_stopped"),
    ("小项 P3-D log.md 拿 _WIKI_LOCK（复核 M19）", W, [("        with _WIKI_LOCK:                             # 与\"采纳修改建议\"写日志用同一把锁",
                                                  "        if True:")], f"{R} -k log_written_under"),
    ("小项 NOTE 1 等待按墙钟并集扣", N, [("            if end is None or a > end:\n                total += b - a\n                end = b\n"
                                       "            elif b > end:\n                total += b - end\n                end = b",
                                       "            total += b - a")], f"{R} -k waiting_counted_once"),
    ("小项 NOTE 1 等名额不计时（复核 M14）", N, [("        self.budget.waited(t_call, local)\n", "")], f"{R} -k slot_wait_not"),
    ("小项 坏卡片在 log.md 写明", W, [("        except ApiError:\n            # 主编排答复：log.md 写明是哪个文件坏了\n", "        except ApiError:\n            raise\n")],
     f"{R} -k bad_old_card"),
]

_run = rg.run


def _run_no_full(sel: str):
    if sel == "tests":
        return 0, "（本脚本不跑全量，见 T16\\pytest.txt）"
    return _run(sel)


rg.run = _run_no_full

if __name__ == "__main__":
    sys.exit(rg.main())
