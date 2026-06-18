# Spike: FFXIV packet deobfuscation (personal/private use)

**English** | [Português](README.pt-BR.md)

An **isolated** proof of concept (not production Mitigus code) that deobfuscates FFXIV combat packets **solely from network traffic** — without game injection or process memory reading. This enables reading combat data from a **console (PS5/PS4)** client with a PC in the middle of the network path — the same topology used by Mitigus.

## Why this is possible (what I got wrong before)

The deobfuscation key does **not** depend on the client's internal state (`localRand`). perchbirdd discovered an equivalent path derived from the network:

1. The server sends 3 **seeds** in an initialization packet (over the network).
   - ≤7.3: inside `InitZone` (offsets 37/38/39/40).
   - 7.4+: in a dedicated initialization packet (offsets 22/23/24/28). Patch 7.4 only **moved** the seeds — it did not close the passive vector.
2. **Static tables** (`table0/1/2`, `midtable`, `daytable`, `opcodekeytable`) are extracted *offline* from `ffxiv_dx11.exe` per patch. perchbirdd publishes the `.bin` files (coverage up to 2026.06.10 / patch 7.5x).
3. The 3 keys are derived using **pure arithmetic** over the seeds + tables (`Derive`). In 7.3+, there is also an **opcode-specific key** (`opcodekeytable`).
4. The **descramble** process subtracts/XORs these keys in the correct fields of each packet (`ActionEffect` = damage, `PlayerSpawn` = identity/job, etc.).

## What's in here

| File | Role | Port origin |
|---|---|---|
| `constants.py` | table offsets, modes, opcodes by version | `Constants/Versions/*.cs` |
| `keygen.py` | derivation of the 3 keys + key-per-opcode | `Derivation/KeyGenerator{72,73,74}.cs` |
| `unscramble.py` | descrambling fields (and scramble for testing) | `Unscramble/Unscrambler{72,73}.cs` |
| `loader.py` | loads `.bin` files + Deobfuscator facade | `*Factory.cs` |
| `data/<version>/*.bin` | vendorized static tables | perchbirdd repository |
| `test_deob.py` | round-trip + determinism | — |

Credits: **perchbirdd/Unscrambler** (WTFPL license) and **NotNite/TemporalStasis**. The `.bin` files were copied from perchbirdd's repository; no game files (`ffxiv_dx11.exe`) are present here — we use the pre-extracted tables.

## Validation Status (Honest)

`python test_deob.py` → **11/11 OK**.

What the tests **PROVE**:
- The descramble structure is correct and self-consistent: offsets, widths (u16/u32/u64/byte), dispatch by opcode, and the inverse operations (sub ↔ add, self-inverse XOR). `scramble → unscramble` recovers the original byte-for-byte on all 19 obfuscated opcodes.
- Derivation routing: mode detection, seed offsets, bit negation; deterministic and seed-sensitive. `unscramble_copy` does not modify the original buffer.

What the tests **DO NOT PROVE** (the honest frontier):
- That the key **values** match those in the **game** byte-for-byte. The round-trip uses the derived keys consistently in both directions, so any error in the `Derive` arithmetic or the key-per-opcode index **would cancel out** during the round-trip. This can only be verified with:
  - (a) a **real PS5 capture** (1 session: capture the initializer + some ActionEffects and see if the resulting damage is coherent), or
  - (b) building the **reference C# implementation** and comparing `Derive` outputs across a grid of seeds (requires the .NET SDK — not installed here).

For now, the correctness of the values relies on a line-by-line port of simple integer arithmetic (with equivalent overflow/sign masks matching C#) — but **the final proof is a real capture**.

## Adding a New Patch

1. Copy the 6 `.bin` files from `Unscrambler/Data/<version>/` to `data/<version>/`.
2. Transcribe the corresponding `Constants<version>.cs` into `constants.py` (radixes, max, mode, opcodes) and update `LATEST`.
3. Run the tests.

## Integration into Mitigus (when/if applicable)

- Mitigus is already a TCP relay + decodes Oodle + parses IPC bundles/segments.
- For a **read-only** parser: on each IPC segment, call `Deobfuscator.unscramble_copy(ipc_buf)` on a **copy** and read combat data; **forward the original intact buffer** to the console (the console performs its own deobfuscation — forwarded scrambled bytes would crash the client).
- Once per session: capture the initialization packet (opcode `unknown_obfuscation_init_opcode`) and call `feed_initializer`.

## Capture → Replay Pipeline (already complete on the `dps-meter` branch)

1. **Capture** (on the PC, with the console routing through it): `python windows/run_capture.py` — runs the production proxy (relay + Oodle + weave) and writes **pristine post-Oodle** IPC segments to a `.jsonl` file. Hooked via optional `capture` in the Mitigator (default-off; production intact) + `mitigus/capture/recorder.py`. Start capturing BEFORE changing zones (Oodle/obfuscation trigger upon zone entry).
2. **Validate** (offline): `python research/deob/replay_capture.py <capture.jsonl>` — detects the initializer, derives network keys, deobfuscates ActionEffects, and verifies if `action_id`/damage values are plausible. `test_replay.py` validates the entire pipeline (capture → key → descramble → parse) using synthetic data: it recovers exact `action_id` and damage values.

## Next Steps

1. **Run a real PS5 capture** and pass it through `replay_capture.py` — this is the final validation needed to guarantee byte-accuracy. If the game version ≠ 2026.06.10, copy the correct `.bin` files and transcribe version constants.
2. Once validated: build a complete combat parser (damage → crit/direct hit → DPS by job; job via `PlayerSpawn`) + "Neon Bars" UI.
3. Harden: boundary checks on writes (the upstream uses raw pointers without checks) and auto-detect game versions.
