Get-CimInstance Win32_Process -Filter "Name='curl.exe'" |
  Where-Object { $_.CommandLine -like '*google/umt5-base*' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Write-Host "curl(umt5) stopped"
