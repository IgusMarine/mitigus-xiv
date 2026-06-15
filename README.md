# Weave Box

Um painel web simples que transforma um notebook x86 velho numa appliance de
mitigação de latência para FFXIV. Ele roda o script provado da comunidade
(`XivMitmLatencyMitigator`) por baixo, e te dá um botão de liga/desliga acessível
do celular, com telemetria ao vivo do corte de animation lock.

Pensado para quem joga **no PS5** (ou PS4/console), onde plugins e addons não
existem. A interceptação acontece na rede, então não importa o que roda o jogo.

```
   PS5  ──gateway──►  Notebook (Linux)  ──►  Roteador  ──►  Servidores Aether
                          │
                          ├─ mitigate.py   (intercepta e corta o lock)
                          └─ Weave Box     (painel web :8080)  ◄── celular liga/desliga
```

---

## O que você precisa

- **Um notebook x86-64** (Intel/AMD). **Não pode ser ARM.** O script carrega o
  `ffxiv_dx11.exe` e executa as funções de compressão Oodle como código nativo
  x64, então um Raspberry Pi ou qualquer ARM não roda isso.
- O notebook e o PS5 na **mesma rede**. De preferência o notebook no **cabo**
  (rotear tráfego de jogo por Wi-Fi adiciona jitter).
- Acesso ao roteador para reservar um IP fixo pro notebook (ou setar IP estático).

---

## Passo 1 — Botar Linux no notebook

Esse notebook vira dedicado. Instale um Linux leve, por exemplo
**Ubuntu Server 24.04** (sem ambiente gráfico, é uma appliance). Durante a
instalação, habilite o OpenSSH pra você administrar de longe.

> Se quiser testar antes de formatar, dá pra rodar de um pendrive Live com
> persistência. Mas pro uso real, instale no disco.

Depois de instalar, atualize e garanta o Python e o iptables:

```bash
sudo apt update && sudo apt install -y python3 python3-pip iptables curl
```

## Passo 2 — Pegar as peças

Copie a pasta `weave-box/` pro notebook (via `scp`, `git`, pendrive, etc), e
junte os dois arquivos que não vêm aqui:

**a) o mitigador** — baixe o script atual pra dentro de `vendor/`:

```bash
cd weave-box
mkdir -p vendor
curl -L https://raw.githubusercontent.com/Soreepeong/XivMitmLatencyMitigator/main/mitigate.py \
  -o vendor/mitigate.py
```

**b) o `ffxiv_dx11.exe`** — o script precisa dele pro Oodle. Seu amigo é PS5-only
e não tem o jogo no PC, então baixe o **trial gratuito** do FFXIV em qualquer
Windows, e copie o `ffxiv_dx11.exe` (fica em `game/` da instalação) pra dentro de
`vendor/`, ao lado do `mitigate.py`.

**c) os opcodes** — gere o arquivo local de definições:

```bash
sudo sh scripts/update-opcodes.sh
```

Isso cria `vendor/opcodes.json`. A partir daí o mitigador lê desse arquivo e
**não acessa mais o GitHub enquanto joga**.

## Passo 3 — Instalar

```bash
sudo sh scripts/install.sh
```

Isso instala as dependências, sobe a rede base e registra dois serviços que
ligam no boot: a rede base e o painel web. No fim ele imprime o endereço do
painel.

## Passo 4 — Rede

1. **IP fixo pro notebook.** No seu roteador, faça uma reserva de DHCP pro MAC do
   notebook (ou configure IP estático no Linux). Anote esse IP, ex: `192.168.0.10`.
   Se o IP mudar, a config do PS5 quebra.
2. **Não deixar o notebook dormir.** Com a tampa fechada ele precisa continuar
   ligado:
   ```bash
   sudo sed -i 's/#HandleLidSwitch=.*/HandleLidSwitch=ignore/' /etc/systemd/logind.conf
   sudo systemctl restart systemd-logind
   ```

## Passo 5 — Apontar o PS5 pro notebook

No PS5: **Ajustes → Rede → Configurar Conexão com a Internet → (sua rede) →
Configuração Avançada / Manual**, e defina:

- **Endereço IP**: manual, um IP fixo livre na sua rede (ex: `192.168.0.50`)
- **Gateway padrão**: o **IP do notebook** (ex: `192.168.0.10`)
- **DNS primário**: o IP do roteador, ou `1.1.1.1`

Salve e teste a conexão. O PS5 agora roteia tudo pelo notebook.

## Passo 6 — Usar

Abra no navegador do celular:

```
http://192.168.0.10:8080
```

(trocando pelo IP do notebook). Toque em **Ligar mitigação**, entre em combate no
jogo, e veja o lock sendo cortado ao vivo. Pronto. Ele controla tudo dali, sem
mexer no notebook.

---

## Manutenção

- **A cada patch do jogo**, os opcodes mudam. Rode de novo:
  ```bash
  sudo sh scripts/update-opcodes.sh
  ```
  e desligue/ligue a mitigação no painel. Se o repo padrão estiver desatualizado,
  aponte pra um fork atual:
  ```bash
  SOURCE="https://api.github.com/repos/<fork>/XivAlexander/contents/StaticData/OpcodeDefinition" \
    sudo sh scripts/update-opcodes.sh
  ```
- **Quando o Oodle mudar** (mais raro), troque o `vendor/ffxiv_dx11.exe` por um do
  cliente atualizado.
- **Ver o que está rolando**: `journalctl -u weave-box -f`

---

## Coisas que você precisa saber (honestamente)

- **Isso é área cinza de ToS.** O próprio autor do mitigador avisa. Raramente é
  punido porque o ajuste fica do lado do cliente e mantém a margem de segurança,
  mas o risco não é zero.
- **Isso conserta o weave, não o ping real.** Os ~250ms continuam valendo pra
  movimento, mecânica e snapshot de dano. Pra esse outro eixo, um otimizador de
  rota (ExitLag/NoPing) seria um complemento, nunca um substituto.
- **O notebook vira ponto único de falha da internet do PS5.** Se ele desligar, o
  PS5 fica sem net até você voltar a config ou religar a caixa. A rede base sobe
  no boot justamente pra isso não acontecer toda hora.
- **Segurança**: o painel escuta só na sua LAN. **Nunca** faça port-forward da
  porta 8080 pra internet. Ele roda como root porque o mitigador precisa.

---

## Estrutura

```
weave-box/
├── app.py                  painel web (FastAPI) + endpoints
├── controller.py           gerencia o mitigate.py e faz parsing da telemetria
├── config.py               caminhos e ajustes (tudo sobrescrevível por env)
├── requirements.txt
├── static/index.html       a interface (self-contained, sem build)
├── scripts/
│   ├── install.sh          instalador (deps + systemd)
│   ├── netbase-up.sh       rede base persistente (MASQUERADE + ip_forward)
│   └── update-opcodes.sh   vendoriza os opcodes localmente
├── systemd/weave-box.service
└── vendor/                 você coloca: mitigate.py, ffxiv_dx11.exe, opcodes.json
```
