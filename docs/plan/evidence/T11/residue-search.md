# 395 残留检查（2026-09-30 15:1x，用户在 395 管理员窗口执行 residue_395 的命令，输出由用户贴回）

- 在 G5/G6 实测（23 页虚构扫描件 ×3 轮并发 + 9B 抽取）和 dewatermark_395 之后执行。
- 搜索根：C:\prep395、C:\Windows\Temp、各用户 AppData\Local\Temp、C:\llama*（无）。
- `FILES: 96098`；**无 `HIT:` 行**（8 个虚构材料特征串 utf8 / unicode 均未命中）。
- `PREP395_TEMP_PREFIX: 7`：逐个核对，全是程序文件，不是临时文件残留：
  - C:\prep395\python\Lib\site-packages\prep395-1.0.0.dist-info
  - C:\prep395\services\prep395-llm9b.exe / .xml / .wrapper.log
  - C:\prep395\services\prep395-ocr.exe / .xml / .wrapper.log
  已改 residue_395 的命令：计数时排除 C:\prep395\services\ 与 C:\prep395\python\（这两处按名字以 prep395- 开头是正常的）。按新规则此次计数为 0。
- `*.wrapper.log`（各约 1.1 KB）：WinSW 在 install / uninstall 命令时写的记录（"Installing service …"之类），不含请求内容；服务运行时 `<log mode="none"/>` 生效。README 已据实改写。
- access.log 抽 3 行：只有 ts、key（Key 指纹 8 位）、api、pages、bytes、elapsed_ms、status、err 八个字段。
- 未判：BitLocker（用户 2026-09-30 15:03 决定暂缓），所以人工单"通过"条件里的"BitLocker 已开"这一条本次不满足。
