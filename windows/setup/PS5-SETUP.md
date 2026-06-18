# Pointing the PS5 to the PC (Single NIC Topology)

**English** | [Português](PS5-SETUP.pt-BR.md)

Goal: Route PS5 network traffic through the Windows PC so the engine can detect it (Phase 0) and intercept it (Phase 1+).

## 1. Find the PC's IP address

Run `setup\enable-routing.ps1` as Administrator. At the end, it will print the PC's LAN IP address (e.g., `192.168.0.10`). This is the **gateway** the PS5 will use.

> Assign a static IP or set up a DHCP reservation for the PC on your router. If the PC's IP address changes, the PS5 configuration will break.

## 2. Manually Configure the PS5

On the PS5: **Settings → Network → Set Up Internet Connection → (your network) → Advanced Settings / Manual** (use a **wired cable connection**, not Wi-Fi):

| Field            | Value                                             |
|------------------|---------------------------------------------------|
| IP Address       | Manual — a free IP on your network (e.g., `192.168.0.50`) |
| Subnet Mask      | your network mask (usually `255.255.255.0`)       |
| Default Gateway  | **the PC's IP address** (e.g., `192.168.0.10`)   |
| Primary DNS      | your router's IP, or `1.1.1.1`                    |

Save and test the connection. The PS5 will now route its traffic through the PC.

## 3. Run the Sniffer (on the PC, as Admin)

```
python run_sniff.py --host 192.168.0.50
```

(replace with the PS5's IP). Enter a zone or start combat in-game. You should see the **"FF14ARR detected"** block and the counters rising.

## Reverting

When finished, change the PS5's **Default Gateway** back to your router's IP, and run `setup\disable-routing.ps1` on the PC.

## Note (Single NIC)

In this single-NIC topology, the return path (server → PS5) tends to route directly from the router to the PS5, bypassing the PC. As a result, Phase 0 only intercepts **outbound** traffic, which is sufficient to validate packet capture. Reliable bi-directional interception (required to modify `ActionEffect`) is achieved in **Phase 1** via the transparent proxy terminating the TCP connection on the PC. For maximum robustness, adding a second network adapter (USB-Ethernet) dedicated to the PS5 eliminates this routing asymmetry.
