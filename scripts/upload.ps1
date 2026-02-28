# -------------------------------------------------------------
# upload.ps1  -  Upload videos and transcripts to the server
#
# Run from your local Windows machine (PowerShell):
#   .\upload.ps1
#
# Or pass files directly:
#   .\upload.ps1 "C:\Videos\lecture.mp4" "C:\transcripts\notes.pkl"
#
# Set SERVER below to your server's user@host or IP.
# -------------------------------------------------------------

$SERVER     = "ubuntu@YOUR_SERVER_IP_OR_HOSTNAME"
$REMOTE_DIR = "/home/ubuntu/youtube-project/uploads"

# -- File picker ----------------------------------------------
function Pick-Files {
    Add-Type -AssemblyName System.Windows.Forms

    $dialog = New-Object System.Windows.Forms.OpenFileDialog
    $dialog.Title       = "Select video or transcript files to upload"
    $dialog.Filter      = "Videos and Transcripts|*.mp4;*.mkv;*.mov;*.avi;*.webm;*.pkl|All Files|*.*"
    $dialog.Multiselect = $true

    $dummy = New-Object System.Windows.Forms.Form
    $dummy.TopMost = $true

    if ($dialog.ShowDialog($dummy) -eq [System.Windows.Forms.DialogResult]::OK) {
        return $dialog.FileNames
    }
    return @()
}

# -- Collect files (CLI args or picker) -----------------------
if ($args.Count -gt 0) {
    $files = $args
} else {
    $files = Pick-Files
    if ($files.Count -eq 0) {
        Write-Host "No files selected."
        exit 0
    }
}

# -- Upload each file -----------------------------------------
$allowed = @("mp4","mkv","mov","avi","webm","pkl")

foreach ($file in $files) {
    if (-not (Test-Path $file)) {
        Write-Host "ERROR: File not found: $file"
        continue
    }

    $ext  = [System.IO.Path]::GetExtension($file).TrimStart(".").ToLower()
    $name = [System.IO.Path]::GetFileName($file)

    if ($allowed -contains $ext) {
        Write-Host "Uploading: $name -> ${SERVER}:${REMOTE_DIR}/"
        scp $file "${SERVER}:${REMOTE_DIR}/"
        if ($LASTEXITCODE -eq 0) {
            Write-Host "[OK] Done: $name"
        } else {
            Write-Host "[FAILED] $name"
        }
    } else {
        Write-Host "Skipping unsupported file type: $name (.$ext)"
    }
}
