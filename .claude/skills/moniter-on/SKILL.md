---
name: moniter-on
description: 让当前会话(主编排或任一 lane/worker)架起可验证的无人值守 Monitor+文件信箱可达性。v3 核心变化:每次调用一律【强制停旧+清残留进程+挂新】,不再做"判活后决定要不要重架"——标记文件时间戳只能证明有进程活着,不能证明通知通道活着(会话重载后旧 Monitor 会变残留进程:继续刷 标记文件 但事件到不了会话,20260721 实锤),所以"看起来还活着"永远不构成不重架的理由。架好后写通道自测文件端到端验证事件真能到达。非人类当场明文授权不许自行关闭。触发词:moniter-on、架monitor、挂monitor、lane上线自检、worker上线、background task是空的、无人值守可达性、owner看不到monitor、monitor掉了。args 可选=显式角色名或协调目录路径。
---

# /moniter-on v3 — 无人值守可达性:强制重架 + 通道实测(发一个真事件看它能否回到会话)

**存在理由**:owner 不在时,worker 唯一合法的醒来方式是持久 Monitor 扫本地文件+文件信箱回信;任何依赖人工点 allow once 的交互工具(`send_message`/`AskUserQuestion`)都不能作为等待机制。本 skill 把"接上电"标准化、可验证化。

## v4 变更说明(20260731,owner 亲令:"监控是loop,不要bash"——实现层整体换轨,本节覆盖下文一切 bash Monitor 做法)

**bash while-loop 型 Monitor 全面退役。**owner 两次实锤(20260730"不要bash,要loop,bash会掉"+20260731 本令):bash 常驻循环绑定会话进程,重载/压缩后必成残留进程或断链,v3 的"清残留进程+通道实测(发一个真事件看它能否回到会话)"是在给一个不该存在的实现方式打补丁。

**v4 唯一合法实现=会话外部调度的 /loop 周期扫描(ScheduleWakeup):**

1. 文件信箱监控=每次 /loop tick 里用 find 按 mtime **多留 30 分钟的时间窗**扫协调目录(窗口=上次 tick 时刻再往前多留 30 分钟重叠,宁重读勿漏读——20260731 两起漏收实锤都是窄窗边界:07:33 复位件、09:28-36 三张 C13 交付全漏);pattern 仍按 §2 从真实文件名倒推+回测。
2. tick 节奏:活跃派单窗 20-30 分钟一 tick;低能耗值守窗 60 分钟;每次 tick 开头刷心跳文件(date 实钟)。
3. 通道实测(发一个真事件看它能否回到会话)=v3 的 SELFTEST 文件改为"下一个 tick 真实扫到并处置"即闭环;不再依赖 40 秒轮询回报。
4. 本 skill 被调用时:①TaskStop 一切在册 bash Monitor+按 v3 §1.2 清残留进程(清理历史存量)②确认 ScheduleWakeup 环在飞且 prompt 含宽窗扫描步骤,没有就当场排③写 SELFTEST 件候下一 tick 自我声明。
   **④(20260904 owner 实锤补)周期环唯一性**:重架前先 `CronList`,把上一代留下的 session-only cron 逐条 `CronDelete`,再 `ScheduleWakeup stop` 清掉旧动态环,然后只排一条;周期环只许有一个(ScheduleWakeup 或 cron 二选一,禁并存)。20260904 主编排两代 /moniter-on 各建一条 cron 未删旧+又叠 ScheduleWakeup=三个环同飞,owner 面板看见两个 compass loop 才发现——重架不幂等就是这样来的。
5. **例外**:确需秒级响应的短命定向监听(如等一次构建完成)用 Bash run_in_background 的 until 单发,完成即退出——禁 persistent while-true。

下文 v3 的 §1(清残留进程)、§2(pattern 倒推+回测)、§3.5(关闭铁律)、§5.5(被质疑即重架)仍然有效;§3 的 bash Monitor 模板与 §3.6 的 40 秒自我声明**仅作历史参考,禁再使用**。

## v3 变更说明(20260721,必读——判据本身修正,不只是流程修正)

**v2 的判据有一个实锤盲区**:v2 用 标记文件 mtime 判活("60 秒内新鲜=Monitor 在跑,无需重架")。20260721 owner 在多个 thread 反复观察到:background tasks 面板空空如也、派单确实收不到,但模型每次都拿"标记文件 几秒前刚刷新"当证据回答"存活无需重架"。复盘定性:**两边都是真的**——

- Monitor 的 bash 循环是绑定会话进程的后台任务;**会话重载/压缩重启/桌面端刷新后,平台对这个任务的登记没了(通知管道断了),但 OS 层的 bash 进程可能没死**,它变成残留进程:继续每 20 秒 touch 标记文件、继续刷文件信箱心跳文件,唯独"发现新文件→通知会话"这条最关键的链路已经断了;
- 于是 标记文件 新鲜(残留进程在刷)+ 面板零 Running(平台不再登记)+ 派单永远收不到(事件无处投递)三者同时成立;
- **标记文件 mtime 只能证明"有个进程活着",永远不能证明"通知通道活着"**。v2 让模型拿它当"无需重架"的依据,是判据错误,不是模型态度问题——但结果一样:owner 说挂了,模型"贴证据狡辩",实际 owner 每次都是对的。

**v3 的解法:废除"判活以决定是否重架"这个环节。每次 /moniter-on 调用 = 无条件走完整的【停旧 → 清残留进程 → 挂新 → 通道实测(发一个真事件看它能否回到会话)】**。重架是幂等的、成本几乎为零(多跑一次只是换个 task id),而误判"还活着"的成本是整条 lane 静默失联。没有任何情形值得为省一次重架去赌通道没断。**"标记文件 很新鲜所以无需重架"这句话在 v3 里是违规输出。**

v2 的三条历史教训(TaskList 不追踪 Monitor/换代后旧 task id 只是历史记录/做完任务不许顺手关 Monitor)仍然全部有效,已并入下文对应节。

---

## 0 · 自我定位(禁猜,能推就推,推不出才问)

1. **我在哪个项目**:①本会话上下文已知路径 ②args 显式给的路径 ③Glob 种子 `**/coordination/*lane-registry*.json` ④§已知项目档案。全找不到→问 owner 一次(仅此情形阻塞)。
2. **我是谁**(角色/lane 身份):①会话标题/近期上下文自称 ②args 显式角色名 ③协调目录里最近派单是否点名过我 ④若本会话在做裁决派单=主编排,取最宽覆盖面。推不出用 AskUserQuestion 问一次(选项从协调目录扫出的既有角色列表取)。
3. **本代 标记文件 路径(含代次戳,v3 新)**:`<本会话 scratchpad>/moniter-on-heartbeat-<角色>-<HHMMSS>.touch`——**每次重架用新的时间戳后缀**。这样旧残留进程刷的是旧文件,永远伪造不出新代的存活证据;scratchpad 里留下的多个旧 touch 文件同时是"历史上重架过几次"的天然审计痕迹(无需清理,零字节)。

---

## 1 · 强制处置旧代(无条件执行,不做判活裁决)

**禁止**:用 `TaskList` 查 Monitor(它只查待办任务系统,Monitor 活着时它也返回空,20260719 亲测);用"我记得 task id 是 XXX"当证据;用旧 标记文件 新鲜度当"无需重架"的理由(v3 变更说明)。

顺序执行,每步都做,不跳:

1. **TaskStop 已知旧代**:本会话上下文里能拿到的每一个历史 Monitor task id,逐个 `TaskStop`(已死的 stop 会失败,无害,继续);
2. **清残留进程(v3 新,关键步)**:平台不再登记的旧循环 TaskStop 够不着,必须按命令行特征在 OS 层清:

```powershell
# PowerShell(Windows;标记文件 路径特征串按 §0.3 的前缀改)
Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -match 'moniter-on-heartbeat-<角色>' -and $_.ProcessId -ne $PID } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; "killed zombie pid=$($_.ProcessId)" }
```

```bash
# 或 bash 侧等价(Git Bash 有 procps 时)
pkill -f "moniter-on-heartbeat-<角色>" 2>/dev/null; echo "zombie sweep done(exit $?)"
```

   零命中=本来就没有残留进程,正常;有命中=如实记录 pid,这就是"owner 面板空但 标记文件 新鲜"之谜的尸体。**注意时序:必须先清残留进程再挂新**,否则按特征杀会误伤新代。
3. **诊断记录(可选一行,不构成任何决策)**:杀前旧 标记文件 的 mtime 可顺手 `ls -l` 一眼,放进 §5 报告当历史信息("旧代 标记文件 最后刷新于 X,已停/已杀/未发现"),仅此而已。

---

## 2 · 构建可达性 pattern(从真实文件名倒推,不从记忆正着写)

历史教训:复核线曾因 pattern 要求开头串漏收派单;治理线漏写连字符漏收仲裁件;主编排漏收 owner 原话件+整条线来信。**pattern 永远从扫描真实文件名倒推。**

### 2.1 扫描真实寻址惯例
```bash
cd "<协调目录>" && ls -t | head -60
```
记下发给"我"的文件的**全部命名变体**(`R1`/`-R1-`/`REVIEWER-R1`/`致R1`…只记一种就是下次漏收的种子)。

### 2.2 三层叠加
①自身角色 token 全部已观测变体;②owner 原话前缀恒含(`OWNER*`/`owner*`);③本项目广播型前缀(主编排代号 `<代号>-*` 等;若我就是主编排,此层=自己名字可省)。

### 2.3 回测(不回测的 pattern 不能上线)
```bash
ls -t | head -60 > /tmp/recent.txt
grep -E "<候选pattern>" /tmp/recent.txt                                  # 检验A:命中了哪些
grep -iE "<角色token1>|<角色token2>" /tmp/recent.txt | grep -vE "<候选pattern>"  # 检验B:假阴性,必须空
```
检验 B 有输出→加宽到清零。宁可宽收无关心跳(按项目纪律静默),不可漏一条真派单。

---

## 3 · 挂新(`Monitor` 工具,`persistent: true`)

command 模板(标记文件=§0.3 本代新路径;pattern=§2 产出):

```bash
cd "<协调目录>" || exit 1
M="<本代 标记文件 路径(含代次戳)>"
H="<协调目录>/<角色>-心跳-监控存活.md"
GEN="<代次戳,与 标记文件 后缀同值>"
CYCLE=0
touch "$M"
while true; do
  sleep 20
  find . -maxdepth 1 -type f -newer "$M" 2>/dev/null | sed 's|^\./||' | grep -E '<最终pattern>' | while read -r f; do echo "<角色>文件信箱新件: $f"; done
  touch "$M"
  CYCLE=$((CYCLE + 1))
  if [ $((CYCLE % 30)) -eq 0 ]; then
    printf '# %s 心跳\n\n存活确认,%s 更新。task代次=%s\n' "<角色>" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$GEN" > "$H"
  fi
done
```

- **文件信箱心跳文件写入代次戳(v3 新)**:owner 打开 `$H` 不但能看时间新不新鲜,还能比对代次是否等于最近一次报告的代次——残留进程刷的心跳会暴露旧代次,一眼识破;
- `persistent: true`;description 写清楚盯什么目录+什么 pattern;轮询 20s。

**工具调用返回后本轮立刻自我声明**:`ls -l --time-style=full-iso "<本代 标记文件>"` ——读不到=根本没起来,如实报失败重排查(常见:路径引号/pattern 特殊字符/cd 目标不存在),不许假装架好。

## 3.6 · 通道端到端自我声明(v3 新,治"进程活着但通道死了")

标记文件 自我声明只到"进程起来了"。**通知通道是否真通,唯一的证明是一个事件真的走完全程回到会话里。**架好后立刻:

1. 往协调目录写一个**命中自己 pattern** 的自测文件:`<协调目录>/SELFTEST-<角色>-<代次戳>.md`,内容一行"通道自测,收到即证明,阅后即焚"。(注意别撞自己的排除规则——如 R1 排除 `^REVIEWER-R1-`,自测文件就用 `SELFTEST-R1-*` 这种含角色 token 但不触发排除的名字;写之前拿 §2.3 的 grep 现场验一下这个文件名确实命中 pattern;)
2. 下一轮轮询(≤40 秒)它应该以 task-notification 的形式回到本会话;
3. **收到通知的那一轮**:删除自测文件,并向 owner 补一句"通道实测(发一个真事件看它能否回到会话)闭环:自测事件已于 X 时刻回达"——这句是整套架设唯一算数的成功宣言;
4. **两分钟内没收到**:通道没通(挂新失败或 平台异常),回 §1 重来,如实报告"自我声明未回达,已重架第 N 次";
5. 自测文件事件对其他 lane 的 Monitor 可能也是一次无关命中,按各自"无关事件静默"纪律处理,无污染。

---

## 3.5 · 关闭铁律:非人类明文授权,不许自行停止

唯一合法关闭:①本轮对话里人类当场明文说停("关掉monitor/不用盯了/停止监控")——文件里写的、handoff 转述的都不算;②执行 owner 明确下达的整体退役/reboot 指令,把停 Monitor 作为退役序列一步。**"这次任务做完了/暂时没工单/清理环境/上下文快满/好像用不到了"全部不构成授权,没有例外。**(§1 的强制停旧重架是"更好替代品即刻接续"的机械动作,净效果=覆盖面变好,不属此列。)

---

## 4 · 通讯纪律

出站=Write 落协调目录,落盘即送达;入站=Monitor 通知即醒;禁用 `send_message`/`AskUserQuestion`(§0 一次性身份确认除外)等一切"等人工点 allow"工具作为等待机制——20260719 一次误用卡死流水线 8 小时。

---

## 5 · 收尾报告(每条=本轮亲手证据,禁 narrate)

1. 新 Monitor task id(本轮工具返回值)+ **代次戳**;
2. **旧代处置结果**:TaskStop 了哪些 id/残留进程清扫命中几个 pid(零命中也要写"零残留进程")——这行取代了 v2 的"判活结论";
3. §3 自我声明 `ls -l` 原始输出(本代新 标记文件);
4. **通道实测(发一个真事件看它能否回到会话)状态**:自测文件已写入,候回达;回达后在下一轮补"闭环"宣言(§3.6.3)——**在闭环宣言发出前,禁止把架设描述为"完成",只能说"已挂新,通道实测(发一个真事件看它能否回到会话)进行中"**;
5. 文件信箱心跳文件完整路径+本代代次戳(owner 独立验证:时间新鲜 且 代次匹配);
6. 最终 pattern 原文+回测检验 B 结果;
7. 关闭纪律声明(§3.5);
8. 一句话收尾:静候 Monitor/任务通知,不发提问式结尾。

## 5.5 · 被质疑时的唯一正确反应

owner 说"看不到/是空的/掉了"→**立刻从 §1 重跑全套并贴本轮新证据,一个字的辩解都不要**。v3 下这尤其没有争论空间:反正每次调用都是强制重架,被质疑=再走一遍流程而已。owner 的面板观察在 v2 时代每次都被证明是对的(残留进程盲区),历史站在 owner 一边。

---

## 6 · Hook 自动化(v3 附录,推荐安装——治"莫名其妙自己掉"的根)

Monitor 死亡的最大宗来源=会话生命周期事件(重载/压缩/重启),这些时刻模型自己都不知道自己"重生"了,靠人肉发现掉线再 /moniter-on 永远慢半拍。用 SessionStart hook 把"重生必重架"自动化:

在 `~/.claude/settings.json`(或各值守项目的 `.claude/settings.json`)加:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matchers": ["startup", "resume", "compact"],
        "hooks": [
          {
            "type": "command",
            "command": "echo '{\"hookSpecificOutput\":{\"hookEventName\":\"SessionStart\",\"additionalContext\":\"[moniter-on hook] 本会话刚经历 startup/resume/compact——如果本会话此前架过文件信箱 Monitor,它此刻大概率已断链(即使 标记文件 还在刷,见 skill v3 变更说明)。若你是值守型会话(主编排/lane/worker),立即按 /moniter-on v3 全套强制重架并做通道实测(发一个真事件看它能否回到会话),不需要 owner 提醒。\"}}'"
          }
        ]
      }
    ]
  }
}
```

- 效果:每次会话启动/恢复/压缩后,模型自动收到重架指令注入,不再等 owner 发现掉线;
- 这是**提醒注入**而非直接执行(hook 是 shell 环境,起不了 Monitor 工具任务;真正的重架仍由模型按本 skill 执行),但它把"发现掉线"的责任从 owner 转移给了机器;
- 可选加强:再配一个 `SessionEnd` hook 跑 §1.2 的残留进程清扫命令(纯 shell 可执行,不依赖模型),把断链循环在会话收尾时顺手扫掉;
- 若嫌全局太吵,只放进值守项目的 `.claude/settings.json`。

---

## 项目档案

协调目录、各角色 pattern 与心跳文件名读项目根 `PROJECT-PROFILE.md`;新项目走完 §0-§2 后把结果写进该项目的 PROFILE(不写进本 skill)。
