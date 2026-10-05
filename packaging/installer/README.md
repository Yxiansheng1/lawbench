# 律所统一 Skill 目录（给律所 IT）

律所要给所有律师统一下发 Skill 时才需要这个目录；现在没有统一下发的 Skill，**不用建**。不建时程序照常用，设置"关于"里显示一行"未配置律所统一 Skill 目录"，不算问题。

- 位置：`%ProgramData%\lawbench\skills`（通常是 `C:\ProgramData\lawbench\skills`）。
- 权限：普通用户只读，只有管理员和 SYSTEM 能改。这样下发的 Skill 不会被律师本机改动。程序启动时会检查；普通用户能改时，首页提示"请联系技术支持设置为只读"。

## 怎么建

任选一种，都需要管理员权限：

1. **安装时**：安装程序装完会问"是否创建律所统一 Skill 目录？"，选"是"，在弹出的管理员确认里点"是"。默认是"否"；静默安装（`/S`）不问。
2. **装好以后**：以管理员身份打开 PowerShell，运行（不带参数就是上面那个位置）：

   ```powershell
   & "$env:LOCALAPPDATA\Programs\连越律师工作台\installer\set-skills-acl.ps1"
   ```

   装到别的目录时，把路径换成 `<安装目录>\installer\set-skills-acl.ps1`。要建在别处时加 `-Dir <文件夹>`（程序只读上面那个位置，一般不用改）。

## 下发 Skill

把 Skill 文件夹放进 `%ProgramData%\lawbench\skills\`（需要管理员权限），律师下次启动程序时加载；同名时覆盖程序自带的。
