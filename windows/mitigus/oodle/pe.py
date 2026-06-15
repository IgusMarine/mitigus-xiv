"""
Mapeador manual de PE (x64) — port do `mitigate.py`.

As funções de compressão Oodle ficam ESTATICAMENTE ligadas dentro do
`ffxiv_dx11.exe` e não são exportadas, então não dá para `LoadLibrary` e pegar por
nome. A solução (igual ao original): carregar a imagem do PE na memória à mão —
copiar headers e seções para memória executável, aplicar as base relocations — e
depois localizar as funções por assinatura de bytes (sigscan, em oodle.py).

Diferente do original (que roda no Linux), aqui é x64-only e Windows-nativo:
`allocate_executable_memory` usa VirtualAlloc com PAGE_EXECUTE_READWRITE.
"""
from __future__ import annotations

import ctypes
import typing

POINTER_SIZE = ctypes.sizeof(ctypes.c_void_p)

IMAGE_NUMBEROF_DIRECTORY_ENTRIES = 16
IMAGE_DIRECTORY_ENTRY_BASERELOC = 5
IMAGE_SIZEOF_SHORT_NAME = 8


class ImageDosHeader(ctypes.LittleEndianStructure):
    _fields_ = (
        ("e_magic", ctypes.c_uint16),
        ("e_cblp", ctypes.c_uint16),
        ("e_cp", ctypes.c_uint16),
        ("e_crlc", ctypes.c_uint16),
        ("e_cparhdr", ctypes.c_uint16),
        ("e_minalloc", ctypes.c_uint16),
        ("e_maxalloc", ctypes.c_uint16),
        ("e_ss", ctypes.c_uint16),
        ("e_sp", ctypes.c_uint16),
        ("e_csum", ctypes.c_uint16),
        ("e_ip", ctypes.c_uint16),
        ("e_cs", ctypes.c_uint16),
        ("e_lfarlc", ctypes.c_uint16),
        ("e_ovno", ctypes.c_uint16),
        ("e_res", ctypes.c_uint16 * 4),
        ("e_oemid", ctypes.c_uint16),
        ("e_oeminfo", ctypes.c_uint16),
        ("e_res2", ctypes.c_uint16 * 10),
        ("e_lfanew", ctypes.c_uint32),
    )


class ImageFileHeader(ctypes.LittleEndianStructure):
    _fields_ = (
        ("Machine", ctypes.c_uint16),
        ("NumberOfSections", ctypes.c_uint16),
        ("TimeDateStamp", ctypes.c_uint32),
        ("PointerToSymbolTable", ctypes.c_uint32),
        ("NumberOfSymbols", ctypes.c_uint32),
        ("SizeOfOptionalHeader", ctypes.c_uint16),
        ("Characteristics", ctypes.c_uint16),
    )


class ImageDataDirectory(ctypes.LittleEndianStructure):
    _fields_ = (
        ("VirtualAddress", ctypes.c_uint32),
        ("Size", ctypes.c_uint32),
    )


class ImageOptionalHeader64(ctypes.LittleEndianStructure):
    _fields_ = (
        ("Magic", ctypes.c_uint16),
        ("MajorLinkerVersion", ctypes.c_uint8),
        ("MinorLinkerVersion", ctypes.c_uint8),
        ("SizeOfCode", ctypes.c_uint32),
        ("SizeOfInitializedData", ctypes.c_uint32),
        ("SizeOfUninitializedData", ctypes.c_uint32),
        ("AddressOfEntryPoint", ctypes.c_uint32),
        ("BaseOfCode", ctypes.c_uint32),
        ("ImageBase", ctypes.c_uint64),
        ("SectionAlignment", ctypes.c_uint32),
        ("FileAlignment", ctypes.c_uint32),
        ("MajorOperatingSystemVersion", ctypes.c_uint16),
        ("MinorOperatingSystemVersion", ctypes.c_uint16),
        ("MajorImageVersion", ctypes.c_uint16),
        ("MinorImageVersion", ctypes.c_uint16),
        ("MajorSubsystemVersion", ctypes.c_uint16),
        ("MinorSubsystemVersion", ctypes.c_uint16),
        ("Win32VersionValue", ctypes.c_uint32),
        ("SizeOfImage", ctypes.c_uint32),
        ("SizeOfHeaders", ctypes.c_uint32),
        ("CheckSum", ctypes.c_uint32),
        ("Subsystem", ctypes.c_uint16),
        ("DllCharacteristics", ctypes.c_uint16),
        ("SizeOfStackReserve", ctypes.c_uint64),
        ("SizeOfStackCommit", ctypes.c_uint64),
        ("SizeOfHeapReserve", ctypes.c_uint64),
        ("SizeOfHeapCommit", ctypes.c_uint64),
        ("LoaderFlags", ctypes.c_uint32),
        ("NumberOfRvaAndSizes", ctypes.c_uint32),
        ("DataDirectory", ImageDataDirectory * IMAGE_NUMBEROF_DIRECTORY_ENTRIES),
    )


class ImageNtHeaders64(ctypes.LittleEndianStructure):
    _fields_ = (
        ("Signature", ctypes.c_uint32),
        ("FileHeader", ImageFileHeader),
        ("OptionalHeader", ImageOptionalHeader64),
    )


class ImageSectionHeader(ctypes.LittleEndianStructure):
    _fields_ = (
        ("Name", ctypes.c_char * IMAGE_SIZEOF_SHORT_NAME),
        ("VirtualSize", ctypes.c_uint32),
        ("VirtualAddress", ctypes.c_uint32),
        ("SizeOfRawData", ctypes.c_uint32),
        ("PointerToRawData", ctypes.c_uint32),
        ("PointerToRelocations", ctypes.c_uint32),
        ("PointerToLinenumbers", ctypes.c_uint32),
        ("NumberOfRelocations", ctypes.c_uint16),
        ("NumberOfLinenumbers", ctypes.c_uint16),
        ("Characteristics", ctypes.c_uint32),
    )


class ImageBaseRelocation(ctypes.LittleEndianStructure):
    _fields_ = (
        ("VirtualAddress", ctypes.c_uint32),
        ("SizeOfBlock", ctypes.c_uint32),
    )


def allocate_executable_memory(length: int) -> ctypes.c_void_p:
    va = ctypes.windll.kernel32.VirtualAlloc
    va.argtypes = (ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32, ctypes.c_uint32)
    va.restype = ctypes.c_void_p
    return ctypes.c_void_p(va(0, length, 0x3000, 0x40))  # MEM_RESERVE|MEM_COMMIT, PAGE_EXECUTE_READWRITE


def free_executable_memory(ptr: ctypes.c_void_p) -> None:
    ctypes.windll.kernel32.VirtualFree(ptr, 0, 0x8000)  # MEM_RELEASE


PyMemoryView_FromMemory = ctypes.pythonapi.PyMemoryView_FromMemory
PyMemoryView_FromMemory.argtypes = (ctypes.c_void_p, ctypes.c_ssize_t, ctypes.c_int)
PyMemoryView_FromMemory.restype = ctypes.py_object


class PeImage:
    def __init__(self, data: typing.Union[bytearray, bytes]):
        if POINTER_SIZE != 8:
            raise RuntimeError("Mitigus XIV requer Python 64-bit (x64).")
        self._data = data if isinstance(data, bytearray) else bytearray(data)

        self.dos = ImageDosHeader.from_buffer(self._data, 0)
        if self.dos.e_magic != 0x5A4D:
            raise ValueError("bad dos header")
        self.nt = ImageNtHeaders64.from_buffer(self._data, self.dos.e_lfanew)
        if self.nt.Signature != 0x4550:
            raise ValueError("bad nt header")
        if self.nt.OptionalHeader.Magic != 0x20B:
            raise ValueError("não é PE32+ (x64)")

        self.sections = (ImageSectionHeader * self.nt.FileHeader.NumberOfSections).from_buffer(
            self._data, self.dos.e_lfanew + ctypes.sizeof(self.nt)
        )

        self.address = allocate_executable_memory(self.nt.OptionalHeader.SizeOfImage)
        if not self.address or not self.address.value:
            raise MemoryError("VirtualAlloc falhou")
        self.view: memoryview = PyMemoryView_FromMemory(
            self.address, self.nt.OptionalHeader.SizeOfImage, 0x200  # PyBUF_WRITE
        )

        self._map_headers_and_sections()
        self._relocate()

    def _map_headers_and_sections(self) -> None:
        ctypes.memmove(
            self.address,
            ctypes.addressof(ctypes.c_byte.from_buffer(self._data)),
            self.nt.OptionalHeader.SizeOfHeaders,
        )
        for shdr in self.sections:
            ctypes.memmove(
                ctypes.addressof(ctypes.c_byte.from_buffer(self.view, shdr.VirtualAddress)),
                ctypes.addressof(ctypes.c_byte.from_buffer(self._data, shdr.PointerToRawData)),
                min(shdr.SizeOfRawData, shdr.VirtualSize),
            )

    def _relocate(self) -> None:
        directory = self.nt.OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_BASERELOC]
        rva = int(directory.VirtualAddress)
        rva_to = rva + int(directory.Size)
        displacement = self.address.value - self.nt.OptionalHeader.ImageBase
        if displacement == 0 or rva == 0:
            return
        while rva < rva_to:
            page = ctypes.cast(
                ctypes.c_void_p(self.address.value + rva), ctypes.POINTER(ImageBaseRelocation)
            ).contents
            count = (page.SizeOfBlock - ctypes.sizeof(page)) // 2
            page_data = ctypes.cast(
                ctypes.c_void_p(self.address.value + rva + ctypes.sizeof(page)),
                ctypes.POINTER(ctypes.c_uint16 * count),
            ).contents
            for relo in page_data:
                absptr = self.address.value + page.VirtualAddress + (relo & 0xFFF)
                kind = relo >> 12
                if kind == 0:  # ABSOLUTE
                    pass
                elif kind == 3:  # HIGHLOW (32-bit)
                    ptr = ctypes.cast(absptr, ctypes.POINTER(ctypes.c_uint32))
                    ctypes.memmove(
                        absptr, ctypes.addressof(ctypes.c_uint32(ptr.contents.value + displacement)), 4
                    )
                elif kind == 10:  # DIR64 (64-bit)
                    ptr = ctypes.cast(absptr, ctypes.POINTER(ctypes.c_uint64))
                    ctypes.memmove(
                        absptr, ctypes.addressof(ctypes.c_uint64(ptr.contents.value + displacement)), 8
                    )
                else:
                    raise RuntimeError(f"relocation não suportada: {kind}")
            rva += page.SizeOfBlock

    def section_header(self, name: bytes) -> ImageSectionHeader:
        for s in self.sections:
            if s.Name == name:
                return s
        raise KeyError(name)

    def section(self, section: typing.Union[bytes, ImageSectionHeader]) -> memoryview:
        if not isinstance(section, ImageSectionHeader):
            section = self.section_header(section)
        return self.view[section.VirtualAddress : section.VirtualAddress + section.VirtualSize]

    def resolve_rip_relative(self, addr: int) -> int:
        """Resolve o alvo de um CALL/JMP rel32 (E8/E9) na posição `addr` (RVA)."""
        if self.view[addr] in (0xE8, 0xE9):
            return addr + 5 + int.from_bytes(self.view[addr + 1 : addr + 5], "little", signed=True)
        raise NotImplementedError("esperava E8/E9 em rip-relative")
