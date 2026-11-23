Add-Type -AssemblyName System.Windows.Forms
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = 'Select the anima-cloudflare folder containing .private and anima-client'
$dialog.ShowNewFolderButton = $false
if ($dialog.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { exit 2 }
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
[Console]::WriteLine($dialog.SelectedPath)
