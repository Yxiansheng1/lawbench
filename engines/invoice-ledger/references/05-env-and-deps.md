# 05 · 分发环境与本机运行缓存（3.7.0）

## 文件边界

技能内 `vendor/` 只分发 `env-win_amd64.zip` 和 `env.lock`。主台账仍以技能根目录为默认位置，保持既有 --ledger 与 INVOICE_LEDGER_DIR 规则。

展开缓存默认位于 `%LOCALAPPDATA%/invoice-ledger-db/runtimes/win-amd64/<ZIP的SHA256>/`。
可用 INVOICE_RUNTIME_CACHE 指定技能目录之外的绝对缓存根路径。不应将该目录加入技能同步。
每个指纹目录用 active.json 选择一个 gen-随机标识 子目录；只有验收完成的副本才写入 ready.json 并被选择。

## 启动契约

`python scripts/invoke.py invoice_db.py report` 与直接执行业务脚本均走 runtime_cache.py。
命令引导需要宿主 Python 3.10+；业务解释器和 9 个声明依赖由技能携带，宿主不需安装业务依赖。
适用平台为 Windows AMD64。环境无效时退出 1，不静默回落宿主或旧指纹环境。

1. 校验 schema 2 锁文件及 ZIP 大小、SHA256。
2. 按 ZIP 指纹定位缓存，检查完成标记、MANIFEST.tsv 哈希、文件存在性与大小。
3. 缓存不可用时获取进程锁（等待最多 45 秒），再次检查，以防重复展开。
4. 解压到本进程唯一临时目录，校验所有文件哈希，验证解释器版本和 9 个声明依赖（并验证 winsdk OCR 所需命名空间）可导入。
5. 写完成标记，将临时目录改为正式副本，原子替换 active.json。
6. 用缓存解释器运行业务脚本；启动器注入本次技能脚本位置，缓存不保存技能绝对路径。

缓存升级由包指纹决定，与技能版本号独立；只改业务代码不重建环境。_pth 仅含解释器自身、标准库 ZIP 和 Lib\site-packages。运行禁写 .pyc，避免缓存和发布资产混入字节码。

正常启动不逐文件计算哈希；同大小的内容破坏需要深度诊断发现。SHA256 用于本地一致性检查，不是发布者数字签名。

## 诊断与修复

```text
python scripts/env_check.py --deep --ocr
python scripts/runtime_cache.py --repair
```

env_check.py 只读：不创建缓存、不修复文件；尚未建立缓存时显示“环境包有效，缓存尚未建立”。存在缓存时检查其一致性、依赖，以及通过缓存解释器读取台账，避免宿主缺 openpyxl 导致误报。
--deep 额外校验全部文件哈希及额外文件；--quiet 减少输出。
--repair 强制新建副本，通过验收后切换。失败保留原指针，临时目录只清理本次创建的目录。

进程锁由操作系统释放，异常退出不会永久锁住后续启动。崩溃遗留的 .build-* 和旧 gen-* 不会被当作有效缓存；程序不自动删除其他进程可能仍在使用的目录。需要回收旧缓存时先结束相关发票任务，再由维护操作清理指定副本。

## 构建与发布

```text
python scripts/build_env_zip.py --repack
python scripts/build_env_zip.py --py-version 3.12.10
python scripts/package_skill.py --out <技能外新zip路径>
python scripts/package_skill.py --out <个人迁移包路径> --include-ledger
```

--repack 离线校验现有 ZIP 与锁文件，保留依赖版本，更新路径规则、清单与指纹并移除 .pyc；正常构建需要联网且宿主 Python 次版本匹配。请在技能副本中构建、验证完成后部署 ZIP 和锁文件这一对资产；两者更新中间若被读取，启动会拒绝不匹配的组合。

声明依赖：openpyxl、et-xmlfile、pdfplumber、pdfminer.six、pillow、pypdfium2、cryptography、charset-normalizer，版本以 env.lock 为准。winsdk==1.0.0b10 为第 9 个声明依赖，已纳入环境包。采用 Python 3.12.10 AMD64 以匹配发布的 cp312 wheel；不用宿主安装 winsdk。

package_skill.py 先运行一致性校验并验证环境包，按清单选择根说明、元数据、脚本、参考资料和 vendor 两个载荷；检查成品 ZIP 清单及 CRC。排除 vendor/env、临时目录、.pyc、日志、备份、候选台账。默认不含个人主台账，个人离线迁移加 --include-ledger。

## 从 3.5.x 迁移

首次运行从当前 ZIP 新建外部缓存，不信任也不复用旧 vendor/env。新环境通过深度诊断、只读台账验证后，旧 vendor/env 可移到技能外备份，再从技能目录移除。台账、备份、日志不随环境迁移。

## 验收

`python scripts/tests/env_acceptance.py` 在独立临时技能与缓存内测试首次启动、并发、缓存复用、退出码、损坏重建、深度检查、显式修复、锁文件损坏、包不匹配、环境包升级、技能位置移动和打包排除；比较真实台账 SHA256。测试保留隔离目录供复核，不操作安装目录的缓存。
既有业务批次测试仍需历史发票样本，缺样本不能视为通过。

## 图片 OCR 的迁移边界与验收

Python 解释器、winsdk 及 Python 依赖均在 ZIP 中，迁移后自动离线展开。Windows OCR 服务和系统语言功能属于目标操作系统，不在 ZIP 中；中文识别要求目标 Windows 10/11 已启用简体中文 OCR（zh-CN）。本版不会擅自安装或复制系统语言组件。

`env_check.py --deep --ocr` 在缓存解释器中检查绑定导入和系统可用 OCR 语言；缓存尚未建立时 --ocr 返回 1 并说明尚未建立，普通只读诊断仍可报告环境包有效。无 --ocr 时只验证 Python 环境及台账，不宣称已验收中文识别能力。

`python scripts/invoke.py tests/ocr_acceptance.py` 使用合成中文测试图片，在临时台账中验证 PNG/JPEG 提取号码、日期、金额，重复导入与 OCR 待人工状态保护。真实台账只做哈希比对。该测试需要目标系统的中文 OCR 和微软雅黑字体；缺少时不能视为通过。

识别时对 OCR 特有空格及货币金额间隔点做格式整理，不把 O/I 等字母猜为数字，也不改变 PDF 文本解析。图片结果仍为“⚠OCR待人工”，不会自动标为已报。

来源：[winsdk 发布文件及 cp312 wheel](https://pypi.org/project/winsdk/1.0.0b10/)、[Python 3.12.10](https://www.python.org/downloads/release/python-31210/)、[微软 OCR 可用语言说明](https://learn.microsoft.com/en-us/uwp/api/windows.media.ocr.ocrengine.availablerecognizerlanguages?view=winrt-26100)。
