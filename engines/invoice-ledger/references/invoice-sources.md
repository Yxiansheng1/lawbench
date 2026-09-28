> 本文仅作历史来源模式参考；当前PDF选择、购买方核验、数量对账及浏览器交接规则以[3.9流程](10-collection-and-paper.md)为准。发件人和网站格式需实际核实。

# 发票来源特征与附件清单格式参考

## 一、六类发票来源发件域与附件模式

| 来源 | 发件域 | 每封附件 | 附件内容 |
|------|--------|----------|----------|
| 票根通行费 | `service@invoice.txffp.com` | 3 | 通行费电子发票.zip + 汇总单(票据).pdf + 汇总单(行程).pdf |
| 美团 | `it_fapiao@meituan.com` | 3 | PDF + XML + OFD（OFD 文件名带 `_查阅需OFD阅读器` 后缀） |
| 票通 | `kefu@service.vpiaotong.com` | 3 | PDF + OFD + XML |
| 麦当劳 | `e-invoice@mcd.cn` | 2 | PDF + XML |
| 中石化 | `sys-mail@sinopec.com` | 3 | PDF + OFD + XML |
| 微信支付 | `weixinteam@tencent.com` | 2 | PDF + CSV（电子报销单） |

### 票根 ZIP 内容结构（重要）

每个 `通行费电子发票.zip` 内含该日全部通行费明细发票，**PDF 与 XML 成对**。
邮件正文会声明"成功开具了 N 张发票"——ZIP 内 PDF 数量应与 N 一致，是完整性交叉验证的关键依据。

示例（0722 批次）：
- 邮件声明 7 张 → ZIP 含 7 PDF + 7 XML
- 邮件声明 8 张 → ZIP 含 8 PDF + 8 XML

### 各来源邮件主题特征（用于快速识别）

| 来源 | 主题特征 |
|------|----------|
| 票根 | `通行费电子发票` |
| 美团 | `【电子发票】<商家名>（发票金额：xxx元）` |
| 票通 | `您收到一张来自<商家名>的电子发票【发票金额：xxx】` |
| 麦当劳 | `【电子发票】您收到一张新的电子发票[发票号码：...]` |
| 中石化 | `【中国石化】推送的电子发票` |
| 微信支付 | `你有1张电子发票` |

## 二、附件三级优先级

| 优先级 | 类型 | 默认处理 |
|--------|------|----------|
| P0-PDF | `.pdf` 发票文件 | 必须下载归档 |
| P1-ZIP | 票根 `通行费电子发票.zip` | 补下载（内含明细） |
| SKIP | `.ofd` / `.xml` / `.csv` | 有意跳过 |

> 说明：OFD 为国产数电票格式（需专用阅读器），XML 为数电票源文件，CSV 为电子报销单辅助表——报销场景下 PDF 已足够，故 SKIP。

## 三、清单 TSV 格式规范

### 附件清单v2权威.tsv（全量权威清单）

```
日期	来源	文件名	类型	大小	优先级	message_id	attachment_id
0803	票根通行费	通行费电子发票.zip	application/zip	397731	P1-ZIP	msg_xxx	att_xxx
0803	票根通行费	通行费电子票据汇总单(票据).pdf	application/pdf	47045	P0-PDF	msg_xxx	att_xxx
```

### 待下载清单.tsv

```
优先级	日期	来源	文件名	大小	message_id	attachment_id
P1-ZIP	0708	票根通行费	通行费电子发票.zip	597379	msg_xxx	att_xxx
SKIP	0708	中石化	26000000000000000001.ofd	25473	msg_xxx	att_xxx
```

### 下载清单.tsv（注意 `#` 注释表头）

```
# message_id	attachment_id	来源	日期	原文件名
msg_xxx	att_xxx	票根通行费	0708	通行费电子票据汇总单(票据).pdf
```

> **解析要点**：`下载清单.tsv` 表头带 `#` 前缀，csv.DictReader 无法解析，需逐行跳过 `#` 开头行再 `split('\t')`。

### 最终清单_<日期范围>.tsv（终态账目）

```
日期	来源	文件名	类型	大小	优先级	状态
0803	票根通行费	通行费电子发票.zip	application/zip	397731	P1-ZIP	OK
0722	票根通行费	通行费电子发票.zip	application/zip	1589462	P1-ZIP	OK
0708	中石化	26000000000000000001.ofd	application/octet-stream	25473	SKIP	MISSING
```

状态取值：`OK`（已下载归档）/ `MISSING`（未下载）/ `SKIP`（有意跳过）。

**终态验收规则**：所有 MISSING 行必须全部是 SKIP 优先级；P0-PDF 与 P1-ZIP 必须 100% OK。

## 四、下载日志.tsv 格式

```
attachment_id	来源	日期	文件名	大小	本地路径	状态
mcp-connector-proxy-qq-mail_DownloadAttachment-xxx	票根通行费		0803_通行费电子发票.zip	397731	票根通行费/0803_通行费电子发票.zip	OK
```

早期批次（0710-0714、0714-0717 等）曾用批次文件夹归档，后续统一改为来源子目录。日志用于交叉验证最终清单（size 匹配 + 日志记录对齐）。

## 五、归档命名规则

| 附件类型 | 命名规则 | 示例 |
|----------|----------|------|
| 汇总单 PDF | `MMDD_通行费电子票据汇总单(票据/行程)[N].pdf` | `0722_通行费电子票据汇总单(票据)3.pdf` |
| ZIP | `MMDD_通行费电子发票[(N)].zip` | `0722_通行费电子发票(3).zip` |
| 其他来源 | 原文件名 | `26000000000000000001_示例单位.pdf` |

同日期多个同类型附件按邮件顺序加 `(2)(3)(4)` 序号。

## 六、链接型发票来源（v1.1.0 新增）

以下来源的发票**不作为邮件附件发送**，而是通过邮件正文中的下载 URL 交付。
需要在获取邮件后从 HTML/文本 body 中提取 PDF URL，再用 HTTP 下载。

### 京东 JD.COM

| 属性 | 值 |
|------|-----|
| 发件域 | `customer_service@jd.com` |
| 显示名称 | 京东JD.com |
| 主题特征 | `您的京东订单【{订单号}】电子发票已开具` |
| body_format | 2 (HTML) |
| attachment_count | 0 |
| 发票链接格式 | `<a href="https://eicore-invoice-{N}.s3.cn-north-1.jdcloud-oss.com/digital-invoice/digital_{发票号}.pdf?AWSAccessKeyId=...&Expires=...&Signature=...">发票PDF文件下载</a>` |
| URL 提取正则 | `digital_\d+\.pdf\?[^"'\s<>]+` |
| Expires | 约 2730000000 (Unix timestamp ≈ 2056年，历史样例，不保证当前链接有效) |
| 每封邮件 | 1 张 PDF（1 个订单号），偶有同订单多封重复邮件 |
| 归档命名 | `{MMDD}_京东_{发票号}.pdf` |

### krystore

| 属性 | 值 |
|------|-----|
| 发件域 | `krystore@service.alibaba.com` |
| 显示名称 | krystore |
| 主题 | `发票开票成功通知` |
| body_format | 1 (纯文本) |
| attachment_count | 0 |
| 交付机制 | 正文包含短链接 `invoice.keruyun.com/s/{code}` → HTTP 302 重定向 → 实际 PDF |
| URL 提取方式 | 正则 `https://invoice\.keruyun\.com/s/\w+` |
| 归档命名 | `{MMDD}_krystore.pdf` |

### 票慧通

| 属性 | 值 |
|------|-----|
| 发件域 | `dianzifapiao@fapiaotuisong.huapiaoer.cn` |
| 显示名称 | 票慧通 |
| 主题 | `你有一张电子发票待接收` |
| body_format | 2 (HTML) |
| attachment_count | 0 |
| 交付机制 | 正文包含三种格式下载链接（PDF/OFD/XML），指向税务局平台 `dppt.shenzhen.chinatax.gov.cn` |
| URL 提取正则 | `https://dppt\.shenzhen\.chinatax\.gov\.cn[^"'\s<>]*Wjgs=PDF[^"'\s<>]*` |
| 归档命名 | `{MMDD}_票慧通_{发票号}.pdf` |

### 诺诺网（v1.3.0 新增，2026-08-07 实测）

| 属性 | 值 |
|------|-----|
| 发件域 | `invoice@info.nuonuo.com` |
| 显示名称 | 诺诺网 |
| 主题 | `您收到一张【{销方名称}】开具的发票【发票号码：{发票号}】` |
| body_format | 1/2（正文含链接） |
| attachment_count | 0 |
| 交付机制 | 正文含链接 `https://nnfp.jss.com.cn/{code}` → 跳转至发票下载页（HTML）→ 再提取其中 PDF 下载链接 |
| URL 提取正则 | `https://nnfp\.jss\.com\.cn/[^\s"'<>]+` |
| 正文特征 | 含"下载发票"按钮 + 发票抬头/数电号码/开票日期/合计金额 + `支付宝 \| 扫一扫领取发票` + `点击链接查看发票` |
| 归档命名 | `{MMDD}_诺诺网_{发票号}.pdf` |

### 臻票云（v1.3.0 新增，2026-08-07 实测）

| 属性 | 值 |
|------|-----|
| 发件域 | `mail@fp51.cn` |
| 显示名称 | 臻票云 |
| 主题 | `{销方名称}给您开具了发票，请注意查收` |
| body_format | 1/2（正文含链接） |
| attachment_count | 0 |
| 交付机制 | 正文含链接 `http://fp51.cn/{code}` → 跳转至发票下载页（HTML）→ 提取 PDF/OFD/XML 下载链接 |
| URL 提取正则 | `https?://fp51\.cn/[^\s"'<>]+` |
| 正文特征 | 含 `臻企云智能发票` + `点击下载PDF发票OFD发票XML发票` + 购方名称/开票日期/开票金额/发票号码 + `领票二维码` |
| 归档命名 | `{MMDD}_臻票云_{发票号}.pdf` |

### 票点点（v1.3.0 新增，2026-08-07 实测）

| 属性 | 值 |
|------|-----|
| 发件域 | `invoice@mail.sf-epiaotong.com` |
| 显示名称 | 票点点电子发票 |
| 主题 | `您收到来自{销方名称}的电子发票【发票号{发票号}】` |
| body_format | 1/2（正文含链接） |
| attachment_count | 0 |
| 交付机制 | 正文含发票信息 + 下载链接（sf-epiaotong 域或跳转） |
| URL 提取正则 | `https?://[^\s"'<>]*(?:epiaotong|sf-epiaotong)[^\s"'<>]*` |
| 正文特征 | 含 `票点点-让发票变得更简单` + `请选择需要的发票格式，点击对应链接进行下载` + 发票抬头/发票号码/开票日期 |
| 归档命名 | `{MMDD}_票点点_{发票号}.pdf` |

### 搜索策略差异

| 来源类型 | 搜索方式 | 关键参数 |
|----------|----------|----------|
| 附件型（六类） | `ListMessages(dir=inbox, has_attachments=true, after=<日期>)` | 带附件过滤 |
| 链接型（六类） | `SearchMessages(q="发票", search_in=SEARCH_IN_SUBJECT, dir=inbox, after=<日期>)` 翻页拉全，逐封按发件域识别 | **v1.3.0 推荐主法**，可发现未知新来源 |
| 链接型（补充） | `SearchMessages` 针对性关键词 | `q="诺诺"` / `q="臻票云"` / `q="票点点"` / `q="发票开票成功通知"`, `search_in=SEARCH_IN_ALL` |

> 若仅用 `ListMessages(has_attachments=true)`，会系统性漏掉全部链接型来源（它们 `has_attachments: false`）。
> 若仅用 `SearchMessages(q="发票", has_attachments=true)`，同理——正文含"发票"但不含附件的邮件不会出现在结果中。
> **教训（2026-08-07）**：早期仅按三类已知链接型来源做关键词搜索，遗漏了诺诺网/臻票云/票点点；改为"主题全局搜索 + 发件域识别"后全部暴露。新来源出现时应先验证其交付机制再纳入清单。