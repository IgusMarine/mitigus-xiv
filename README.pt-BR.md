# Mitigus XIV

[English](README.md) | **Português**

Mitigador de latência do **FINAL FANTASY XIV** 100% nativo no **Windows**, pensado para quem joga no **console (PS5/PS4)** — onde plugins e addons não existem.

Ele faz o que o [XivMitmLatencyMitigator](https://github.com/Soreepeong/XivMitmLatencyMitigator) / [XivAlexander](https://github.com/Soreepeong/XivAlexander) fazem (descontar o RTT da rede da `animation_lock_duration` pra você conseguir encaixar dois *weaves*), mas **sem Linux, sem VM e sem mexer no console**: o PC vira o gateway do console, intercepta o tráfego do FFXIV na rede e corrige o lock em tempo real.

```
  PS5/PS4  ──gateway──►  PC (Windows)  ──►  Roteador  ──►  Servidores do FFXIV
                              │
                              ├─ mascara (NAT) a internet geral do console
                              ├─ desvia SÓ as conexões do FFXIV p/ um proxy local
                              ├─ decodifica (Oodle) e corta o animation lock
                              └─ painel (janela própria + http://IP:8080 no celular)
```

## Como funciona
- O console aponta o **gateway** para o PC. O Windows encaminha o tráfego; o Mitigus faz NAT da internet geral e **desvia apenas as conexões do FFXIV** para um proxy local.
- O proxy termina o TCP, decodifica os pacotes (Oodle, lido do `ffxiv_dx11.exe`) e reescreve a `animation_lock_duration` subtraindo o RTT medido — com uma margem de segurança ajustável (estilo NoClippy/adaptativa).
- Um **painel** (janela sem a barra do Windows, via WebView2, + acessível no celular) mostra o corte ao vivo, ping (rede vs. jogo), jitter e o status do sistema.

## Requisitos
- **Windows 10/11** (x64). Roda como **Administrador** (carrega o driver WinDivert).
- **`ffxiv_dx11.exe`** — necessário pro Oodle. **NÃO vem no pacote (é copyright).** Pegue do **trial gratuito** do FFXIV em qualquer PC Windows e coloque na pasta do Mitigus (ou em `vendor\`). O app abre a pasta certa e avisa se faltar.
- Console e PC na **mesma rede** (de preferência o PC no cabo).
- O Windows precisa ser **reiniciado uma vez** depois de ativar o compartilhamento (o app pergunta).

## Como usar
1. Extraia a pasta **"Mitigus XIV (app)"** e coloque seu `ffxiv_dx11.exe` dentro dela.
2. Rode o **"Mitigus XIV (app).exe"** (aceite o aviso de Administrador / UAC).
3. No console: **Rede → Configurar Internet → Manual** e aponte o **Gateway** para o IP do PC (o painel mostra o IP). DNS primário `1.1.1.1`.
4. Abra o FFXIV. O painel mostra os cortes ao vivo. No celular (mesma rede): `http://IP_DO_PC:8080`.

## Build (a partir do código)
```bash
cd windows
pip install -r requirements.txt
python -m PyInstaller mitigus_xiv_native.spec   # gera dist/"Mitigus XIV (app)"/
python -m unittest discover -s tests            # testes
```
Documentação técnica e os outros modos (console/janela/bandeja) em [`windows/README.md`](windows/README.md).

## Manutenção
- **A cada patch do jogo** os opcodes mudam — o Mitigus tenta atualizar sozinho ao abrir (mesma fonte do XivAlexander); há um botão **Atualizar** no painel.
- Em patches grandes, troque também o `ffxiv_dx11.exe` por um do cliente atualizado.

## ⚠️ Aviso (leia antes de usar)
- Ferramenta **não-oficial**, **não afiliada nem endossada** pela Square Enix / FINAL FANTASY XIV. FINAL FANTASY é marca da Square Enix.
- **Área cinza dos Termos de Serviço.** O uso é **por sua conta e risco** e pode, em tese, resultar em punição na conta. O ajuste fica do lado do cliente e mantém uma margem de segurança, mas o risco **não é zero**.
- Isso conserta o **weave**, não o ping real — movimento, mecânica e snapshot de dano continuam sujeitos à latência da rede.
- Fornecido **sem qualquer garantia**.

## Créditos
- [XivMitmLatencyMitigator](https://github.com/Soreepeong/XivMitmLatencyMitigator) e [XivAlexander](https://github.com/Soreepeong/XivAlexander) (Soreepeong) — a técnica de mitigação e a fonte dos opcodes.
- [WinDivert](https://github.com/basil00/WinDivert) (basil00) — interceptação de pacotes em userland no Windows.
- Fonte [Chakra Petch](https://fonts.google.com/specimen/Chakra+Petch) (SIL OFL 1.1).
