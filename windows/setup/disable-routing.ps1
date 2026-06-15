#Requires -RunAsAdministrator
<#
  Mitigus XIV - reverte o roteamento habilitado por enable-routing.ps1.
  Rode isto quando terminar de testar, para o PC voltar a ser um host normal.
#>
$ErrorActionPreference = "Stop"

Write-Host "=== Mitigus XIV - desabilitar roteamento ===" -ForegroundColor Cyan

Set-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters" `
  -Name "IPEnableRouter" -Value 0 -Type DWord
Write-Host "[ok] IPEnableRouter = 0"

Get-NetIPInterface -AddressFamily IPv4 -ConnectionState Connected |
  Set-NetIPInterface -Forwarding Disabled
Write-Host "[ok] forwarding desabilitado nas interfaces IPv4 ativas"

try {
    Stop-Service -Name RemoteAccess -Force -ErrorAction Stop
    Set-Service -Name RemoteAccess -StartupType Manual
    Write-Host "[ok] servico RemoteAccess parado e em Manual"
} catch {
    Write-Host "[aviso] nao foi possivel parar o RemoteAccess: $($_.Exception.Message)"
}

Write-Host ""
Write-Host "Lembre de reverter o 'Gateway padrao' do PS5 para o IP do roteador."
