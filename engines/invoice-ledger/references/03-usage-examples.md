> 历史结构参考。3.8.0的金额、身份、去重和授权规则见[当前工作流](08-current-workflow.md)，旧示例不作当前验收依据。

# 命令示例与实测数据基线

## 查看帮助

```bash
# 查看所有命令
python scripts/invoice_db.py --help

# 查看各子命令帮助
python scripts/invoice_db.py init --help
python scripts/invoice_db.py import --help
python scripts/invoice_db.py mark-reimbursed --help
python scripts/invoice_db.py report --help
python scripts/dedupe_check.py --help
```

## 初始化台账（**仅首次建库**）

> **3.0.0 起语义变更**：`init` 只在主台账**不存在**时用于建库。
> 主台账已存在时会被拒绝（exit 1）——台账**只做增量、不做删减**。
> 日常录入一律用 `import`；确需从模板重建，用 `--out` 生成候选台账（不触碰主台账）。

```bash
# 首次建库（主台账不存在时）
python scripts/invoke.py invoice_db.py init \
  --src "/path/to/统计表所在目录" \
  --batch "8月" \
  --reimbursed \
  --full-nums-json "/path/to/_dup_check_rmb.json"

# 已建库后确需重建 → 生成候选台账到 _候选台账/，主台账不受影响
python scripts/invoke.py invoice_db.py init \
  --src "/path/to/统计表所在目录" \
  --batch "8月" --reimbursed \
  --out "候选_8月_20260916.xlsx"
```

- `--reimbursed`：强制所有行状态=已报（8月全部已报销）
- `--full-nums-json`：JSON 文件格式 `{全号: 路径}`，用于补全 20 位全号列
- 自动对账：台账合计 ≠ 模板合计 → exit 1
- **拒绝的三种情形**：主台账已存在却未给 `--out`；`--out` 指向主台账本体；
  `--src` 目录内含台账本体（防止把台账当模板，丢掉第 7~9 列）

## 导入新发票

```bash
# 目录导入（自动取目录名作为批次）
python scripts/invoice_db.py import --src "/path/to/2026-01第一批" --batch "2026-01第一批"

# 单文件导入（--batch 必填，防孤儿数据）
python scripts/invoice_db.py import --src "/path/to/一张发票.pdf" --batch "2026-01第一批"

# 启用图片 OCR（winsdk 已内置，目标 Windows 需有中文 OCR 语言功能）
python scripts/invoice_db.py import --src "/path/to/图片目录" --batch "2026-01第一批" --img
```

## 标记已报销

```bash
# 预览（默认 dry-run）
python scripts/invoice_db.py mark-reimbursed --batch "2026-01第一批"

# 执行标记
python scripts/invoice_db.py mark-reimbursed --batch "2026-01第一批" --apply

# 月级匹配（标记 8月全部批次）
python scripts/invoice_db.py mark-reimbursed --batch "2026-01" --month --apply

# 前缀匹配
python scripts/invoice_db.py mark-reimbursed --batch "2026-01" --prefix --apply
```

## 独立查重（不依赖台账）

```bash
# 单目录内部查重
python scripts/dedupe_check.py --dir "/path/to/目录"

# 两目录交叉查重
python scripts/dedupe_check.py --dir "/path/to/A" --dir "/path/to/B"

# 目标目录 vs 历史已报根（自动排除目标自身）
python scripts/dedupe_check.py \
  --target "/path/to/2026-01第一批" \
  --history-root "/path/to/2026年"

# 可选对比 8月已报 JSON
python scripts/dedupe_check.py --dir "/path/to/新下载" --json8 "/path/to/_dup_check_rmb.json"
```

## 台账结构体检（只读）

```bash
python scripts/invoke.py invoice_db.py check-schema
```

输出：主表行数/列数、**额外列**（写盘时会被保留）、冲突记录表是否存在及待裁/已归档条数、
状态分布与白名单校验。

**只读**——体检前后台账字节数必须一致（脚本内置 I2 断言；不一致即 exit 1）。

## 冲突与重复的处置

导入判定分三类（判定表见 `02-dedup-logic.md`）：

| 判定 | 落点 | 你要做什么 |
|---|---|---|
| **新增** | 主表 | 无 |
| **重复**（关键字段一致）| 仅冲突记录表留痕 `已归档` | 无（保留溯源，便于日后回答"这张票在哪批被跳过"）|
| **冲突**（关键字段矛盾）| 冲突记录表 `待裁`，**不进主表**，exit 2 | **需裁定**：核对发票本体后手工处理 |

```bash
# 看待裁冲突
python scripts/invoke.py invoice_db.py check-schema          # 体检会报告待裁条数
python scripts/invoke.py invoice_db.py report                # 末行：冲突记录：待裁 N 条 / 已归档 M 条

# 裁定（唯一入口；默认 dry-run，加 --apply 执行）
python scripts/invoke.py invoice_db.py resolve-conflict --index 2 --decision 维持台账   # 预览
python scripts/invoke.py invoice_db.py resolve-conflict --id CF-20260917-0001 \
       --decision 采纳新值 --note "以发票本体为准" --apply
```

`--decision` 三选一：

| 裁定 | 对主表所涉行的处理 |
|---|---|
| `采纳新值` | 原行置 `已取代`（不计入合计）＋ 追加一行按发票新值（状态 `未报`）|
| `维持台账` | 状态还原为冲突前的「原状态」|
| `剔除` | 原行置 `重复-剔除`（不计入合计）|

> 冲突检测时即把所涉主表行标为 `冲突-待裁` → **其金额暂不计入合计**，裁定后归位。
> 三种裁定都会把冲突记录置 `已归档` 并填写 `裁定结果` / `裁定时间`。
> 核定后建议接着跑 `check-schema` 复核状态分布与合计口径。

## 数据内置与跨设备迁移

**发票主台账.xlsx 默认存放在技能根目录**（`~/.workbuddy/skills/invoice-ledger-db/发票主台账.xlsx`），与脚本一起随技能迁移。
**3.0.0 起运行环境亦内置**（`vendor/env-win_amd64.zip`，自含解释器与依赖）——
3.6.0 起用 `package_skill.py --include-ledger --out <技能外新zip路径>` 制作个人迁移包；展开缓存不随包走，新设备按指纹重建。启动需宿主 Python 3.10+，宿主无需安装业务 Python 包。

```bash
# 默认模式（推荐）：不设任何参数，读写技能内置台账
python scripts/invoke.py invoice_db.py import --src "新发票目录" --batch "2026-01第一批"
python scripts/invoke.py invoice_db.py report
```

**指定台账位置（仅特殊场景需要）**：

```bash
# 方式1：--ledger 参数（把台账独立于技能存放）
python scripts/invoice_db.py import --src "..." --ledger "/path/to/发票数据库"

# 方式2：环境变量
export INVOICE_LEDGER_DIR="/path/to/发票数据库"
python scripts/invoice_db.py import --src "..."
```

**主库与归档区的关系**：
- **数据主库（唯一权威）** = 技能内置 `发票主台账.xlsx`（全量记录、状态、查重结论）
- **归档区**（坚果云 2026年/ 各月份文件夹）= 发票 PDF 原件存放处（按需备份），供 import 扫描提取，**不是数据主库**
- 迁移换设备：整体拷贝技能目录（含 发票主台账.xlsx）+ 可选拷贝发票 PDF 归档区；主库数据不丢、不依赖原设备路径

## 行为基线（具体数值已脱敏）

| 项 | 值 |
|----|-----|
| 主台账总条数 | 示例：200+ 条（含已报与未报） |
| 金额合计 | 略（涉及真实金额，不随发布包提供） |
| 全号覆盖率 | 100% |
| 当期 vs 上期 重复 | 0 |
| 当期 vs 全部历史 | 0（历史根排除当期自身） |
| 幂等导入 | 重导 → 全判重复、0 新增、exit 2 |
| 状态机 | 已报批次 mark --apply → 0 变更、整批跳过 |
| 数据库完整性 | 全量行 × 9 字段无空值 |

### 历史已报月份内部重复（⚠ 非本次问题，记录供参考）

历史存档中曾发现同号重复，常见模式（示例已脱敏）：
- 同月份不同批次重复
- 跨月份重复
- 相邻月份多组重复

> 建议用 `dedupe_check.py` 定位后由用户确认是否需要清理历史重复。

## 报销体系目录约定（供参考，路径可自定义）

```
报销体系根/
├── 2026年/
│   ├── M月（已报）第一批/      ← 旧命名：差旅费234.56-0001.pdf
│   ├── M月（已报）/            ← 批次目录名含"已报"表示已报销
│   ├── M月（已报）/第一批/
│   ├── M月（已报）/第一批/ 第二批/ 第三批/
│   ├── M月/年M月报销/          ← 多批次
│   └── M月/年M月报销/          ← 单批次（平铺目录）
```

> 初始化时，目录名含"已报"可自动识别为已报；或用 `--reimbursed` 强制全部已报。
## 回归自检（改代码后）

```bash
for f in scripts/tests/*.py; do python "$f"; done
```

样本数据根默认 `<历史样本目录>`，可用 `INVOICE_TEST_SAMPLES` 覆盖。
当前基线：**121 项全过**（env ✓／batch1 16／batch2 10／batch3 18／batch4 14／batch5 14／audit 21／virtual 28）。
