# T14 派修 · 导出 docx"兼容性模式"（线 C，`5bf892d`，T15）· 主编排亲核记录

- 来件：`致ORCH-C-交回-T14派修docx-1553.md`；target → main cherry-pick
- 落件时刻：2026-10-03 16:06 (+08:00)
- 原因（线 C 查明、我读代码核实）：导出模板由 pandoc reference.docx 改出，`settings.xml` 无 `w:compat` → Word 按 12 显示兼容性模式；归档用 python-docx 默认底板为 14。
- 修法：`export\compat.py` `set_compat15`（只改 compatibilityMode、其余 compat 项保留、插入位置按 CT_Settings 顺序）；两内置模板重生成（逐部件比对只 settings.xml 变）；归档默认底板生成的三种文书设 15，**律所模板生成的保留其自身设置**（不替律所改模板，交付说明写了 Word 里"转换"另存的做法）；修订版就地改、逻辑不动。
- 测试：main 上 test_export + test_redline + test_archive **86 passed**；我把 MODE 改 14 → 2 红、复原；线 C 用 Word 16 后台核旧样本 12 → 新 15。
- **通过。**
---

# T14 派修 · 存过正式草稿不留 `进行中.md`（线 B，`37b5160`，T15）· 主编排亲核记录（2026-10-03 16:27 (+08:00)）

- cherry-pick 到 main `0c23086`（交付说明与线 C 兼容模式一节冲突，两节都保留）。改动 6 行产品代码（`tools\drafts.py` save_draft 成功后删、`case\task.py` task/end 有正式草稿再删一次）+ 1 例。
- main 上 `test_t8_rework.py` 35 passed；我去掉 save_draft 处的删除 → 该例红；复原干净。无正式草稿仍改名 `未完成-*`、硬退出保留——与 Spec 一致。
- 线 B 附带判断：T14 第 10 步两次取消未见 `未完成-*.md` 不是缺陷，同意；慢场景已在 A 第二次实跑令里。
- **通过。**
