"""使用 395 的 9B 抽取（Spec 9.1"使用 395 的 9B"、6.4；契约 prep395/extract.schema.json；F-ENT-04）。

律师勾选"使用 395 抽取"时，在逐份材料写摘要之前：
- 只对位置单位为页、段、行的非表格类材料做；每份材料按单元切成不超过 16000 字的段（带位置标记）。
- 每份材料第一段做一次分类（classify），每段做一次字段抽取（fields：当事人、日期、金额、案号）。
- 核对：每个字段的值要能在它标的位置原样找到（与引语核对同一口径：归一化、去空白、引号统一），找不到的丢弃并记数。
- 核对不过的比例高于 20%，或 395 不可用（连不上、非 200、返回不合契约），这一步整体跳过，全部由 27B 完成，
  记一条提示（写进运行记录和 wiki 日志；status 接口没有放提示的字段）。
- 通过的字段按段交给摘要步骤，作为参考输入（摘要仍要带出处、照常核对）。395 的调用不计入 6000D 的调用预算。
请求头带律师 Key（与 6000D 同一个 Key，395 用它校验）；日志只记元数据。
取消（T16 返修 P2-1）：与 6000D 同一个取消标志；每段请求前查一次，在途请求单独一个 client，取消即关掉。
"""
from __future__ import annotations

import threading

import httpx

from .. import contracts, logs
from ..checks import evidence
from ..errors import ApiError
from .llm import Cancelled, abortable

MAX_CHARS = 16000
FIELDS = ["当事人", "日期", "金额", "案号"]
CATEGORIES = ["起诉意见书", "讯问笔录", "询问笔录", "书证", "鉴定意见", "合同", "其他"]
FAIL_RATIO = 0.2
TIMEOUT = 600.0
SCHEMA = "prep395/extract.schema.json"
WORD = {"page": "页", "para": "段", "line": "行"}


class Unavailable(Exception):
    pass


class Prep:
    def __init__(self, net, key_getter, cancel: threading.Event | None = None):
        self.net = net
        self.key_getter = key_getter
        self.cancel = cancel or threading.Event()
        self.note: str | None = None
        self.stats = {"字段": 0, "核对不过": 0, "调用": 0}

    def _post(self, body: dict) -> dict:
        key = self.key_getter()
        if not key:
            raise Unavailable("no_key")
        try:
            r = self._send(body, {"Authorization": f"Bearer {key}"})
        except (ApiError, httpx.HTTPError) as e:
            raise Unavailable(type(e).__name__) from None
        self.stats["调用"] += 1
        if r.status_code != 200:
            raise Unavailable(f"http_{r.status_code}")
        try:
            data = r.json()
        except ValueError:
            raise Unavailable("bad_json") from None
        if contracts.errors(SCHEMA, "#/$defs/response", data):
            raise Unavailable("response_contract")
        return data

    def _send(self, body: dict, headers: dict) -> httpx.Response:
        """与 Net.request 相同（连不上时重新选址再发一次），只是每次一个 client、可被取消标志打断。"""
        for attempt in (0, 1):
            if self.cancel.is_set():
                raise Cancelled()
            base, _ = self.net.select("prep", force=attempt > 0)
            client = self.net.own_client()

            def go():
                try:
                    return client.post(base + "/v1/extract", json=body, headers=headers, timeout=TIMEOUT)
                finally:
                    client.close()

            try:
                return abortable(go, self.cancel, TIMEOUT, client.close)
            except (httpx.ConnectError, httpx.ConnectTimeout):
                self.net.invalidate("prep")
                if attempt:
                    raise
        raise AssertionError("unreachable")

    def run(self, mats: list) -> tuple[dict[str, list[tuple[int, str]]], dict[str, str]]:
        """(材料编号 → 通过核对的参考字段行, 材料编号 → 分类)。不可用或核对不过太多时返回两个空表。"""
        refs: dict[str, list[tuple[int, str]]] = {}
        cats: dict[str, str] = {}
        try:
            for m in mats:
                unit = m.meta["unit"]
                if m.table or unit not in WORD:
                    continue
                for i, (text, nos) in enumerate(_chunks(m)):
                    if i == 0:
                        data = self._post({"task": "classify", "text": text, "categories": CATEGORIES})
                        cats[m.mid] = data["result"]["category"]
                    data = self._post({"task": "fields", "text": text, "fields": FIELDS})
                    for f in data["result"]:
                        self.stats["字段"] += 1
                        no = _loc_no(f["loc"], unit)
                        if no is None or no not in nos or not _found(m, unit, no, f["value"]):
                            self.stats["核对不过"] += 1
                            continue
                        refs.setdefault(m.mid, []).append(
                            (no, f"- {f['field']}：{f['value']}〔{m.name} 第{no}{WORD[unit]}〕"))
        except Unavailable as e:
            self.note = "395 不可用，本次全部由 27B 完成"
            logs.event("pipeline", "prep", status="fail", error=str(e))
            return {}, {}
        n, bad = self.stats["字段"], self.stats["核对不过"]
        if n and bad / n > FAIL_RATIO:
            self.note = f"395 抽取的字段核对不过 {bad}/{n}，高于 20%，本次全部由 27B 完成"
            return {}, {}
        return {mid: sorted(v) for mid, v in refs.items()}, cats


def _chunks(m) -> list[tuple[str, set[int]]]:
    from .steps.wiki import _render
    out, cur, size = [], [], 0
    for u in m.units:
        n = len(u.text) + 12
        if cur and size + n > MAX_CHARS:
            out.append(cur)
            cur, size = [], 0
        cur.append(u)
        size += n
    if cur:
        out.append(cur)
    return [(_render(c, m.meta["unit"])[:MAX_CHARS], {u.no for u in c}) for c in out]


def _loc_no(loc: str, unit: str) -> int | None:
    if not loc.startswith("第") or not loc.endswith(WORD[unit]):
        return None
    try:
        return int(loc[1:-1])
    except ValueError:
        return None


def _found(m, unit: str, no: int, value: str) -> bool:
    v = evidence.squash(value)
    if not v:
        return False
    text = "\n".join(u.text for u in m.units if u.no == no)
    return v in evidence.squash(text)


def attach(run, net, key_getter, cancel: threading.Event | None = None) -> None:
    run.prep = Prep(net, key_getter, cancel)
