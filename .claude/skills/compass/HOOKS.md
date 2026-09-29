# compass 机械 hook 层(附录;正文见 SKILL.md)

- 脚本:`~/.claude/hooks/compass-stop-guard.ps1`(UTF-8 BOM),同一脚本两模式:
  - **SessionStart(resume/compact)`-Mode sessionstart`**:当前会话 cwd 命中某 active 值守开关文件的 `cwd_prefixes` 才注入提醒(重架 Monitor+重架定时唤醒轻检)。
  - **Stop guard(默认)**:归属匹配的 active 开关文件+心跳(glob 取最新)超 40 分钟→block(exit 2)逼先重架再收口。防循环=自造计数器(目录×会话分片,连拦 2 次放行)。**TTL 自愈**:心跳/开关文件龄超 12h 自动改 `stale_auto_closed` 并落 `~/.claude/compass/guard-log.txt`。它只抓「彻底死透」;残留进程档(文件在刷但通道断)靠 §4.2 通道实测(发一个真事件看它能否回到会话)抓。
- 值守开关文件:`<coordination>\COMPASS-值守旗.json(值守开关文件)`,字段 `{state, project, cwd_prefixes, heartbeat_glob}`;heartbeat 用 glob 自动取最新。/keep-pushing 开窗写 active,收口或 owner 回归改 closed。
- 注册表:`~/.claude/compass/registry.txt`(UTF-8 BOM),一行一个协调目录;新项目启用=加一行+写值守开关文件。
- 已知边界:hook 修改需会话重启生效;中文路径依赖 ACP=65001(脚本已加 BOM+显式 UTF8);SessionStart 只挂 resume/compact,全新会话靠 Stop guard 兜底。
