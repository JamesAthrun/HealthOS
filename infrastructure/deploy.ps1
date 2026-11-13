<#
.SYNOPSIS
  一条命令部署 HealthOS 到阿里云服务器（需要已配置好的 workbench CLI）。

.DESCRIPTION
  1. 检查工作区干净、当前提交已推送
  2. 本地构建前端（npm run build）
  3. 打包当前提交的源码（git archive）和 frontend/out
  4. 用 workbench 上传，并在服务器后台运行 infrastructure/deploy-remote.sh
  5. 轮询输出直到 DONE 或 FAILED

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File infrastructure/deploy.ps1
#>
param(
    [string]$InstanceId = "i-uf6fzv82ry299hiewi24",
    [string]$Region = "cn-shanghai",
    [switch]$SkipBuild,
    [switch]$AllowDirty
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$repo = Split-Path -Parent $PSScriptRoot
$wb = Join-Path $env:LOCALAPPDATA "Programs\workbench\workbench.exe"
if (-not (Test-Path $wb)) { throw "找不到 workbench：$wb" }
Set-Location $repo

function Invoke-Native([scriptblock]$block) {
    # Windows PowerShell 5.1 在 Stop 模式下会把原生命令写到 stderr 的正常输出当成错误
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { return (& $block 2>&1 | ForEach-Object { "$_" }) -join "`n" } finally { $ErrorActionPreference = $previous }
}

function Invoke-Remote([string]$command) {
    return Invoke-Native { & $wb exec --instance-id $InstanceId --region $Region --command $command }
}

function Send-File([string]$path) {
    $out = Invoke-Native { & $wb upload $path /tmp/ -i $InstanceId -r $Region -f }
    if ($out -notmatch "Upload complete") { throw "上传失败：$path`n$out" }
    Write-Host "已上传 $(Split-Path -Leaf $path)"
}

# 1. 工作区检查
$dirty = git status --porcelain
if ($dirty -and -not $AllowDirty) { throw "工作区有未提交的改动（git archive 只会打包已提交的内容）。先提交，或加 -AllowDirty。" }
$head = (git rev-parse --short HEAD).Trim()
$branch = (git rev-parse --abbrev-ref HEAD).Trim()
Invoke-Native { git fetch origin } | Out-Null
$behind = (git rev-list --count "HEAD..origin/$branch" 2>$null)
if ($behind -and [int]$behind -gt 0) { throw "本地落后 origin/$branch $behind 个提交，先合并再部署。" }
Write-Host "部署 $branch @ $head"

# 2. 前端构建
if (-not $SkipBuild) {
    Push-Location frontend
    try {
        npm run build | Select-Object -Last 3 | Write-Host
        if ($LASTEXITCODE -ne 0) { throw "前端构建失败" }
    } finally { Pop-Location }
}

# 3. 打包（脚本必须是 LF 换行）
$tmp = Join-Path $env:TEMP "healthos-deploy"
New-Item -ItemType Directory -Force $tmp | Out-Null
$src = Join-Path $tmp "healthos-src.tgz"
$web = Join-Path $tmp "healthos-web.tgz"
$remote = Join-Path $tmp "healthos-deploy.sh"
git -c core.autocrlf=false archive --format=tar.gz -o $src HEAD
tar -czf $web -C frontend/out .
[IO.File]::WriteAllText($remote, [IO.File]::ReadAllText((Join-Path $repo "infrastructure\deploy-remote.sh")).Replace("`r", ""))

# 4. 上传并后台运行
Send-File $src
Send-File $web
Send-File $remote
Invoke-Remote "rm -f /tmp/healthos-deploy.out; nohup bash /tmp/healthos-deploy.sh > /tmp/healthos-deploy.out 2>&1 & echo started" | Write-Host

# 5. 轮询结果（workbench exec 单次最多约 30 秒）
for ($i = 0; $i -lt 30; $i++) {
    $out = Invoke-Remote "sleep 20; cat /tmp/healthos-deploy.out"
    if ($out -match "DONE|FAILED") {
        Write-Host $out
        Invoke-Remote "rm -f /tmp/healthos-deploy.sh" | Out-Null
        if ($out -match "FAILED") { throw "部署失败，见上方输出" }
        Write-Host "部署完成：$branch @ $head"
        exit 0
    }
    Write-Host "…进行中（$(($i + 1) * 20) 秒）"
}
throw "等待超时，请到服务器查看 /tmp/healthos-deploy.out"
