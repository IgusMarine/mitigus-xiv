# Spike: desofuscação de pacotes do FFXIV (uso pessoal/privado)

[English](README.md) | **Português**

Prova de conceito **isolada** (não é código de produção do Mitigus) que desofusca pacotes de combate do FFXIV a partir **só do tráfego de rede** — sem injetar no jogo e sem ler a memória do processo. Isso é o que viabiliza ler combate de um cliente de **console (PS5/PS4)** com um PC no meio do tráfego — a mesma topologia do Mitigus.

## Por que isso é possível (o que eu tinha errado antes)

A chave de desofuscação **não** depende de estado interno do cliente (`localRand`). O perchbirdd descobriu um caminho equivalente derivado da rede:

1. O servidor manda 3 **seeds** num pacote inicializador (na rede).
   - ≤7.3: dentro do `InitZone` (offsets 37/38/39/40).
   - 7.4+: num pacote inicializador dedicado (offsets 22/23/24/28). O 7.4 só **moveu** os seeds — não fechou o vetor passivo.
2. **Tabelas estáticas** (`table0/1/2`, `midtable`, `daytable`, `opcodekeytable`) são extraídas *offline* do `ffxiv_dx11.exe` por patch. O perchbirdd publica os `.bin` (cobertura até 2026.06.10 / patch 7.5x).
3. As 3 chaves saem de **aritmética pura** sobre seeds + tabelas (`Derive`). Em 7.3+ há ainda uma **chave por opcode** (`opcodekeytable`).
4. O **descramble** subtrai/XOR essas chaves nos campos certos de cada pacote (ActionEffect = dano, PlayerSpawn = identidade/job, etc.).

## O que tem aqui

| Arquivo | Papel | Origem do port |
|---|---|---|
| `constants.py` | offsets de tabela, modos, opcodes por versão | `Constants/Versions/*.cs` |
| `keygen.py` | derivação das 3 chaves + chave-por-opcode | `Derivation/KeyGenerator{72,73,74}.cs` |
| `unscramble.py` | descramble dos campos (e `scramble`, p/ testes) | `Unscramble/Unscrambler{72,73}.cs` |
| `loader.py` | carrega os `.bin` + fachada `Deobfuscator` | `*Factory.cs` |
| `data/<versão>/*.bin` | tabelas estáticas vendorizadas | repo perchbirdd |
| `test_deob.py` | round-trip + determinismo | — |

Crédito: **perchbirdd/Unscrambler** (licença WTFPL) e **NotNite/TemporalStasis**. Os `.bin` foram copiados do repo do perchbirdd; nenhum arquivo do jogo (`ffxiv_dx11.exe`) está aqui — usamos as tabelas já extraídas.

## Status de validação (honesto)

`python test_deob.py` → **11/11 OK**.

O que os testes **PROVAM**:
- A estrutura do descramble está certa e auto-consistente: offsets, larguras (u16/u32/u64/byte), dispatch por opcode e a operação inversa (sub↔add, XOR auto-inverso). `scramble → unscramble` recupera o original byte-a-byte nos 19 opcodes ofuscados.
- A fiação da derivação: porta do modo, offsets dos seeds, negação de bits; determinístico e sensível aos seeds. `unscramble_copy` não toca no original.

O que os testes **NÃO PROVAM** (a fronteira honesta):
- Que os **valores** das chaves batem byte-a-byte com os do **jogo**. O round-trip usa as chaves derivadas de forma consistente nos dois sentidos, então um eventual erro na aritmética do `Derive` ou no índice da chave-por-opcode **se cancelaria** no round-trip. Isso só se confirma com:
  - (a) uma **captura real do PS5** (1 sessão: pegar o inicializador + alguns ActionEffect e ver se o dano sai coerente), ou
  - (b) build do **C# de referência** e comparar `Derive` numa grade de seeds (precisa do .NET SDK — não instalado aqui).

A correção dos valores se apoia, por ora, em: port linha-a-linha de aritmética inteira simples (com as máscaras de overflow/sinal equivalentes ao C#) — mas **a prova final é a captura real**.

## Adicionar um patch novo

1. Copie os 6 `.bin` de `Unscrambler/Data/<versão>/` para `data/<versão>/`.
2. Transcreva o `Constants<versão>.cs` correspondente em `constants.py` (radixes, max, modo, opcodes) e ajuste `LATEST`.
3. Rode os testes.

## Integração no Mitigus (quando/se for o caso)

- O Mitigus já é relay TCP + decodifica Oodle + parseia bundles/segmentos IPC.
- Para um leitor **read-only**: em cada segmento IPC, chame `Deobfuscator.unscramble_copy(ipc_buf)` numa **cópia** e leia o combate; **repasse o buffer original intacto** pro console (ele faz a própria desofuscação — bytes desembaralhados quebrariam o cliente).
- 1× por sessão: capture o pacote inicializador (opcode `unknown_obfuscation_init_opcode`) e chame `feed_initializer`.

## Pipeline de captura → replay (já pronto, branch `dps-meter`)

1. **Capturar** (no PC, com o console relayado): `python windows/run_capture.py` — roda o proxy de produção (relay + Oodle + weave) e grava os segmentos IPC **pristine pós-Oodle** num `.jsonl`. Costura `capture` opcional no Mitigator (default-off; produção intacta) + `mitigus/capture/recorder.py`. Comece a captura ANTES de trocar de zona (Oodle/ofuscação ligam na entrada da zona).
2. **Validar** (offline): `python research/deob/replay_capture.py <captura.jsonl>` — acha o inicializador, deriva as chaves da rede, desofusca os ActionEffect e diz se `action_id`/dano saíram plausíveis. `test_replay.py` prova a cadeia inteira (captura → chave → descramble → parse) com dados sintéticos: recupera `action_id` e os valores de dano exatos.

## Próximos passos

1. **Rodar uma captura real do PS5** e passar pelo `replay_capture.py` — é o único teste que falta pra cravar a validação byte-exata. Se a versão do jogo ≠ 2026.06.10, copiar os `.bin` da versão certa e transcrever os constants.
2. Depois de validado: parser de combate completo (dano→crit/direct hit→DPS por job; job via PlayerSpawn) + UI "Neon Bars".
3. Endurecer: limites de bounds nos writes (o upstream usa ponteiro cru, sem checagem) e detectar a versão do jogo automaticamente.
