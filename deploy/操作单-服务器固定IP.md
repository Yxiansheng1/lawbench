# 操作单 · 服务器固定 IP（395、6000D）

**为什么要做**：律所 10-02 晚停电，10-03 中午来电后，395 用 DHCP 拿到了新地址：从 `192.168.8.124` 变成了 `.32`。
可产品的白名单、Spec、验收脚本和防火墙都写死在 `.124` 上。用户通过 SSH 远程改静态 IP，改到一半自己被踢下线，395 一度从网络上消失，最后到机器前重启才恢复。
6000D 没出问题：它本来就是静态 IP。

本单分三部分：
- 395（Windows）怎么改成固定 IP；
- 6000D（Linux）只核对，不改；
- 请律所网管在路由器上做 DHCP 地址保留。

**命令都在服务器本机执行，AI 不执行、不保存密码。**

## 两条铁律（先读）

1. **改 IP 只在服务器本机的控制台做**（坐在机器前，或者用不经过这个 IP 的远程方式）。
   - 如果一定要远程改，先确认还有第二条通路：395 的 EasyTier 虚拟地址 `10.126.126.3` 能远程登录，而且 EasyTier 已经是开机自启的服务（见 `操作单-395停电后恢复.md` 第 2 步）。
   - **绝不能用要改的那个地址远程连进去再改它。** 10-03 被踢下线就是这样发生的。
2. **改之前确认目标地址空着。**
   - 在要改的服务器上，或同网段另一台电脑上运行：`ping -n 2 192.168.8.124` 应该不通，然后 `arp -a | findstr 192.168.8.124` 应该没有记录。
   - 如果有回应：先查清是谁占着（例如另一台电脑设了这个静态地址），不要直接改。

## 一、395（Windows 11）改成固定 `192.168.8.124`

下面的参数是 10-03 在律所网络上实测的：网关 `192.168.8.1`，掩码 /24，DNS `202.96.134.133`、`202.96.128.166`。
**执行前先在 395 上运行 `Get-NetIPConfiguration`，按现场结果核对**，有出入以现场为准。

在 395 本机，以管理员身份打开 PowerShell：

```powershell
# 0) 看现状，记下来（回退用）
Get-NetIPConfiguration | Format-List InterfaceAlias, IPv4Address, IPv4DefaultGateway, DNSServer
Get-NetAdapter | Format-Table Name, InterfaceDescription, Status, MediaType
# 预期：有线网卡（MediaType 802.3，名字多为"以太网"）Up；若 WLAN 也 Up 且同在 192.168.8.x，见第 4 步

# 1) 确认 .124 空着（铁律 2）
ping -n 2 192.168.8.124        # 预期：请求超时（若 395 现在就是 .124，这步会通——那是它自己，跳过即可）
arp -a | findstr 192.168.8.124  # 预期：无输出（同上）

# 2) 有线网卡改静态（把 "以太网" 换成第 0 步看到的有线网卡名）
$if = "以太网"
Set-NetIPInterface -InterfaceAlias $if -Dhcp Disabled
Get-NetIPAddress -InterfaceAlias $if -AddressFamily IPv4 -ErrorAction SilentlyContinue | Remove-NetIPAddress -Confirm:$false
Get-NetRoute -InterfaceAlias $if -DestinationPrefix 0.0.0.0/0 -ErrorAction SilentlyContinue | Remove-NetRoute -Confirm:$false
New-NetIPAddress -InterfaceAlias $if -IPAddress 192.168.8.124 -PrefixLength 24 -DefaultGateway 192.168.8.1
Set-DnsClientServerAddress -InterfaceAlias $if -ServerAddresses 202.96.134.133, 202.96.128.166

# 3) 验证
Get-NetIPAddress -InterfaceAlias $if -AddressFamily IPv4 | Format-Table IPAddress, PrefixLength, PrefixOrigin
# 预期：192.168.8.124  24  Manual
ping -n 2 192.168.8.1           # 预期：通（网关）
ping -n 2 192.168.8.77          # 预期：通（6000D）
Invoke-RestMethod http://192.168.8.124:9000/health
# 预期：status ok、contract_version 1.3。prep395 绑地址时会自己每 5 秒重试，
# 地址出现后自动绑上（T11 的设计），一般不用重启服务；30 秒后仍不通再 Restart-Service prep395
```

4) **建议关掉 Wi-Fi，只留有线。** 395 现在有线和 WLAN 同时连在同一个网段，两张网卡都能拿到 192.168.8.x 的地址。哪张网卡出流量、对方看到哪个地址都不确定。确认有线正常（第 3 步通过）之后，再执行：

```powershell
Disable-NetAdapter -Name "WLAN" -Confirm:$false      # 名字以第 0 步为准
```

**回退**（改坏了、连不上网关）：

```powershell
Set-NetIPInterface -InterfaceAlias $if -Dhcp Enabled
Set-DnsClientServerAddress -InterfaceAlias $if -ResetServerAddresses
Enable-NetAdapter -Name "WLAN" -Confirm:$false       # 若第 4 步关过
ipconfig /renew
```

**改完在开发机上跑**（`.124` 能到就说明 395 还在 `.124`）：

```
python deploy\check_servers.py
```

预期四行都通过。

## 二、6000D（Ubuntu）：只核对，不改

6000D 本来就是静态 IP，服务也开机自启，10-03 没出问题。只核对一遍、记录结果。在 6000D 上运行（SSH 登录、无需 sudo）：

```bash
ip -4 addr show | grep 192.168.8.77            # 预期：inet 192.168.8.77/24 ... 不带 "dynamic"
ls /etc/netplan/ 2>/dev/null && grep -RnE "dhcp4|addresses" /etc/netplan/ 2>/dev/null
# 预期：dhcp4: false（或 no），addresses 含 192.168.8.77/24
nmcli -g ipv4.method,ipv4.addresses con show --active 2>/dev/null   # 若用 NetworkManager：预期 manual、192.168.8.77/24
systemctl is-enabled easytier-gw; systemctl show easytier-gw -p Restart   # 预期 enabled；Restart=always 或 on-failure
```

把输出贴给主编排，记进 `deploy\easytier\README.md`。如果核对出 `dhcp4: true`，或者地址带 `dynamic`：**先不要改**，交主编排定。改法同 395 的两条铁律：在本机控制台做，或先确认 `10.126.126.1` 这条通路可用。

## 三、请律所网管做 DHCP 地址保留（双保险）

固定 IP 防的是服务器自己换地址，还要防另一台设备被 DHCP 分到 `.124` 或 `.77`，导致地址冲突。请律所网管在路由器的 DHCP 设置里：

| 设备 | 地址 | 做法 |
|---|---|---|
| 395 有线网卡 | `192.168.8.124` | 按 MAC 地址保留（MAC 在 395 上 `Get-NetAdapter -Name 以太网 \| Select MacAddress`），或者把 `.124` 排除出 DHCP 地址池 |
| 6000D | `192.168.8.77` | 同上（MAC：`ip link show`） |

两种做法任选其一。最简单的是把 `.2`–`.99` 整段留作静态地址、DHCP 只发 `.100` 以上。做完请网管回一句"已保留"，记进 `deploy\easytier\README.md` 的变更记录。

## 附：10-03 实况

- **395 地址漂移**：DHCP 给了 `.32`，`.124` 上的服务全不可达。用户远程改静态时自己被踢下线；395 一度从网络上消失，到现场重启后回到 `.124`、`/health` ok。
- **EasyTier**：395 的 EasyTier 昨天是手动起的。重启后一度不在，后来网卡列表里又看到 `et_*` 网卡 Up。它是不是开机自启，**没查清**。服务化另见 `deploy\easytier\install_service_395.ps1` 和 `操作单-395停电后恢复.md`。
- **开发机**：线 C 写本单时顺带发现，开发机的"以太网"网卡上手动配了 `192.168.8.124`。网线没插，地址处于 Tentative，目前没有影响；但一插进律所网络就会和 395 抢地址。**请用户确认后改回自动获取**：开发机上 `Set-NetIPInterface -InterfaceAlias 以太网 -Dhcp Enabled`。
