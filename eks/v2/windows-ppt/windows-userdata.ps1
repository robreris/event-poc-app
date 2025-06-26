$region = $args[0]
$clusterName = $args[1]

# Waiting for initialization 
$ErrorActionPreference = "Stop"
$log = "C:\setup-log.txt"
"UserData script started" | Out-File $log -Append
"Running as user: $([System.Security.Principal.WindowsIdentity]::GetCurrent().Name)" | Out-File $log -Append
"Current directory: $(Get-Location)" | Out-File $log -Append

# --- POLL FOR NETWORK AVAILABILITY ---
$maxAttempts = 20
$attempt = 1
"Polling for networking..." | Out-File $log -Append
while ($attempt -le $maxAttempts) {
    try {
        $response = Invoke-WebRequest -Uri "http://www.msftconnecttest.com/connecttest.txt" -UseBasicParsing -TimeoutSec 5
        if ($response.StatusCode -eq 200) {
            "Networking ready after $attempt attempt(s)." | Out-File $log -Append
            break
        }
    } catch {
        "Network not ready, attempt $attempt" | Out-File $log -Append
        Start-Sleep -Seconds 10
        $attempt++
    }
}
if ($attempt -gt $maxAttempts) {
    "Networking NOT available after $maxAttempts attempts. Exiting." | Out-File $log -Append
    exit 1
}

# --- DOWNLOAD PYTHON INSTALLER ---
$pythonInstaller = "C:\python-installer.exe"
try {
    Invoke-WebRequest -Uri "https://www.python.org/ftp/python/3.12.3/python-3.12.3-amd64.exe" -OutFile $pythonInstaller -ErrorAction Stop
    "Python installer downloaded." | Out-File $log -Append
} catch {
    "Python installer download FAILED: $_" | Out-File $log -Append
    exit 1
}

# --- INSTALL PYTHON ---
if (Test-Path $pythonInstaller) {
    try {
        Start-Process $pythonInstaller -ArgumentList '/quiet InstallAllUsers=1 PrependPath=1' -Wait -ErrorAction Stop
        "Python installer ran." | Out-File $log -Append
    } catch {
        "Python installer FAILED to run: $_" | Out-File $log -Append
        exit 1
    }
} else {
    "Python installer missing after download attempt." | Out-File $log -Append
    exit 1
}

# --- VERIFY PYTHON INSTALLATION ---
$pythonPath = "C:\Program Files\Python312\python.exe"
if (Test-Path $pythonPath) {
    try {
        & $pythonPath --version | Out-File $log -Append
        "Python installed successfully." | Out-File $log -Append
        $env:Path += ";C:\Program Files\Python312\Scripts"
        pip install pika pywin32 boto3
    } catch {
        "Python version check failed: $_" | Out-File $log -Append
    }
} else {
    "Python executable not found at $pythonPath." | Out-File $log -Append
}

# Install AWS CLI v2
Invoke-WebRequest -Uri https://awscli.amazonaws.com/AWSCLIV2.msi -OutFile awscliv2.msi
Start-Process msiexec.exe -ArgumentList '/i awscliv2.msi /quiet' -Wait
Remove-Item awscliv2.msi
$env:Path += ";C:\Program Files\Amazon\AWSCLIV2"
$maxRetries = 10
$retry = 0
while ($retry -lt $maxRetries) {
    try {
        aws --version > $null 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Output "AWS CLI is available."
            break
        }
    } catch {
        # no-op
    }
    Write-Output "Waiting for AWS CLI to become available..."
    Start-Sleep -Seconds 5
    $retry++
}

if ($retry -eq $maxRetris) {
    Write-Error "AWS CLI did not become available in time. Exiting..."
    exit 1
}

# Download Office Deployment Tool (ODT) to C:\odt
New-Item -Path "C:\odt" -ItemType Directory -Force | Out-Null
Invoke-WebRequest -Uri "https://download.microsoft.com/download/6c1eeb25-cf8b-41d9-8d0d-cc1dbc032140/officedeploymenttool_18827-20140.exe" -OutFile "C:\odt\OfficeDeploymentTool.exe"
Start-Process "C:\odt\OfficeDeploymentTool.exe" -ArgumentList "/extract:C:\odt /quiet" -Wait

# custom xml configuration for ODT
$odtConfig = @"
<Configuration>
  <Add OfficeClientEdition="64" Channel="MonthlyEnterprise">
    <Product ID="O365BusinessRetail">
      <Language ID="en-us" />
      <ExcludeApp ID="Access"/>
      <ExcludeApp ID="Excel"/>
      <ExcludeApp ID="OneNote"/>
      <ExcludeApp ID="Outlook"/>
      <ExcludeApp ID="Publisher"/>
      <ExcludeApp ID="Teams"/>
      <ExcludeApp ID="Word"/>
    </Product>
  </Add>
  <Display Level="None" AcceptEULA="TRUE"/>
  <Property Name="AUTOACTIVATE" Value="1"/>
</Configuration>
"@
$odtConfig | Out-File -FilePath "C:\odt\config.xml" -Encoding UTF8     

# Run ODT to install just PowerPoint
Start-Process "C:\odt\setup.exe" -ArgumentList "/configure C:\odt\config.xml" -Wait

# Create working directory for powperpoint objects
New-Item -Path "C:\shared-artifacts" -ItemType Directory -Force | Out-Null

# Set up RabbitMQ
$rabbitmqhost = aws ssm get-parameter --name "/$clusterName/rabbithost" --with-decryption --region $region --query 'Parameter.Value' --output text
$rabbitmqusername = aws ssm get-parameter --name "/$clusterName/rabbitusername" --with-decryption --region $region --query 'Parameter.Value' --output text
$rabbitmqpassword = aws ssm get-parameter --name "/$clusterName/rabbitpassword" --with-decryption --region $region --query 'Parameter.Value' --output text

# Set for current session
$env:RABBITMQ_HOST=$rabbitmqhost
$env:RABBITMQ_USER=$rabbitmqusername
$env:RABBITMQ_PASS=$rabbitmqpassword

# Set for future sessions
[System.Environment]::SetEnvironmentVariable("RABBITMQ_HOST", $rabbitmqhost, "Machine")
[System.Environment]::SetEnvironmentVariable("RABBITMQ_USER", $rabbitmqusername, "Machine")
[System.Environment]::SetEnvironmentVariable("RABBITMQ_PASS", $rabbitmqpassword, "Machine")

## Prepare working directory for agent and download agent.py from GitHub
$scriptDir = "C:\render-agent"
$scriptFile = "$scriptDir\agent.py"
$logDir = "C:\Temp"
New-Item -Path $scriptDir -ItemType Directory -Force | Out-Null
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/robreris/event-poc-app/refs/heads/main/eks/v2/windows-ppt/windows-agent-setup.py" -OutFile $scriptFile

$logFile = "$logDir\rabbitworker.log"

# Register scheduled task
$taskName = "StartRabbitWorker"
$escapedScriptPath = $scriptFile -replace '\\', '\\'
$command = "python `"$escapedScriptPath`" >> `"$logFile`" 2>&1"

## Schedule task to run agent on system startup
schtasks /Create /TN $taskName /TR $command /SC ONSTART /RU SYSTEM /RL HIGHEST

# Start the task now
Start-Process -FilePath python -ArgumentList $scriptFile -NoNewWindow
#Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "`"$command`"" -NoNewWindow 

