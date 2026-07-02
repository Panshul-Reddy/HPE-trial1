$ErrorActionPreference = "Stop"

# --- Configuration ---
$ProjectRoot = $PSScriptRoot
$LogDir = Join-Path $ProjectRoot "logs"

Write-Host "=== FastFlow Live Demo (Windows) ===" -ForegroundColor Cyan

# 1. Clean Ports
$portsToClean = @(5050, 8440, 8441, 8442, 8443, 8444, 8445, 9443, 9999)
Write-Host "[1/5] Cleaning up ports..." -ForegroundColor Yellow
foreach ($port in $portsToClean) {
    $conns = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
    foreach ($conn in $conns) {
        $proc = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
        if ($proc) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }
    }
}

if (!(Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }

# 1.5 Setup Python Environments
Write-Host "[1.5/5] Setting up Python Environments..." -ForegroundColor Yellow
$PythonServices = @("classifier", "proxy", "groq-client", "noise-client")
foreach ($dir in $PythonServices) {
    $FullDir = Join-Path $ProjectRoot $dir
    Set-Location $FullDir
    if (!(Test-Path ".venv")) {
        Write-Host "  Creating venv in $dir..." -ForegroundColor Gray
        python -m venv .venv
    }
    if (Test-Path "requirements.txt") {
        Write-Host "  Installing requirements in $dir..." -ForegroundColor Gray
        & .\.venv\Scripts\python.exe -m pip install -r requirements.txt | Out-Null
    }
}

# 2. Docker
Write-Host "[2/5] Starting backend containers (Docker)..." -ForegroundColor Yellow
Set-Location $ProjectRoot
docker compose up -d mcp-servers noise-server

# 3. Python Services
Write-Host "[3/5] Starting Python Services (API, Proxy, Clients)..." -ForegroundColor Yellow

# Function to start process with logs
function Start-PythonService {
    param(
        [string]$Name,
        [string]$Dir,
        [string]$Command,
        [string]$LogName,
        [string]$EnvVarName = $null,
        [string]$EnvVarValue = $null
    )
    Write-Host "  Starting $Name..." -ForegroundColor Cyan
    
    $FullDirPath = Join-Path $ProjectRoot $Dir
    $LogFilePath = Join-Path $ProjectRoot "logs\$LogName"

    # Set up environment variables for the process if needed
    if ($EnvVarName) {
        [Environment]::SetEnvironmentVariable($EnvVarName, $EnvVarValue, "Process")
    }
    
    # We use cmd.exe /c to launch the process and redirect both stdout and stderr (2>&1)
    # into the same log file, bypassing PowerShell's Start-Process limitations.
    $Exe = if ($Command -match "^uvicorn") { "$FullDirPath\.venv\Scripts\uvicorn.exe" } else { "$FullDirPath\.venv\Scripts\python.exe" }
    
    $ArgsArray = $Command -split ' ' | Where-Object { $_ -ne '' }
    $ArgsStr = ($ArgsArray[1..($ArgsArray.Length-1)]) -join ' '

    $CmdLine = "`"$Exe`" $ArgsStr > `"$LogFilePath`" 2>&1"
    Start-Process cmd.exe -ArgumentList "/c", $CmdLine -WorkingDirectory $FullDirPath -WindowStyle Hidden
}

# Start API
Start-PythonService -Name "API" -Dir "classifier" -Command "uvicorn api:app --port 5050" -LogName "api.log"

# Wait a second for API to bind
Start-Sleep -Seconds 2

# Start Proxy
$ProxyArgs = "tls_proxy.py --cert `"$ProjectRoot\nginx\ssl\mcp.crt`" --key `"$ProjectRoot\nginx\ssl\mcp.key`" --mappings 8440:3000,8441:3001,8442:3002,8443:3003,8444:3004,8445:3005,9443:9444 --backend-host 127.0.0.1"
Start-PythonService -Name "Proxy" -Dir "proxy" -Command "python $ProxyArgs" -LogName "proxy.log"

Start-Sleep -Seconds 1

# Start Groq Client
Start-PythonService -Name "Groq Client" -Dir "groq-client" -Command "python groq_mcp_client.py" -LogName "groq.log" -EnvVarName "VM1_IP" -EnvVarValue "127.0.0.1"

# Start Noise Client
Start-PythonService -Name "Noise Client" -Dir "noise-client" -Command "python client.py" -LogName "noise.log" -EnvVarName "NOISE_SERVER" -EnvVarValue "https://127.0.0.1:9443"

# 4. Open UI
Write-Host "[4/5] Opening Dashboard..." -ForegroundColor Yellow
Start-Process "http://localhost:5050"

# 5. Build and Run Rust Extractor
Write-Host "[5/5] Compiling and Running Rust Extractor..." -ForegroundColor Yellow
Set-Location "$ProjectRoot\rust-extractor"
cargo build --release

Write-Host "`nAll background services are running. Rust TUI will launch now." -ForegroundColor Green
Write-Host "Press Ctrl+C inside the TUI to exit everything.`n" -ForegroundColor Cyan

cargo run --release --bin live-analyzer -- --interface \Device\NPF_Loopback --inference-url http://localhost:5050

# Cleanup on exit
Write-Host "`nCleaning up background processes..." -ForegroundColor Yellow
foreach ($port in $portsToClean) {
    $conns = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
    foreach ($conn in $conns) {
        $proc = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
        if ($proc) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }
    }
}
Write-Host "Done." -ForegroundColor Green
