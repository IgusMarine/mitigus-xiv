# Mitigus XIV — engine nativo de Windows

[English](README.md) | **Português**

Mitigação de latência do FFXIV (o "double-weave fix") para **PS5**, rodando **100% no Windows** — sem Linux, sem VM, sem Raspberry Pi. É a evolução do *Weave Box* (a pasta-raiz deste repositório), que dependia de um notebook Linux rodando o `mitigate.py` por baixo. Aqui o mesmo efeito é reconstruído com captura de pacotes nativa (WinDivert) + proxy transparente.

> **Status: Fases 0–5 implementadas.** Captura (0), proxy transparente (1), opcodes (2), codec Oodle (3), **mitigação (4)** e **painel web (5)** prontos e cobertos por testes (26 testes; o algoritmo de mitigação é validado ponta-a-ponta com bundles sintéticos, e o mapeador PE contra a `kernel32.dll`). Falta validar **em hardware**: a cola WinDivert (`divert_nat.py`), o codec contra o `ffxiv_dx11.exe` (`run_oodle_test.py`), e a mitigação ao vivo no PS5 (`run_proxy.py --mitigate --panel`).

## Como funciona (visão geral)

```
PS5  --gateway-->  PC Windows  -------->  Roteador  -->  Servidores FFXIV
                       |
                       |  WinDivert (driver de kernel) desvia o TCP da zona
                       |  proxy transparente termina o TCP e recupera o destino
                       |  parse bundle/segment/IPC  +  Oodle decode (Fase 3)
                       |  mitigação: reescreve animation_lock  (Fase 4)
                       |  Oodle re-encode  ->  reenvia
```

O tráfego de jogo do FFXIV é **TCP em texto claro** (só comprimido), então não há criptografia a quebrar. O desafio real é o **Oodle** (compressão com estado por conexão, desde o patch 6.3) e colocar o PC no caminho do PS5 de forma confiável.

## Começo rápido (pra qualquer pessoa)

1. Instale o **Python** (em python.org, marcando "Add to PATH").
2. Tenha o `ffxiv_dx11.exe` no PC — se o FFXIV (ou o **trial gratuito**) já estiver instalado, o Mitigus **acha sozinho**; senão, o painel avisa e abre a pasta `windows\vendor\` pra você colar o arquivo (veja "Adicionar o ffxiv_dx11.exe").
3. Dê **dois cliques** em **`Iniciar Mitigus XIV.bat`** — ele pede Admin sozinho, instala o que falta, liga o roteamento e abre o painel.
4. No **painel** (abre no navegador/celular), siga o cartão **"Conectar o PS5"** — o IP do gateway já vem preenchido, com botão de copiar.
5. Ligue/desligue e ajuste a margem pelo painel. Pronto.

> Só quer ver a interface, sem PS5? Dê dois cliques em **`Painel (demo).bat`**.

## Requisitos

- Windows 10/11 x64
- Python 3.11+ (testado no 3.14)
- Privilégios de **Administrador** (o WinDivert carrega um driver de kernel)
- O `pydivert` (já empacota o WinDivert assinado): `pip install -r requirements.txt`

## Quickstart — Fase 0

Abra um terminal **como Administrador**, nesta pasta (`windows/`):

```powershell
pip install -r requirements.txt
```

**Opção A — validar o parser com o FFXIV neste PC** (mais confiável; se você tem o cliente PC / trial instalado). Abra o jogo e rode:

```powershell
python run_sniff.py --layer network
```

**Opção B — enxergar o PS5** (o objetivo final). Como Admin:

```powershell
.\setup\enable-routing.ps1          # habilita o PC como roteador, imprime o IP
# configure o gateway do PS5 = IP do PC (veja setup\PS5-SETUP.md)
python run_sniff.py --host <IP_DO_PS5>
```

Sucesso = aparecer o bloco **"FF14ARR detectado"** e os contadores subindo (`bundles=`, `comp[oodle=...]`, etc.). No Dawntrail a maioria dos bundles é Oodle — eles são contados, mas só serão decodificados na Fase 3.

Encerre com `Ctrl+C` para ver o resumo da sessão.

## Quickstart — Fase 1 (proxy transparente)

**Validar o data-path local** (sem Admin, sem WinDivert) — prova o relay + o hook de transform onde a mitigação vai entrar:

```powershell
python run_proxy.py --demo
```

**Modo real** (Admin; roteamento habilitado e gateway do PS5 = este PC):

```powershell
.\setup\enable-routing.ps1
python run_proxy.py --ps5-ip <IP_DO_PS5>
```

É passthrough: o PS5 deve jogar normalmente *através* do proxy, e cada fluxo novo aparece no log. A mitigação só entra na Fase 4 (nos hooks `on_c2s`/`on_s2c`).

Rodar os testes do núcleo:

```powershell
python -m unittest discover -s tests -v
```

## Quickstart — Fase 3 (Oodle)

Precisa do `ffxiv_dx11.exe` (x64). Como você é PS5-only, pegue-o instalando o **trial gratuito do FFXIV** num PC Windows (fica na pasta `game\` da instalação) e copie para `vendor\ffxiv_dx11.exe`. Então valide o codec:

```powershell
python run_oodle_test.py --exe C:\caminho\ffxiv_dx11.exe
```

Sucesso = `encode/decode Oodle (TCP e UDP) bateram`. Isso confirma o sigscan e o codec — a base que a Fase 4 usa para ler/reescrever os bundles do Dawntrail.

## Quickstart — Fase 4 (mitigação)

Junta tudo: o proxy passa a **reescrever o `animation_lock_duration`** (restaura o double-weave em ping alto). Como Admin, com o roteamento habilitado, o gateway do PS5 apontando pro PC, e o `ffxiv_dx11.exe` em mãos:

```powershell
python run_proxy.py --ps5-ip <IP_DO_PS5> --mitigate --exe C:\caminho\ffxiv_dx11.exe
```

Os opcodes são baixados/atualizados sozinhos (ou passe `--opcodes-json`). Nos logs `[mit] S2C_ActionEffect ... wait=600ms->NNNms` mostra o lock sendo cortado. A margem é `--extra-delay 0.075` (não diminua). Sem `--mitigate` o proxy é passthrough (Fase 1).

## Quickstart — Fase 5 (painel web)

Ver a UI ao vivo **sem PS5/Admin** (telemetria sintética):

```powershell
python run_panel.py        # abre em http://<seu-ip>:8080
```

No proxy real, adicione `--panel` para o painel mobile (liga/desliga + corte ao vivo) acessível do celular na mesma rede:

```powershell
python run_proxy.py --ps5-ip <IP> --mitigate --exe <ffxiv_dx11.exe> --panel
```

> O painel escuta só na LAN. **Nunca** faça port-forward dessa porta pra internet.

## Estrutura

```
windows/
├── Iniciar Mitigus XIV.bat   atalho 1-clique (auto-Admin + roteamento + painel)
├── Painel (demo).bat         atalho do painel demo (sem PS5/Admin)
├── Build (gerar exe).bat     gera o dist\Mitigus XIV.exe (PyInstaller)
├── mitigus_window.py         entry do .exe (janela frameless WebView2 + bandeja)
├── mitigus_xiv_native.spec   spec do PyInstaller (build do app, onedir)
├── mitigus.ico               ícone do app (gerado por tools/make_icon.py)
├── run_sniff.py              entrypoint da Fase 0 (sniffer)
├── run_proxy.py              entrypoint da Fase 1 (proxy transparente)
├── update_opcodes.py         baixa/atualiza definitions.json (Fase 2)
├── run_oodle_test.py         valida o Oodle contra o ffxiv_dx11.exe (Fase 3)
├── run_panel.py              painel web demo (Fase 5, sem PS5/Admin)
├── requirements.txt          pydivert
├── mitigus/
│   ├── paths.py              caminhos (modo fonte vs .exe empacotado)
│   ├── protocol/
│   │   ├── headers.py        structs ctypes + magic (port fiel do mitigate.py)
│   │   ├── bundle.py         reassembler de stream + decode (zlib/none)
│   │   ├── opcodes.py        OpcodeDefinition + loader (fonte XivAlexander)
│   │   └── ipc.py            structs de payload IPC (ActionEffect, etc.) + constantes
│   ├── net/
│   │   ├── ports.py          ranges de porta do FFXIV + filtro do WinDivert
│   │   └── adapters.py       checagem de Admin + IP da LAN
│   ├── capture/
│   │   └── sniffer.py        captura SNIFF (somente leitura)
│   ├── proxy/
│   │   ├── conntrack.py      mapa (PS5)->(servidor): o SO_ORIGINAL_DST que falta
│   │   ├── relay.py          relay asyncio que termina o TCP (hooks/processor)
│   │   └── divert_nat.py     NAT userland WinDivert (DNAT/SNAT) — validar em hardware
│   ├── oodle/
│   │   ├── pe.py             mapeador PE manual x64 (testado vs kernel32)
│   │   ├── oodle.py          sigscan + codec Oodle (chamada nativa, sem thunk)
│   │   └── locate.py         acha o ffxiv_dx11.exe (instalador SE + Steam)
│   ├── mitigation/
│   │   ├── stats.py          NumericStatisticsTracker + PendingAction
│   │   └── mitigator.py      reescrita do animation_lock + double-weave (Fase 4)
│   └── panel/
│       ├── hub.py            ControlHub (liga/desliga + telemetria, thread-safe)
│       ├── server.py         servidor HTTP do painel (stdlib)
│       └── index.html        UI mobile (liga/desliga + corte ao vivo)
├── tests/                    26 testes (mitigação, painel, PE, opcodes, relay, conntrack)
└── setup/
    ├── enable-routing.ps1    PC vira roteador (IP forwarding, sem ICS/NAT)
    ├── disable-routing.ps1   reverte
    └── PS5-SETUP.md          IP fixo + gateway no PS5
```

## Roadmap

- **Fase 0 — captura:** ver o `FF14ARR` do PS5. ✅ implementado
- **Fase 1 — proxy transparente:** WinDivert desvia o fluxo para um listener local; relay `asyncio` termina o TCP e abre socket upstream (resolve seq/ack e o caminho de volta de NIC única). ✅ núcleo (conntrack+relay) testado; ⏳ cola WinDivert (`divert_nat.py`) a validar em hardware.
- **Fase 2 — opcodes:** `OpcodeDefinition` (port fiel) + loader/atualizador cross-platform da fonte XivAlexander (`update_opcodes.py`). ✅ implementado e testado
- **Fase 3 — Oodle:** mapeador PE manual (`pe.py`, ✅ testado vs kernel32) + sigscan e codec por canal (`oodle.py`, chamada nativa — sem os thunks de ABI do Linux). ⏳ validar o codec contra o `ffxiv_dx11.exe` (`run_oodle_test.py`).
- **Fase 4 — mitigação:** `PendingAction` por sequence, casa ActionRequest↔Effect, reescreve `animation_lock_duration` (margem `extra_delay=0.075` — não diminuua), gating de double-weave, IPC custom OriginalWaitTime. ✅ implementado e testado (bundles sintéticos); ⏳ validar ao vivo no PS5 (`run_proxy.py --mitigate`).
- **Fase 5 — painel + UX:** UI mobile redesenhada (liga/desliga, corte ao vivo, slider de margem, guia de conexão do PS5 com IP preenchido, checklist de saúde) + atalho 1-clique (`Iniciar Mitigus XIV.bat`) e `--ps5-ip` opcional (capta o PS5 sozinho). ✅ implementado e testado (29 testes; UI verificada por screenshot).
- **Fase 6 — empacotamento `.exe`:** onefile via PyInstaller (`Build (gerar exe).bat`), com o driver WinDivert e o painel embutidos, manifesto UAC (pede Admin sozinho) e caminhos cientes do modo congelado. O `ffxiv_dx11.exe` do jogo **não** vai no pacote (é achado/colado pelo usuário). ✅ implementado e build validado.
- **Fase 7 — ícone:** cristal teal original (`mitigus.ico`, gerado por `tools/make_icon.py`), embutido no `.exe`. ✅ feito.
- **Fase 8+ — refino measure_ping (RTT real do Windows via SIO_TCP_INFO).**

## Adicionar o ffxiv_dx11.exe

O `ffxiv_dx11.exe` é o **executável do jogo** (da Square Enix). O codec de compressão Oodle vem dentro dele — sem o arquivo, não dá pra ler os pacotes do Dawntrail. Por copyright/tamanho, ele **não acompanha o projeto**; você fornece (igual ao XivMitm/XivAlexander originais).

- **Quem joga no PS5** não tem o jogo no PC. Solução: instale o **trial gratuito do FFXIV** (não precisa de assinatura) em qualquer PC Windows. O arquivo fica em `...\FINAL FANTASY XIV - A Realm Reborn\game\ffxiv_dx11.exe`.
- **Detecção automática:** se o jogo (ou o trial) estiver instalado, o Mitigus acha o `.exe` sozinho (instalador da Square Enix e bibliotecas do Steam). Você não precisa copiar nada.
- **Se não achar:** o painel mostra *"falta o ffxiv_dx11.exe"* e a pasta `windows\vendor\` abre sozinha — é só colar o arquivo lá e reiniciar.
- Precisa ser o **x64** (`ffxiv_dx11.exe`, não o antigo `ffxiv.exe`). Ele **quase nunca precisa ser trocado** — só os *opcodes* mudam por patch (e esses se atualizam sozinhos); o Oodle só muda em raras ocasiões.

## Gerar o `.exe` (dispensa instalar Python no PC do usuário)

Dois cliques em **`Build (gerar exe).bat`** gera **duas versões** em `dist\` (~10 MB cada), que já trazem dentro o driver WinDivert e o painel, pedem Administrador (UAC), ligam o roteamento e sobem o painel:

- **`Mitigus XIV.exe`** — abre o painel no **navegador** padrão.
- **`Mitigus XIV (janela).exe`** — abre numa **janela própria** (Edge em modo `--app`, sem abas/barra de endereço; cai pro navegador se não houver Edge/Chrome).
- **`Mitigus XIV (sem console).exe`** — roda em **segundo plano**, `console=False`, com **ícone na bandeja** (pystray): clique direito → "Abrir painel" / "Sair". Maior (~16 MB, embute pystray+Pillow). Tudo continua no `mitigus.log`; erros saem numa caixinha do Windows.

- O `ffxiv_dx11.exe` do jogo **NÃO** vai dentro do `.exe` (é copyright da Square Enix). Ele é achado na sua instalação/trial, ou colado em `dist\vendor\`.
- Conferir o pacote sem precisar de Admin: `"dist\Mitigus XIV.exe" --selfcheck`.

## Opcodes (atualização a cada patch)

Os opcodes (os IDs que dizem "que pacote é este") são **embaralhados pela Square Enix a cada patch** — é o que mais quebra. O Mitigus os carrega de um JSON externo que se atualiza sozinho (fonte XivAlexander), escolhe a tabela certa pelo IP do servidor, e tem **botão "atualizar" no painel** (mostra a data do patch em uso).

- Quando o FFXIV atualizar: clique em **atualizar** no painel (ou rode `python update_opcodes.py`). Pode levar de horas a 1–2 dias até a comunidade publicar os opcodes de um patch grande.
- Os opcodes são **globais por patch** (JP/NA/EU = mesma versão = mesmos opcodes; só CN/KR diferem). A tabela atual cobre **NA/Aether** (faixa `204.2.29.0/24`), então a fonte padrão já serve.
- Se um dia o painel mostrar **"opcodes não cobrem seu servidor"**, atualize, ou passe um arquivo próprio com `--opcodes-json seu_arquivo.json`.

## Log / diagnóstico

Toda sessão do proxy grava um **`mitigus.log`** (ao lado do `.exe` / em `windows\`) com tudo que aparece na tela: os `[nat] novo fluxo...`, os `[mit] S2C_ActionEffect wait=600ms->NNNms`, e erros. O painel também mostra o caminho do arquivo no cartão "Registro de eventos". É esse arquivo (+ um print do "Status do sistema") que serve para analisar/ajustar a interceptação depois do teste no PS5.

## Aviso (ToS)

Ferramentas de terceiros que leem/modificam o tráfego do FFXIV violam o User Agreement da Square Enix (categoria "packet spoofing", citada como prioridade em 2022). Não há anti-cheat de kernel e a fiscalização é reativa, mas o risco **não é zero** e a decisão é sua, sobre a sua própria conta. Este projeto é para fins técnicos/educacionais.

## Créditos

- [XivMitmLatencyMitigator](https://github.com/Soreepeong/XivMitmLatencyMitigator) e [XivAlexander](https://github.com/Soreepeong/XivAlexander) (Soreepeong) — a técnica de mitigação e a fonte dos opcodes.
- [WinDivert](https://github.com/basil00/WinDivert) (basil00) — interceptação de pacotes em userland no Windows.
- Fonte [Chakra Petch](https://fonts.google.com/specimen/Chakra+Petch) (SIL OFL 1.1).
