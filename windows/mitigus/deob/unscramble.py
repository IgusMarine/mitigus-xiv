"""
Descramble dos campos ofuscados (port de Unscrambler/Unscramble/Unscrambler73).

Aplica as 3 chaves + a chave-por-opcode nos campos certos de cada pacote
(ActionEffect = dano, PlayerSpawn = identidade/job, etc.). Cobre 7.3 -> 7.5.

O buffer passado comeca no HEADER IPC (opcode em offset 2). Os offsets dos
campos abaixo sao relativos a esse inicio (igual ao upstream).

IMPORTANTE p/ integracao no relay (Mitigus): para um leitor read-only,
desofusque uma COPIA do buffer. NAO repasse os bytes desofuscados pro
console -- ele espera os bytes ofuscados e faz a propria desofuscacao.

`unscramble()` e a operacao real (subtrai). `scramble()` e o inverso exato
(soma), usado so para testes/fixtures de round-trip -- mesmo mapa de campos,
sinal trocado. Campos XOR sao auto-inversos (iguais nos dois sentidos).
"""

from __future__ import annotations

_MASK = {1: 0xFF, 2: 0xFFFF, 4: 0xFFFFFFFF, 8: 0xFFFFFFFFFFFFFFFF}


def _read(buf, off, width):
    return int.from_bytes(buf[off:off + width], "little")


def _write(buf, off, width, val):
    buf[off:off + width] = (val & _MASK[width]).to_bytes(width, "little")


def _addsub(buf, off, width, key, sign):
    """sign=-1 -> '-= key' (unscramble); sign=+1 -> '+= key' (scramble)."""
    _write(buf, off, width, _read(buf, off, width) + sign * key)


def _xor(buf, off, width, key):
    _write(buf, off, width, _read(buf, off, width) ^ (key & _MASK[width]))


def opcode_at_ipc_start(buf) -> int:
    """opcode = uint16 LE em offset 2 (OpcodeUtility.GetOpcodeFromPacketAtIpcStart)."""
    return _read(buf, 2, 2)


class Unscrambler:
    def __init__(self, constants):
        self.constants = constants

    # --- API publica -----------------------------------------------------
    def unscramble(self, buf: bytearray, key0, key1, key2, opcode_key_table) -> int:
        """Desofusca o pacote in-place. Retorna o opcode tocado (ou -1)."""
        return self._run(buf, key0, key1, key2, opcode_key_table, sign=-1)

    def scramble(self, buf: bytearray, key0, key1, key2, opcode_key_table) -> int:
        """Inverso exato de unscramble (apenas testes/fixtures)."""
        return self._run(buf, key0, key1, key2, opcode_key_table, sign=+1)

    # --- nucleo ----------------------------------------------------------
    def _run(self, buf, key0, key1, key2, opcode_key_table, sign) -> int:
        if key0 == 0 and key1 == 0 and key2 == 0:
            return -1
        if opcode_key_table is not None and len(opcode_key_table) == 0:
            return -1

        keys = (key0, key1, key2)
        opcode = opcode_at_ipc_start(buf)
        base_key = keys[opcode % 3] & 0xFF
        idx = (opcode + base_key) % len(opcode_key_table)
        opcode_based_key = opcode_key_table[idx]

        self._apply(buf, opcode, base_key, opcode_based_key, sign)
        return opcode

    def _apply(self, data, opcode, base_key, opcode_based_key, sign):
        op = self.constants.obfuscated_opcodes

        if opcode == op["PlayerSpawn"]:
            _addsub(data, 24, 8, base_key, sign)   # Content ID
            _addsub(data, 36, 2, base_key, sign)   # Current world
            _addsub(data, 38, 2, base_key, sign)   # Home world
            for i in range(32):                    # Name
                _addsub(data, 610 + i, 1, base_key, sign)
            int_key = (base_key + opcode_based_key) & 0xFFFFFFFF  # Equipment
            for i in range(10):
                _xor(data, 556 + i * 4, 4, int_key)

        elif opcode in (op["NpcSpawn"], op["NpcSpawn2"]):
            self._npc_spawn(data, base_key, opcode_based_key & 0xFFFFFFFF, sign)

        elif opcode == op["ActionEffect01"]:
            self._action_effect(data, 1, base_key, opcode_based_key, sign)
        elif opcode == op["ActionEffect08"]:
            self._action_effect(data, 8, base_key, opcode_based_key, sign)
        elif opcode == op["ActionEffect16"]:
            self._action_effect(data, 16, base_key, opcode_based_key, sign)
        elif opcode == op["ActionEffect24"]:
            self._action_effect(data, 24, base_key, opcode_based_key, sign)
        elif opcode == op["ActionEffect32"]:
            self._action_effect(data, 32, base_key, opcode_based_key, sign)
        elif opcode == op["ActionEffect02"]:
            self._action_effect(data, 2, base_key, opcode_based_key, sign)
        elif opcode == op["ActionEffect04"]:
            self._action_effect(data, 4, base_key, opcode_based_key, sign)

        elif opcode == op["StatusEffectList"]:
            self._status_effect_list(data, base_key, 36, sign)
        elif opcode == op["StatusEffectList3"]:
            self._status_effect_list(data, base_key, 16, sign)

        elif opcode == op["Examine"]:
            _addsub(data, 18, 1, base_key, sign)
            _addsub(data, 19, 1, base_key, sign)
            _addsub(data, 66, 2, base_key, sign)
            _addsub(data, 72, 8, base_key, sign)
            for i in range(32):
                _addsub(data, 656 + i, 1, base_key, sign)
            for i in range(32):
                _addsub(data, 688 + i, 1, base_key, sign)

        elif opcode == op["UpdateGearset"]:
            int_key = (base_key + opcode_based_key) & 0xFFFFFFFF
            for i in range(10):
                _xor(data, 36 + i * 4, 4, int_key)

        elif opcode == op["UpdateParty"]:
            for i in range(8):
                off = 456 * i
                _addsub(data, 64 + off, 8, base_key, sign)
                _addsub(data, 72 + off, 4, base_key, sign)
                _addsub(data, 76 + off, 4, base_key, sign)
                _addsub(data, 80 + off, 4, base_key, sign)
                _addsub(data, 96 + off, 2, base_key, sign)
                _addsub(data, 101 + off, 1, base_key, sign)
                _addsub(data, 103 + off, 1, base_key, sign)
                _addsub(data, 105 + off, 1, base_key, sign)

        elif opcode == op["ActorControl"]:
            if _read(data, 16, 2) == 34:           # TargetIcon
                _addsub(data, 20, 4, base_key, sign)

        elif opcode == op["ActorCast"]:
            _addsub(data, 20, 4, base_key, sign)

        elif opcode == op["UnknownEffect01"]:
            _addsub(data, 28, 4, base_key, sign)
            short_key = (base_key + opcode_based_key) & 0xFFFF
            for i in range(8 * 1):
                _xor(data, 66 + i * 8, 2, short_key)

        elif opcode == op["UnknownEffect16"]:
            _addsub(data, 28, 4, base_key, sign)
            short_key = (base_key + opcode_based_key) & 0xFFFF
            for i in range(8 * 16):
                _xor(data, 58 + i * 8, 2, short_key)

    # --- handlers reutilizados ------------------------------------------
    def _action_effect(self, data, target_count, base_key, base_key_mod, sign):
        _addsub(data, 24, 4, base_key, sign)       # Action ID
        short_key = (base_key + base_key_mod) & 0xFFFF
        for i in range(8 * target_count):          # valores de dano/cura
            _xor(data, 64 + i * 8, 2, short_key)

    def _status_effect_list(self, data, base_key, op_offset, sign):
        for i in range(30):
            _addsub(data, op_offset + i * 12, 2, base_key, sign)

    def _npc_spawn(self, data, base_key, weird_const, sign):
        _addsub(data, 80, 4, base_key, sign)       # BNPC Base
        _addsub(data, 84, 4, base_key, sign)       # BNPC Name
        _addsub(data, 88, 4, base_key, sign)
        _addsub(data, 96, 4, base_key, sign)       # Companion Owner
        _addsub(data, 100, 4, base_key, sign)      # Event
        _xor(data, 108, 4, weird_const)            # Tether
        for i in range(30):                        # status effects
            _addsub(data, 168 + i * 12, 2, base_key, sign)
