# Apontar o PS5 para o PC (topologia NIC única)

Objetivo: fazer o tráfego do PS5 passar pelo PC Windows, para que o engine possa
enxergá-lo (Fase 0) e, depois, interceptá-lo (Fase 1+).

## 1. Descubra o IP do PC

Rode, como Administrador, `setup\enable-routing.ps1`. No fim ele imprime o IP da
LAN do PC (ex.: `192.168.0.10`). Esse é o **gateway** que o PS5 vai usar.

> Dê ao PC um IP fixo (reserva de DHCP pelo MAC no roteador, ou IP estático).
> Se o IP do PC mudar, a config do PS5 quebra.

## 2. Configure o PS5 manualmente

No PS5: **Ajustes → Rede → Configurar Conexão com a Internet → (sua rede) →
Configuração Avançada / Manual** (use **cabo**, não Wi-Fi):

| Campo            | Valor                                             |
|------------------|---------------------------------------------------|
| Endereço IP      | Manual — um IP livre na sua rede (ex. `192.168.0.50`) |
| Máscara          | a da sua rede (normalmente `255.255.255.0`)       |
| Gateway padrão   | **o IP do PC** (ex. `192.168.0.10`)               |
| DNS primário     | o IP do roteador, ou `1.1.1.1`                     |

Salve e teste a conexão. O PS5 passa a rotear pelo PC.

## 3. Rode o sniffer (no PC, como Admin)

```
python run_sniff.py --host 192.168.0.50
```

(troque pelo IP do PS5). Entre numa zona / combate no jogo. Você deve ver o
bloco **"FF14ARR detectado"** e os contadores subindo.

## Reverter

Quando terminar, no PS5 volte o **Gateway padrão** para o IP do roteador, e no
PC rode `setup\disable-routing.ps1`.

## Observação (NIC única)

Nesta topologia o caminho de **volta** (servidor → PS5) tende a chegar do roteador
direto ao PS5, pulando o PC — então a Fase 0 enxerga bem o tráfego de **saída**, o
suficiente para validar a captura. A interceptação confiável dos dois sentidos
(necessária para modificar o `ActionEffect`) vem na **Fase 1**, com o proxy
transparente que termina o TCP no PC. Se quiser robustez máxima desde já, uma 2ª
placa de rede (USB-Ethernet) dedicada ao PS5 elimina essa assimetria.
