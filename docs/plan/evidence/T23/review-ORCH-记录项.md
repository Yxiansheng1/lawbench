# T23 第二轮九条记录项 · 主编排亲核记录（2026-10-02 10:52 (+08:00)，无人值守窗）

- target：line-C `0ecff5c`（注记 0930 九条，含 T15 两条）；16 文件 +319/-70
- 核法：独立克隆 `rv-C23`，C 线解释器 `-B`，TEMP 短路径。
- diff 核对：`_altchunk_external` 读部件包 try → ParseError；转换时被拒材料进 `skipped`；`_has_afchunk`（有 aFChunk 关系一律不交 Word/WPS）；查加密两处用例；跳过原因文字统一；`.md` 拒绝 `message` 写明材料与原因——为此 `ApiError` 加可选 `detail`（替换通用提示、不进日志）、`fail_body` 带 message（**附带改动，接受**：错误码不变、契约 message 为字符串、日志仍只记码）；文件头文档字符串；T15 `_HTML_TAG` 限长、`_ends_link` 找首个含 w:t/fldChar 的 run。
- `test_convert` + `test_archive` + `test_export` + `test_redline` + `test_main`：113 passed / 1 skipped（真 Word 那条）。
- 变异：`_has_afchunk` 关系判断改 False → `test_convert` 1 failed；复原后树净。
- 结论：**通过**。随 line-C 整体合并（候 N56）。
