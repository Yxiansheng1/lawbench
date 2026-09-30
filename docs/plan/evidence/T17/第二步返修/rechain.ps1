# 在基线克隆里从 477b4f4 重建补丁链：P-10 P-12 P-13 P-3 原样；P-5 起每个补丁"原补丁 + 本轮增补脚本"后提交，并重新导出补丁文件。
$ErrorActionPreference = 'Stop'
$b = 'C:\Users\<用户>\AppData\Local\Temp\claude\D--lawbench-A\83a515fe-3091-4d1d-bb29-68b2364c0be5\scratchpad\dsh-base'
$d = 'C:\Users\<用户>\AppData\Local\Temp\claude\D--lawbench-A\83a515fe-3091-4d1d-bb29-68b2364c0be5\scratchpad'
$P = 'D:\lawbench-A\dsh-patches'
$old = 'C:\Users\<用户>\AppData\Local\Temp\claude\D--lawbench-A\83a515fe-3091-4d1d-bb29-68b2364c0be5\scratchpad\patches-old'
git -C $b checkout -q -B chain2 477b4f4205
foreach ($n in 'P-10-profile-lawbench-dsh','P-12-desktop-no-office','P-13-desktop-no-open-config','P-3-first-run-page') {
  git -C $b apply "$old\$n.patch"; if ($LASTEXITCODE) { throw "apply $n" }
}
git -C $b add -A; git -C $b commit -q -m 'base: P-10 P-12 P-13 P-3'
$chain = @(
  @('P-5-conversation-file-intake', 'd-p5.py'),
  @('P-9-default-session-request-whitelist', 'd-p9.py'),
  @('P-14-fail-closed-without-lawbench-bundle', $null),
  @('P-15-api-file-allowed-roots', 'd-p15.py'),
  @('P-16-citation-inline-marks', $null),
  @('P-17-links-never-open', 'd-p17.py'),
  @('P-18-no-mention-hint-no-developer-switch', 'd-p18.py')
)
foreach ($c in $chain) {
  $n = $c[0]
  git -C $b apply "$old\$n.patch"; if ($LASTEXITCODE) { throw "apply $n" }
  if ($c[1]) { python "$d\$($c[1])" $b; if ($LASTEXITCODE) { throw "delta $n" } }
  git -C $b add -A; git -C $b commit -q -m $n
  git -C $b diff HEAD~1 HEAD --output="$P\$n.patch"
  "$n -> $((Get-Item "$P\$n.patch").Length) bytes"
}
