#Requires -RunAsAdministrator
<#
  Mitigus XIV - habilita este PC como roteador para o PS5 (topologia NIC unica).

  Necessario na Fase 0: com o "Gateway padrao" do PS5 apontando para este PC, o
  PS5 so mantem internet se o PC encaminhar os pacotes (IP forwarding). Usamos
  roteamento PURO, NAO o ICS/NAT do Windows (que conflita com o WinDivert).

  Observacao honesta: em NIC unica e mesma sub-rede, o Windows pode emitir ICMP
  redirects mandando o PS5 falar direto com o roteador, e o trafego de VOLTA
  (servidor -> PS5) tende a pular o PC. Isso e suficiente para a Fase 0 (so
  OBSERVAR a saida). A interceptacao confiavel dos dois sentidos vem na Fase 1
  com o proxy transparente, que termina o TCP e origina a conexao do proprio PC.

  Reverter:  setup\disable-routing.ps1
#>
$ErrorActionPreference = "Stop"

Write-Host "=== Mitigus XIV - habilitar roteamento ===" -ForegroundColor Cyan

# 1) IP forwarding global (persiste no boot)
Set-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters" `
  -Name "IPEnableRouter" -Value 1 -Type DWord
Write-Host "[ok] IPEnableRouter = 1"

# 2) Forwarding por interface (IPv4, interfaces conectadas)
Get-NetIPInterface -AddressFamily IPv4 -ConnectionState Connected |
  Set-NetIPInterface -Forwarding Enabled
Write-Host "[ok] forwarding habilitado nas interfaces IPv4 ativas"

# 3) Servico de roteamento (aplica o forwarding sem reboot)
Set-Service -Name RemoteAccess -StartupType Automatic
Start-Service -Name RemoteAccess
Write-Host "[ok] servico RemoteAccess iniciado"

# 4) Mostra o IP da LAN para usar como Gateway no PS5
$cfg = Get-NetIPConfiguration |
  Where-Object { $_.IPv4DefaultGateway -ne $null -and $_.NetAdapter.Status -eq "Up" } |
  Select-Object -First 1
$ip = $cfg.IPv4Address.IPAddress

Write-Host ""
Write-Host "No PS5, defina 'Gateway padrao' como:  $ip" -ForegroundColor Green
Write-Host "DNS no PS5: o IP do seu roteador, ou 1.1.1.1"
Write-Host ""
Write-Host "Depois, COMO ADMIN:  python run_sniff.py --host <IP_DO_PS5>"
