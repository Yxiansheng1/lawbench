---
name: compact-s
description: 选择性 compact:上下文将满/compact 前先把"只存在于本会话对话里"的高价值状态(owner 裁决原话/编排目标态/验收硬门/关键路径/compass 对照要点与叫醒机制实证/advisor 在生效建议)高保真外置成 checkpoint 文件,再放心 compact;compact 后第一动作=读回 checkpoint 重新对照目标。owner 说"上下文快满了/别粗暴 compact/选择性压缩/compact 前保存"或模型自感 context 紧张时触发。
---

# /compact-s — 先外置,再压缩:compact 不再丢东西

平台自动 compact 是盲目摘要——owner 原话被压成「做了一些决定」。本 skill 不挑刺复核 compact,而是让它无所谓:**凡只活在对话里的高价值状态,先高保真落盘**。项目事实(协调目录/台账路径)读项目根 `PROJECT-PROFILE.md`。

## 0 · 判据:什么进 checkpoint
唯一标准:**这条信息是否只存在于本会话对话流里?** 已落台账/memory/协调目录的只登记路径+一句钩子;本会话新发生未外置的逐字转录;判断不了当作只在对话里。

## 1 · Checkpoint(固定结构,高保真区禁摘要)
路径:值守项目=`<coordination>/<角色>-COMPACT-CHECKPOINT-<YYYYMMDD-HHMM>.md`;非项目会话=args 指定目录或 `~/.claude/compact-checkpoints/<cwd-slug>-<时间戳>.md`。
1. **owner 决策**:本会话每次拍板/裁决/授权的原话+时刻;已入台账的只记条号+路径。
2. **编排计划与目标态**:值守计划/交接件的目标态原文+路径;基面 SHA/tag/冻结态等会话内刚更新的数字;**走五门发版范式的项目必写当前门次**:本车在第几门、哪些卡缺哪一门、五门台账(工单集)绝对路径——compact 后第一动作就靠这行定位。
3. **验收目标与宪法级判准**:硬门清单+「合流≠验收/回归门≠决策完成度」类判准原文+出处。
4. **关键文件路径**:本会话读过/写过的载重文件绝对路径,一行一个+一句说明。
5. **compass 对照要点**:在飞表(开放目标+执行体+叫醒机制+对端会话级活性证据路径)+**叫醒机制实证状态**(每个叫醒机制最近真触发时刻+证据文件;零触发的如实标死)+本窗跑偏/违规记录。
6. **advisor 在生效建议**:尚未执行/裁决的逐条;无则写「无」。
可压缩区:一段话列出可被摘要压掉的工程往返(已固化的命令输出/报错现场)。
纪律:零编造;记不清原话就 Read 回原件;写不满如实写「无此类增量」。

## 2 · 压缩(checkpoint 落盘并亲验之后)
1. ls/Read 回首尾亲验。
2. /compact 是否吃自定义指引因版本而异,现场验证;不确定就普通 compact,checkpoint 在盲压也不丢。
3. 模型不能自己执行 /compact;自动 compact 逼近时不等 owner,立刻落 checkpoint。

## 2.5 · 固定交付:两段可粘贴 prompt(回复末尾原样给出,尖括号换真值,不加解释)
**A. compact 指引**
```
/compact 保留:owner 决策原话与时刻、当前基面 SHA/tag/tip、在飞任务及其执行体与叫醒机制、验收硬门原文、关键文件绝对路径、advisor 未执行建议;可压:已被文件固化的工程往返(命令输出/报错现场/被拦细节)。checkpoint=<checkpoint 绝对路径>
```
**B. compact 后启动短 prompt**
```
你是 <角色>。第一动作:全文读 <checkpoint 绝对路径>,以它为准(摘要与它冲突以它为准);再按 compact 前 30 分钟至今的 mtime 窗口扫一遍文件信箱补漏件;然后 /moniter-on 重架值守并做通道实测(发一个真事件看它能否回到会话);再 /compass 增量;然后按 checkpoint「compact 后第一批动作」逐条执行,不问我。
```

## 3 · Compact 之后
Glob 本角色最新 `*COMPACT-CHECKPOINT*` 全文 Read;跑 `/compass 全检`;摘要与 checkpoint 冲突以 checkpoint 为准。

## 4 · 周期性使用
大节点的 checkpoint 可加一次恢复演练:不带任何背景的子代理只读 checkpoint 答「目标/在飞/禁区/头三个动作/候 owner」五问,答不出=checkpoint 缺陷(同 /reboot 的 drill)。
每逢大节点(合流/收货/换代/owner 密集拍板后)顺手刷一份新 checkpoint,旧的不删。值守计划=现在要干什么;checkpoint=对话里有什么不能丢。

## 5 · 自动 compact 的接法(模型看不到上下文占用、也不能自己触发 compact,所以「时机」靠机制不靠自觉)
平台事实(20260904 查官方文档):自动 compact 的触发点可配(`autoCompactWindow`,设在项目 `.claude/settings.json` 或环境变量,100K-1M token);PreCompact hook 只能记录不能阻止或改指令;SessionStart hook 的 `compact` matcher 能把启动指令注入压缩后的对话;模型拿不到自己的 token 占用数;没有任何工具能让模型主动触发 compact。据此三件套:
1. **阈值**:项目 `.claude/settings.json` 写 `"autoCompactWindow": <目标 token 数>`(想在 450-600k 压就写 550000),压缩由平台在该点自动做。
2. **压缩前标记**:PreCompact hook(manual+auto)跑 `~/.claude/hooks/precompact-marker.ps1`,机械落 `<coordination>/PRECOMPACT-标记-<时刻>.md`:最新 checkpoint 路径 + checkpoint 之后落盘的文件清单。它补的是「checkpoint 到 compact 之间」的空窗,压缩后按清单逐件补收,不靠摘要。
3. **压缩后自启**:SessionStart(compact) hook 注入完整启动指令(读最新 checkpoint→读压缩前标记补收→moniter-on 重架→ScheduleWakeup→compass 增量→读五门台账定位门次→继续),不需要 owner 再发一句。
**主编排的义务(这才是「把握时机」的真实形态)**:每个大节点(收货/合流/派线/owner 密集拍板)刷一份 checkpoint,并且 checkpoint 龄不超过 60 分钟——做到这两条,自动 compact 落在任何时刻,损失都不超过一个节点,再由压缩前标记把这一节点内的文件补回来。hook 改动需重启会话生效;第一次真实 auto-compact 后要肉眼确认注入指令真出现并被执行。

### §5 补(20260904 官方文档查证)
- 阈值键 `autoCompactWindow` 单位=token 数(支持 550000/550k/1M),**会话启动时读取,不热加载**;环境变量 `CLAUDE_CODE_AUTO_COMPACT_WINDOW`(纯数字)优先级最高;CLI `claude --autocompact 550k` 可临时覆盖;交互命令 `/autocompact <值>`、`/autocompact auto` 恢复默认。PreCompact hook 用 `matcher` 取 `auto`/`manual`。**改完阈值必须重启会话才生效**,别在同一会话里等它触发(20260904 实锤:14:15 写入,同会话到 750k 仍按平台默认线压)。
