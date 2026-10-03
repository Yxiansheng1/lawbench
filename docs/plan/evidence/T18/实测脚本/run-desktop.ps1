# T18 line B dev launch. ASCII only. Test home outside repo; ports distinct from line A.
param([string]$Log = 'D:\lawbench-T18\desktop.log')
$T = 'D:\lawbench-devhome-T18'
Set-Location D:\lawbench-B\dsh
$env:CI = 'true'
$env:PATH = 'D:\lawbench-T18\bin;' + $env:PATH
$env:npm_config_verify_deps_before_run = 'false'
$env:pnpm_config_verify_deps_before_run = 'false'
$env:COREPACK_ENABLE_NETWORK = '0'
$env:LOCALAPPDATA = "$T\Local"
$env:APPDATA = "$T\Roaming"
$env:DSH_HOME = "$T\dsh-home"
$env:DSH_DESKTOP_USER_DATA_DIR = "$T\electron-user-data"
$env:DSH_TELEMETRY_DISABLED = '1'
$env:DSH_DESKTOP_OPEN_DEVTOOLS = '0'
$env:DSH_DESKTOP_MAIN_INSPECT_PORT = '9329'
$env:DSH_DESKTOP_RENDERER_DEBUG_PORT = '9322'
$env:DSH_DESKTOP_HOST_INSPECT_PORT = '9330'
Remove-Item Env:LAWFIRM_KEY -ErrorAction SilentlyContinue
$env:LAWBENCH_SERVICE_CMD = '["D:\\lawbench-B\\service\\.venv\\Scripts\\python.exe","D:\\lawbench-T18\\svc_wrap.py"]'
$env:LAWBENCH_SERVICE_PORTS = '18901-18909'
$env:LAWBENCH_SERVICE_CWD = 'D:\lawbench-B\service'
$env:LAWBENCH_SKILLS_DIR = 'D:\lawbench-B\skills'
Remove-Item Env:DSH_TOOLS_MODE -ErrorAction SilentlyContinue
& pnpm.cmd run start:desktop *> $Log
