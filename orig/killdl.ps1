Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -like '*dl_par.py*' -or $_.CommandLine -like '*dl_ace.py*' -or $_.CommandLine -like '*orig/dl.sh*' -or $_.Name -eq 'curl.exe' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Write-Host "cleaned"
