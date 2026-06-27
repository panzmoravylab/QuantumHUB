# Ukonci stare instance Quantum HUD (app.py z P_MONITOR)
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like '*P_MONITOR*' -and $_.CommandLine -like '*app.py*' } |
    ForEach-Object {
        Write-Host "      Ukoncuji HUD PID $($_.ProcessId)"
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
