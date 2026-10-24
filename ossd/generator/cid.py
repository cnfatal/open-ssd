"""CID (LightSwitch) 4 KiB block: identity fields, vendor CSV map, full build.

The full build reproduces the wrapper's write order: subareas first, then
+0xE00, then the wrapper's direct writes. A field appears in several places;
the last write wins.
"""

from __future__ import annotations

from dataclasses import dataclass

CID_BYTES = 4096

SYS_CLOCKS = (575, 550, 525, 500, 475, 450, 400, 350, 325, 250, 100, 50, 25)
LDPC_FLASH_CLOCKS = (400, 325, 266, 200, 166, 133, 100, 83, 66, 40, 33)
NPSS_TABLE = (0, 1, 2, 3, 4, 4)


class CidError(ValueError):
    pass


def _hex_nibble(c: str) -> int:
    if "0" <= c <= "9":
        return ord(c) - ord("0")
    if "a" <= c <= "f":
        return ord(c) - ord("a") + 10
    if "A" <= c <= "F":
        return ord(c) - ord("A") + 10
    return 0


def _parse_reverse(text: str | None, cid: bytearray, dst: int, pairs: int) -> None:
    temp = 0
    for i in range(pairs):
        a = text[2 * i] if text and 2 * i < len(text) else "\0"
        b = text[2 * i + 1] if text and 2 * i + 1 < len(text) else "\0"
        if a != "\0" and b != "\0":
            temp = (_hex_nibble(a) << 4) | _hex_nibble(b)
        cid[dst + pairs - 1 - i] = temp


def _set_bit(cid: bytearray | memoryview, offset: int, bit: int, value: int) -> None:
    if value:
        cid[offset] |= bit
    else:
        cid[offset] &= ~bit & 0xFF


def _put16(buf: bytearray, offset: int, value: int) -> None:
    buf[offset] = value & 0xFF
    buf[offset + 1] = (value >> 8) & 0xFF


def _clock(table, index: int) -> int:
    if index >= len(table):
        raise CidError(f"clock index {index} out of range")
    return table[index]


@dataclass
class CidConfig:
    """Field-for-field port of the wrapper's configuration struct.

    Defaults are zero, exactly like a configuration that sets nothing.
    """

    pci_vendor_id: str | None = None
    pci_device_id: str | None = None
    subsys_vendor_id: str | None = None
    subsys_id: str | None = None
    pcie_speed_index: int = 0
    pcie_lane_index: int = 0
    aspm_support: int = 0
    clock_pm: int = 0
    aspm_l1_2: int = 0
    aspm_l1_1: int = 0
    npss: int = 0
    apsta: int = 0
    warning_temp: int = 0
    critical_temp: int = 0
    nvme_vid: str | None = None
    nvme_ssvid: str | None = None
    ieee: str | None = None
    eui64: str | None = None
    precr: int = 0
    disable_hmb: int = 0
    multi_ns: int = 0
    irst: int = 0
    ps4_max_power: int = 0
    fna_format: int = 0
    fna_erase: int = 0
    gate_apsta: int = 0
    gate_warning: int = 0
    gate_critical: int = 0
    eui64_by_nvme: int = 0
    gate_ps4: int = 0
    gate_fna_format: int = 0
    gate_fna_erase: int = 0
    security: int = 0
    support_rpmb: int = 0
    ata_passthrough: int = 0
    fw_auth: int = 0
    gate_security: int = 0
    gate_rpmb: int = 0
    gate_ata: int = 0
    thermal_throttle: int = 0
    ffu_keep_cid: int = 0
    mt1: int = 0
    mt2: int = 0
    mt3: int = 0
    mt1_delta: int = 0
    mt2_delta: int = 0
    mt3_delta: int = 0
    gate_mt: int = 0
    gate_mt_delta: int = 0
    ps0_sys: int = 0
    ps0_ldpc: int = 0
    ps0_flash: int = 0
    ps1_sys: int = 0
    ps1_ldpc: int = 0
    ps1_flash: int = 0
    ps2_sys: int = 0
    ps2_ldpc: int = 0
    ps2_flash: int = 0
    ps5_sys: int = 0
    ps5_ldpc: int = 0
    ps5_flash: int = 0
    gate_ps_clocks: int = 0
    smart_temp_option: int = 0
    smart_temp_value: str | None = None
    gate_smart_temp: int = 0
    temp_offset: tuple = (0, 0, 0, 0, 0, 0)
    gate_smart_temp_offset: int = 0
    c4: int = 0
    cc: int = 0
    d4: int = 0
    en_output_uart: int = 0
    fix_mode_erase_th: int = 0
    pe_cycle: int = 0
    gate_seq_read_th: int = 0
    gate_pe_cycle: int = 0
    enable_write_protect: int = 0
    enable_bdg_scan: int = 0
    gate_write_protect: int = 0
    gate_bdg_scan: int = 0
    vdt_enable_27_23: int = 0
    vdt_enable_12: int = 0
    vdt_level_27: int = 0
    vdt_level_23: int = 0
    vdt_level_12: int = 0
    gate_vdt: int = 0
    bypass_ext_pwr_dn: int = 0
    cache_program: int = 0
    seq_read_th: int = 0
    watch_dog: int = 0
    bg_gc: int = 0
    cache_read: int = 0
    read_scrub: int = 0
    mt1_510: int = 0
    mt2_510: int = 0
    mt3_510: int = 0
    asic_shutdown: int = 0
    idle_gc: int = 0
    gate_bypass: int = 0
    gate_idle_gc: int = 0
    d8: int = 0
    slc_loop: int = 0
    tlc_loop: int = 0
    ref_mode: int = 0
    erase: int = 0
    program: int = 0
    read_en: int = 0
    rdt_test_mode_b4: int = 0
    rdt_test_mode: int = 0
    disable_thermal: int = 0
    read_write_seq: int = 0
    slc_ecc_bit_th: int = 0
    tlc_ecc_bit_th: int = 0
    temperature_th: int = 0
    total_fail_th: int = 0
    erase_fail_th: int = 0
    program_fail_th: int = 0
    read_fail_th: int = 0
    read_loop_th: int = 0
    rdt_test_mode_loop: int = 0
    disable_thermal_temp: int = 0
    erase_disturb: int = 0
    led_mode: int = 0
    retry_enable: int = 0
    slc_delay: int = 0
    tlc_delay: int = 0
    read_write_seq_cnt: int = 0
    test_block_cnt: str | None = None
    tlc_prog_en: int = 0
    slc_prog_en: int = 0
    tlc_block_num: int = 0
    slc_block_num: int = 0
    slc_prog_th: int = 0
    tlc_prog_th: int = 0
    tlc_bers_en: int = 0
    slc_bers_en: int = 0
    slc_bers_th: int = 0
    tlc_bers_th: int = 0
    prog_timeout_ratio: int = 0
    bser_timeout_ratio: int = 0
    chce_matrix: bytes = bytes(48)
    gate_rdt_test_mode: int = 0
    gate_disable_thermal: int = 0
    gate_read_loop: int = 0
    gate_debug: int = 0
    gate_erase_disturb: int = 0
    gate_led: int = 0
    gate_retry: int = 0
    gate_delay: int = 0
    gate_rw_seq: int = 0
    gate_tprog: int = 0
    gate_tbers: int = 0
    gate_prog_timeout: int = 0
    gate_bser_timeout: int = 0
    gate_chce: int = 0
    gate_32359fc: int = 0
    c_a8_zero: int = 0
    c_ab6: int = 0
    c_aba: int = 0
    gate_ui_e94: int = 0
    c_b32: int = 0
    c_ad2: int = 0
    c_ab2: int = 0
    c_aae: int = 0
    c_b36: int = 0
    c_b3a: int = 0
    c_b3e: int = 0
    global_3235b20: int = 0
    gate_ui_ef8: int = 0
    ef8_enabled: int = 0
    c_b7e: int = 0
    c_b82: int = 0
    c_b86: int = 0
    gate_ui_e80: int = 0
    gate_ui_e8c: int = 0
    c_b8e: int = 0
    c_bfc_low: int = 0
    gate_common: int = 0


def apply_pcie_nvme(cid: bytearray, c: CidConfig) -> None:
    _parse_reverse(c.pci_vendor_id, cid, 0x200, 2)
    _parse_reverse(c.pci_device_id, cid, 0x202, 2)

    x = cid[0x214]
    x = (x & 0xF0) | ((c.pcie_speed_index + 1) & 0x0F)
    x &= 0x8F
    width = 0
    if 0 <= c.pcie_lane_index < 31:
        width = 1 << c.pcie_lane_index
    cid[0x214] = x | ((width << 4) & 0xFF)

    cid[0x215] = (cid[0x215] & 0xF3) | ((c.aspm_support << 2) & 0xFF)
    _set_bit(cid, 0x216, 0x04, c.clock_pm)
    _set_bit(cid, 0x220, 0x04, c.aspm_l1_2)
    _set_bit(cid, 0x220, 0x08, c.aspm_l1_1)
    _parse_reverse(c.subsys_vendor_id, cid, 0x230, 2)
    _parse_reverse(c.subsys_id, cid, 0x232, 2)

    if c.npss < 6:
        cid[0x247] = NPSS_TABLE[c.npss]
    if c.gate_apsta:
        _set_bit(cid, 0x248, 0x01, c.apsta)
    if c.gate_warning:
        _put16(cid, 0x24A, c.warning_temp + 273)
    if c.gate_critical:
        _put16(cid, 0x24C, c.critical_temp + 273)
    _parse_reverse(c.nvme_vid, cid, 0x26A, 2)
    _parse_reverse(c.nvme_ssvid, cid, 0x26C, 2)
    if not c.eui64_by_nvme:
        for i in range(3):
            a = c.ieee[2 * i] if c.ieee and 2 * i < len(c.ieee) else "\0"
            b = c.ieee[2 * i + 1] if c.ieee and 2 * i + 1 < len(c.ieee) else "\0"
            cid[0x28F - i] = (
                (_hex_nibble(a) << 4) | _hex_nibble(b) if a != "\0" and b != "\0" else 0
            )
        for i in range(8):
            a = c.eui64[2 * i] if c.eui64 and 2 * i < len(c.eui64) else "\0"
            b = c.eui64[2 * i + 1] if c.eui64 and 2 * i + 1 < len(c.eui64) else "\0"
            cid[0x2A7 - i] = (
                (_hex_nibble(a) << 4) | _hex_nibble(b) if a != "\0" and b != "\0" else 0
            )
    _set_bit(cid, 0x2B6, 0x01, c.precr)
    _set_bit(cid, 0x2B7, 0x01, c.disable_hmb)
    _set_bit(cid, 0x2B7, 0x02, c.multi_ns)
    _set_bit(cid, 0x2B7, 0x04, c.irst)
    if c.gate_ps4:
        _put16(cid, 0x2A8, c.ps4_max_power)
    if c.gate_fna_format:
        _set_bit(cid, 0x26F, 0x01, c.fna_format)
    if c.gate_fna_erase:
        _set_bit(cid, 0x26F, 0x02, c.fna_erase)


def apply_security_runtime(cid: bytearray, c: CidConfig) -> None:
    if c.gate_security:
        cid[0x300] &= 0xE8
        cid[0x300] = {0: 0, 1: 0x01, 2: 0x03, 3: 0x05}.get(c.security, cid[0x300])
    if c.gate_rpmb:
        _set_bit(cid, 0x301, 0x01, c.support_rpmb)
    if c.gate_ata:
        _set_bit(cid, 0x300, 0x10, c.ata_passthrough)
    if c.gate_security:
        if c.security in (1, 2):
            cid[0x304] = 1
        elif c.security == 3:
            cid[0x304] = 0
    _set_bit(cid, 0x305, 0x01, c.fw_auth)

    _set_bit(cid, 0x390, 0x01, c.thermal_throttle)
    _set_bit(cid, 0x390, 0x08, c.ffu_keep_cid)
    if not c.c4 or c.cc or c.d4:
        cid[0x393] = (c.mt1 + 50) & 0xFF
        cid[0x395] = (c.mt2 + 50) & 0xFF
        cid[0x397] = (c.mt3 + 50) & 0xFF
        if c.gate_mt_delta:
            cid[0x394] = c.mt1_delta & 0xFF
            cid[0x396] = c.mt2_delta & 0xFF
            cid[0x398] = c.mt3_delta & 0xFF

    _put16(cid, 0x3A0, _clock(SYS_CLOCKS, c.ps0_sys))
    _put16(cid, 0x3A2, _clock(LDPC_FLASH_CLOCKS, c.ps0_ldpc))
    _put16(cid, 0x3A4, _clock(LDPC_FLASH_CLOCKS, c.ps0_flash))
    if c.gate_ps_clocks:
        _put16(cid, 0x3A8, _clock(SYS_CLOCKS, c.ps1_sys))
        _put16(cid, 0x3AA, _clock(LDPC_FLASH_CLOCKS, c.ps1_ldpc))
        _put16(cid, 0x3AC, _clock(LDPC_FLASH_CLOCKS, c.ps1_flash))
        _put16(cid, 0x3B0, _clock(SYS_CLOCKS, c.ps2_sys))
        _put16(cid, 0x3B2, _clock(LDPC_FLASH_CLOCKS, c.ps2_ldpc))
        _put16(cid, 0x3B4, _clock(LDPC_FLASH_CLOCKS, c.ps2_flash))
        _put16(cid, 0x3B8, _clock(SYS_CLOCKS, c.ps5_sys))
        _put16(cid, 0x3BA, _clock(LDPC_FLASH_CLOCKS, c.ps5_ldpc))
        _put16(cid, 0x3BC, _clock(LDPC_FLASH_CLOCKS, c.ps5_flash))

    if c.gate_smart_temp and not c.c4:
        cid[0x3CC] = c.smart_temp_option & 0xFF
        cid[0x3CD] = _decimal_byte(c.smart_temp_value)
    if c.gate_smart_temp_offset:
        for i, off in enumerate((0x3C1, 0x3C3, 0x3C5, 0x3C7, 0x3C9, 0x3CB)):
            cid[off] = c.temp_offset[i] & 0xFF


def _decimal_byte(text: str | None) -> int:
    if not text:
        return 0
    s = text.lstrip(" ")
    negative = False
    if s[:1] in ("+", "-"):
        negative = s[0] == "-"
        s = s[1:]
    base = 10
    if s.startswith("$"):
        base = 16
        s = s[1:]
    elif s[:2].lower() == "0x":
        base = 16
        s = s[2:]
    value = 0
    for ch in s:
        if "0" <= ch <= "9":
            d = ord(ch) - ord("0")
        elif base == 16 and "a" <= ch <= "f":
            d = ord(ch) - ord("a") + 10
        elif base == 16 and "A" <= ch <= "F":
            d = ord(ch) - ord("A") + 10
        else:
            break
        if d >= base:
            break
        value = value * base + d
    return (0x100 - value) & 0xFF if negative else value & 0xFF


def apply_small(cid: bytearray, c: CidConfig) -> None:
    _set_bit(cid, 0x182, 0x01, c.en_output_uart)
    if c.gate_seq_read_th:
        _put16(cid, 0x1D0, c.fix_mode_erase_th)
    if c.gate_pe_cycle:
        _put16(cid, 0x1D4, c.pe_cycle)
    if c.gate_write_protect:
        _set_bit(cid, 0x3F0, 0x04, c.enable_write_protect)
    if c.gate_bdg_scan:
        _set_bit(cid, 0x3F0, 0x08, c.enable_bdg_scan)
    if c.gate_vdt:
        _set_bit(cid, 0x500, 0x04, c.vdt_enable_27_23)
        _set_bit(cid, 0x500, 0x08, c.vdt_enable_12)
        if c.vdt_enable_27_23:
            cid[0x501] = c.vdt_level_27 & 0xFF
            cid[0x502] = c.vdt_level_23 & 0xFF
        if c.vdt_enable_12:
            cid[0x504] = c.vdt_level_12 & 0xFF
    if c.gate_bypass:
        _set_bit(cid, 0x59D, 0x01, c.bypass_ext_pwr_dn)
    if c.d8 == 0:
        _set_bit(cid, 0x59E, 0x04, c.cache_program)
    if c.gate_seq_read_th:
        cid[0x59F] = c.seq_read_th & 0xFF

    if c.c4 and not c.cc and not c.d4:
        cid[0x59C] = c.watch_dog & 0xFF
        _set_bit(cid, 0x59E, 0x01, c.bg_gc)
        _set_bit(cid, 0x59E, 0x02, c.cache_read)
        _set_bit(cid, 0x59E, 0x08, c.read_scrub)
        cid[0x5A0] = (c.mt1_510 + 0x32) & 0xFF
        cid[0x5A2] = (c.mt2_510 + 0x32) & 0xFF
        cid[0x5A3] = (c.mt3_510 + 0x32) & 0xFF
        cid[0x5A5] = c.asic_shutdown & 0xFF
    elif c.gate_idle_gc:
        if c.idle_gc:
            cid[0x59E] |= 0x03
        else:
            cid[0x59E] &= ~0x03 & 0xFF


def apply_rdt(cid: bytearray, c: CidConfig) -> None:
    r = memoryview(cid)[0xE00:0x1000]

    r[0x00] = c.slc_loop & 0xFF
    _set_bit(r, 0x01, 0x01, c.erase)
    _set_bit(r, 0x01, 0x02, c.program)
    _set_bit(r, 0x01, 0x04, c.read_en)
    _set_bit(r, 0x01, 0x10, c.rdt_test_mode_b4)
    if c.gate_rdt_test_mode:
        _set_bit(r, 0x01, 0x20, c.rdt_test_mode)
    if c.gate_disable_thermal:
        _set_bit(r, 0x01, 0x40, c.disable_thermal)
    if c.read_write_seq == 1:
        r[0x01] |= 0x80

    r[0x04] = c.ref_mode & 0xFF
    r[0x05] = 0xFF if not c.slc_ecc_bit_th else c.slc_ecc_bit_th & 0xFF
    r[0x06] = 0xFF if not c.tlc_ecc_bit_th else c.tlc_ecc_bit_th & 0xFF
    r[0x07] = c.temperature_th & 0xFF
    r[0x08:0x0A] = (c.total_fail_th & 0xFFFF).to_bytes(2, "little")
    r[0x0A:0x0C] = (c.erase_fail_th & 0xFFFF).to_bytes(2, "little")
    r[0x0C:0x0E] = (c.program_fail_th & 0xFFFF).to_bytes(2, "little")
    r[0x0E:0x10] = (c.read_fail_th & 0xFFFF).to_bytes(2, "little")
    r[0x11] = (c.read_loop_th & 0xFF) if c.gate_read_loop else 1
    r[0x12:0x14] = ((_parse_u16(c.test_block_cnt) if c.gate_debug else 0) & 0xFFFF).to_bytes(
        2, "little"
    )
    if c.gate_rdt_test_mode:
        r[0x14] = (c.rdt_test_mode_loop & 0xFF) if c.rdt_test_mode else 2
    if c.gate_disable_thermal:
        r[0x15] = (c.disable_thermal_temp & 0xFF) if c.disable_thermal else 0x5A
    if c.gate_erase_disturb:
        _set_bit(r, 0x16, 0x02, c.erase_disturb)
    if c.gate_led:
        r[0x17] = c.led_mode & 0xFF
    r[0x20] = c.tlc_loop & 0xFF
    if c.gate_retry:
        r[0x21] = 1 if c.retry_enable else 0
    if c.gate_delay:
        r[0x26:0x28] = (c.slc_delay & 0xFFFF).to_bytes(2, "little")
        r[0x28:0x2A] = (c.tlc_delay & 0xFFFF).to_bytes(2, "little")
    if c.gate_rw_seq:
        r[0x38] = c.read_write_seq_cnt & 0xFF
    if c.gate_tprog:
        _set_bit(r, 0x40, 0x01, c.tlc_prog_en)
        _set_bit(r, 0x40, 0x02, c.slc_prog_en)
        r[0x44:0x46] = (c.tlc_block_num & 0xFFFF).to_bytes(2, "little")
        r[0x46:0x48] = (c.slc_block_num & 0xFFFF).to_bytes(2, "little")
        r[0x48:0x4A] = (c.slc_prog_th & 0xFFFF).to_bytes(2, "little")
        r[0x4A:0x4C] = (c.tlc_prog_th & 0xFFFF).to_bytes(2, "little")
    if c.gate_tbers:
        _set_bit(r, 0x40, 0x04, c.tlc_bers_en)
        _set_bit(r, 0x40, 0x08, c.slc_bers_en)
        r[0x4C:0x4E] = (c.slc_bers_th & 0xFFFF).to_bytes(2, "little")
        r[0x4E:0x50] = (c.tlc_bers_th & 0xFFFF).to_bytes(2, "little")
    if c.gate_prog_timeout:
        r[0x50] = c.prog_timeout_ratio & 0xFF
    if c.gate_bser_timeout:
        r[0x51] = c.bser_timeout_ratio & 0xFF
    if c.gate_chce:
        r[0x80:0xB0] = c.chce_matrix[:48]


def apply_wrapper(cid: bytearray, c: CidConfig) -> None:
    if c.gate_32359fc and c.c_a8_zero:
        _set_bit(cid, 0x305, 0x01, c.c_ab6)
        _set_bit(cid, 0x390, 0x08, c.c_aba)
    if c.gate_ui_e94:
        cid[0x215] = (cid[0x215] & 0xF3) | ((c.c_b32 << 2) & 0xFF)
        _set_bit(cid, 0x216, 0x04, c.c_ad2)
        _set_bit(cid, 0x220, 0x04, c.c_ab2)
        _set_bit(cid, 0x220, 0x08, c.c_aae)
        _put16(cid, 0x3A0, _clock(SYS_CLOCKS, c.c_b36))
        _put16(cid, 0x3A2, _clock(LDPC_FLASH_CLOCKS, c.c_b3a))
        _put16(cid, 0x3A4, _clock(LDPC_FLASH_CLOCKS, c.c_b3e))
        if c.global_3235b20 > 0:
            _put16(cid, 0x3A2, c.global_3235b20 & 0xFFFF)
            _put16(cid, 0x3A4, c.global_3235b20 & 0xFFFF)
    if c.gate_ui_ef8:
        if c.ef8_enabled:
            cid[0x390] |= 0x01
            _put16(cid, 0x393, c.c_b7e)
            _put16(cid, 0x395, c.c_b82)
            _put16(cid, 0x397, c.c_b86)
        else:
            cid[0x390] &= ~0x01 & 0xFF
    if c.gate_ui_e80 and c.gate_ui_e8c:
        cid[0x3CC] = c.c_b8e & 0xFF
        cid[0x3CD] = c.c_bfc_low & 0xFF


def _parse_u16(text: str | None) -> int:
    if not text:
        return 0
    s = text.lstrip(" ")
    negative = False
    if s[:1] in ("+", "-"):
        negative = s[0] == "-"
        s = s[1:]
    base = 10
    if s.startswith("$"):
        base = 16
        s = s[1:]
    elif s[:2].lower() == "0x":
        base = 16
        s = s[2:]
    value = 0
    for ch in s:
        if "0" <= ch <= "9":
            d = ord(ch) - ord("0")
        elif base == 16 and "a" <= ch <= "f":
            d = ord(ch) - ord("a") + 10
        elif base == 16 and "A" <= ch <= "F":
            d = ord(ch) - ord("A") + 10
        else:
            break
        if d >= base:
            break
        value = (value * base + d) & 0xFFFF
    return (0x10000 - value) & 0xFFFF if negative else value


def build(base: bytes, c: CidConfig) -> bytes:
    cid = bytearray(base[:CID_BYTES])
    if len(cid) != CID_BYTES:
        raise CidError("base must be 4096 bytes")
    if c.gate_common:
        apply_pcie_nvme(cid, c)
        apply_security_runtime(cid, c)
        apply_small(cid, c)
    if not c.c_a8_zero:
        apply_rdt(cid, c)
    apply_wrapper(cid, c)
    return bytes(cid)


IDENTITY_FIELDS = ((0x008, 8), (0x10C, 20), (0x128, 32))


def identity(
    cid: bytes, version: str | None = None, serial: str | None = None, model: str | None = None
) -> bytes:
    """Space-padded, truncated writes of the three identity fields."""
    out = bytearray(cid[:CID_BYTES])
    for (offset, length), value in zip(IDENTITY_FIELDS, (version, serial, model)):
        if value is None:
            continue
        raw = value.encode("ascii")[:length]
        out[offset : offset + length] = b" " * length
        out[offset : offset + len(raw)] = raw
    return bytes(out)


@dataclass
class MapReport:
    applied: int = 0
    skipped: int = 0
    sections: int = 0


def _csv_number(text: str, base: int) -> int:
    s = text.strip(" \t\r")
    if len(s) > 2 and s[0] == "0" and s[1] in "xX":
        s = s[2:]
        base = 16
    elif base == 16 and s[-1:] in ("h", "H"):
        s = s[:-1]
    if not s:
        raise CidError("empty number")
    return int(s, base)


def apply_map(cid: bytes, csv_text: str) -> tuple[bytes, MapReport]:
    """Applies a vendor LightSwitch CSV (section rows carry the base)."""
    out = bytearray(cid[:CID_BYTES])
    report = MapReport()
    group = 0
    for line in csv_text.splitlines():
        if not line:
            continue
        fields = line.split(",")
        if len(fields) < 6:
            if fields[2]:
                try:
                    group = _csv_number(fields[2], 16)
                except (CidError, ValueError):
                    pass
            report.sections += 1
            continue
        try:
            enabled = _csv_number(fields[0], 10)
            offset = _csv_number(fields[4], 16)
            bit = _csv_number(fields[5], 10)
            width = _csv_number(fields[6], 10)
        except (CidError, ValueError, IndexError) as exc:
            raise CidError(f"malformed CSV row: {line!r}") from exc
        base = 16 if fields[3].startswith("hex") else 10
        try:
            value = _csv_number(fields[2], base)
        except (CidError, ValueError) as exc:
            raise CidError(f"malformed CSV value: {line!r}") from exc
        if not enabled or not width or width > 32 or bit > 31 or bit + width > 32:
            report.skipped += 1
            continue
        last = group + offset + (bit + width - 1) // 8
        if last >= CID_BYTES:
            report.skipped += 1
            continue
        for i in range(width):
            index = bit + i
            mask = 1 << (index & 7)
            at = group + offset + (index >> 3)
            if value & (1 << i):
                out[at] |= mask
            else:
                out[at] &= ~mask & 0xFF
        report.applied += 1
    if not report.applied:
        raise CidError("no applicable CSV rows")
    return bytes(out), report
