import pathlib
import struct
import subprocess

import os
import pathlib
import shutil
import struct
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
BUILD = ROOT / 'build'

def get_zig_compiler() -> str:
    zig = shutil.which('zig') or shutil.which('python-zig')
    if zig:
        return zig
    scripts_zig = pathlib.Path(sys.executable).parent / 'Scripts' / 'python-zig.exe'
    if scripts_zig.is_file():
        return str(scripts_zig)
    raise FileNotFoundError("Zig compiler not found. Please install via 'pip install ziglang' or add zig to PATH.")


def load_vmlinux_crcs(vmlinux_path: pathlib.Path) -> dict[str, int]:
    b = vmlinux_path.read_bytes()
    e_shoff = struct.unpack_from('<Q', b, 40)[0]
    e_shentsize, e_shnum, e_shstrndx = struct.unpack_from('<HHH', b, 58)
    shstr_off, shstr_sz = struct.unpack_from('<QQ', b, e_shoff + e_shstrndx * e_shentsize + 24)
    shstr = b[shstr_off:shstr_off + shstr_sz]
    secs = {}
    for i in range(e_shnum):
        vals = struct.unpack_from('<IIQQQQIIQQ', b, e_shoff + i * e_shentsize)
        nm = shstr[vals[0]:shstr.find(b'\0', vals[0])].decode()
        secs[nm] = vals

    def v2f(vaddr: int) -> int:
        for vals in secs.values():
            if vals[1] == 1 and vals[3] <= vaddr < vals[3] + vals[5]:
                return vals[4] + (vaddr - vals[3])
        raise KeyError(hex(vaddr))

    crcs = {'module_layout': 0xda0486d9}
    for ksym_sec, kcrc_sec in [('__ksymtab', '__kcrctab'), ('__ksymtab_gpl', '__kcrctab_gpl')]:
        sv = secs[ksym_sec]
        cv = secs[kcrc_sec]
        for i in range(sv[5] // 12):
            pos = sv[4] + i * 12
            pos_v = sv[3] + i * 12
            _, name_off, _ = struct.unpack_from('<iii', b, pos)
            nf = v2f(pos_v + 4 + name_off)
            nm = b[nf:b.find(b'\0', nf)].decode()
            crc = struct.unpack_from('<I', b, cv[4] + i * 4)[0]
            crcs[nm] = crc
    return crcs


def main():
    c_src = pathlib.Path(__file__).resolve().parent / 'avx_vnni_emu.c'
    BUILD.mkdir(parents=True, exist_ok=True)
    obj_path = BUILD / 'avx_vnni_emu.o'
    ko_path = pathlib.Path(__file__).resolve().parent / 'avx_vnni_emu.ko'

    zig_bin = get_zig_compiler()
    cmd = [
        zig_bin, 'cc',
        '-target', 'x86_64-freestanding-none',
        '-mcpu=x86_64',
        '-O2', '-g0',
        '-mcmodel=kernel',
        '-fno-pic', '-fno-pie',
        '-mno-red-zone',
        '-mgeneral-regs-only',
        '-mno-mmx', '-mno-sse', '-mno-sse2', '-mno-avx', '-mno-x87',
        '-fno-vectorize', '-fno-slp-vectorize',
        '-fno-jump-tables',
        '-fno-stack-protector',
        '-fno-asynchronous-unwind-tables',
        '-fno-unwind-tables',
        '-fcf-protection=branch',
        '-c', str(c_src),
        '-o', str(obj_path),
    ]
    print('1. Compiling avx_vnni_emu.c -> avx_vnni_emu.o...', flush=True)
    subprocess.run(cmd, check=True)

    b = obj_path.read_bytes()
    e_shoff = struct.unpack_from('<Q', b, 40)[0]
    e_shentsize, e_shnum, e_shstrndx = struct.unpack_from('<HHH', b, 58)
    shstr_off, shstr_sz = struct.unpack_from('<QQ', b, e_shoff + e_shstrndx * e_shentsize + 24)
    shstr = b[shstr_off:shstr_off + shstr_sz]

    orig_secs = []
    for i in range(e_shnum):
        vals = list(struct.unpack_from('<IIQQQQIIQQ', b, e_shoff + i * e_shentsize))
        nm = shstr[vals[0]:shstr.find(b'\0', vals[0])].decode()
        data = b'' if vals[1] in (0, 8) else b[vals[4]:vals[4] + vals[5]]
        orig_secs.append({'name': nm, 'hdr': vals, 'data': data})

    symtab_sec = next(s for s in orig_secs if s['name'] == '.symtab')
    strtab_sec = next(s for s in orig_secs if s['name'] == '.strtab')
    strtab_raw = strtab_sec['data']

    orig_syms = []
    for off in range(0, len(symtab_sec['data']), 24):
        st_name, st_info, st_other, st_shndx, st_val, st_sz = struct.unpack_from('<IBBHQQ', symtab_sec['data'], off)
        nm = strtab_raw[st_name:strtab_raw.find(b'\0', st_name)].decode()
        orig_syms.append({
            'name': nm,
            'info': st_info,
            'other': st_other,
            'shndx': st_shndx,
            'val': st_val,
            'sz': st_sz,
        })

    # Keep sections except .symtab, .strtab, .shstrtab, .llvm_addrsig
    new_secs = [orig_secs[0]]  # index 0 = SHT_NULL
    old_to_new_sec = {0: 0}
    for old_idx in range(1, len(orig_secs)):
        s = orig_secs[old_idx]
        if s['name'] in ('.symtab', '.strtab', '.shstrtab', '.llvm_addrsig'):
            continue
        old_to_new_sec[old_idx] = len(new_secs)
        new_secs.append({
            'name': s['name'],
            'type': s['hdr'][1],
            'flags': s['hdr'][2],
            'link': s['hdr'][6],
            'info': s['hdr'][7],
            'align': max(s['hdr'][8], 1),
            'entsz': s['hdr'][9],
            'data': bytearray(s['data']),
            'bss_sz': s['hdr'][5] if s['hdr'][1] == 8 else 0,
        })

    print('   Kept object sections:', [s['name'] for s in new_secs[1:]], flush=True)

    # Remap symbol st_shndx
    syms = []
    old_to_new_sym = {}
    for idx, sym in enumerate(orig_syms):
        shndx = sym['shndx']
        if 0 < shndx < 0xff00:
            if shndx not in old_to_new_sec:
                continue
            shndx = old_to_new_sec[shndx]
        old_to_new_sym[idx] = len(syms)
        syms.append({**sym, 'shndx': shndx})

    # Ensure STT_SECTION local symbols exist for .text, .init.text, .exit.text
    sec_sym_for_new_shndx = {}
    for idx, sym in enumerate(syms):
        if (sym['info'] & 0xf) == 3:  # STT_SECTION
            sec_sym_for_new_shndx[sym['shndx']] = idx

    # Remap existing SHT_RELA sections
    for s in new_secs[1:]:
        if s['type'] == 4:  # SHT_RELA
            s['info'] = old_to_new_sec[s['info']]
            rebuilt = bytearray()
            for off in range(0, len(s['data']), 24):
                r_off, r_info, r_add = struct.unpack_from('<QQq', s['data'], off)
                old_sym = r_info >> 32
                r_type = r_info & 0xffffffff
                new_sym = old_to_new_sym[old_sym]
                rebuilt.extend(struct.pack('<QQq', r_off, (new_sym << 32) | r_type, r_add))
            s['data'] = rebuilt

    # Locate __cfi_* symbols for .cfi_sites
    cfi_names = ['__cfi_vnni_die_handler', '__cfi_init_module', '__cfi_cleanup_module']
    cfi_targets = []
    for cname in cfi_names:
        csym = next(sym for sym in syms if sym['name'] == cname)
        cfi_targets.append((csym['shndx'], csym['val']))
    print('   CFI sites:', list(zip(cfi_names, cfi_targets)), flush=True)

    # Ensure STT_SECTION symbols exist for CFI target sections (insert into locals before first global)
    first_global = next((i for i, sym in enumerate(syms) if (sym['info'] >> 4) != 0), len(syms))
    for shndx, _ in cfi_targets:
        if shndx not in sec_sym_for_new_shndx:
            # Insert a local STT_SECTION symbol at first_global and shift >= first_global relocations
            syms.insert(first_global, {
                'name': '',
                'info': 3,  # STB_LOCAL | STT_SECTION
                'other': 0,
                'shndx': shndx,
                'val': 0,
                'sz': 0,
            })
            for s in new_secs[1:]:
                if s['type'] == 4:
                    for off in range(0, len(s['data']), 24):
                        r_off, r_info, r_add = struct.unpack_from('<QQq', s['data'], off)
                        si = r_info >> 32
                        rt = r_info & 0xffffffff
                        if si >= first_global:
                            struct.pack_into('<QQq', s['data'], off, r_off, ((si + 1) << 32) | rt, r_add)
            sec_sym_for_new_shndx = {sym['shndx']: i for i, sym in enumerate(syms) if (sym['info'] & 0xf) == 3}
            first_global += 1

    cfi_sites_idx = len(new_secs)
    new_secs.append({
        'name': '.cfi_sites',
        'type': 1,
        'flags': 0x2,
        'link': 0,
        'info': 0,
        'align': 1,
        'entsz': 4,
        'data': bytearray(4 * len(cfi_targets)),
        'bss_sz': 0,
    })
    rela_cfi = bytearray()
    for i, (shndx, val) in enumerate(cfi_targets):
        sec_sym = sec_sym_for_new_shndx[shndx]
        # R_X86_64_PC32 = 2
        rela_cfi.extend(struct.pack('<QQq', i * 4, (sec_sym << 32) | 2, val))
    new_secs.append({
        'name': '.rela.cfi_sites',
        'type': 4,
        'flags': 0x40,
        'link': 0,  # patched to symtab_idx below
        'info': cfi_sites_idx,
        'align': 8,
        'entsz': 24,
        'data': rela_cfi,
        'bss_sz': 0,
    })

    # .modinfo
    modinfo = (
        b'description=VEX AVX-VNNI/IFMA #UD emulator for AMD Zen 4\x00'
        b'license=GPL\x00'
        b'name=avx_vnni_emu\x00'
        b'intree=Y\x00'
        b'scmversion=g3ec022196c4e\x00'
        b'depends=\x00'
        b'vermagic=6.12.74-android16-6-g3ec022196c4e-ab15076761 SMP preempt mod_unload modversions \x00'
        b'retpoline=Y\x00'
    )
    new_secs.append({
        'name': '.modinfo',
        'type': 1,
        'flags': 0x2,
        'link': 0,
        'info': 0,
        'align': 1,
        'entsz': 0,
        'data': bytearray(modinfo),
        'bss_sz': 0,
    })

    # .gnu.linkonce.this_module + .rela.gnu.linkonce.this_module
    this_mod = bytearray(0x580)
    mod_name_bytes = b'avx_vnni_emu\x00'
    this_mod[0x18:0x18 + len(mod_name_bytes)] = mod_name_bytes
    this_mod_idx = len(new_secs)
    new_secs.append({
        'name': '.gnu.linkonce.this_module',
        'type': 1,
        'flags': 0x3,
        'link': 0,
        'info': 0,
        'align': 64,
        'entsz': 0,
        'data': this_mod,
        'bss_sz': 0,
    })

    # Add __this_module global symbol
    syms.append({
        'name': '__this_module',
        'info': (1 << 4) | 1,  # STB_GLOBAL | STT_OBJECT
        'other': 0,
        'shndx': this_mod_idx,
        'val': 0,
        'sz': 0x580,
    })

    init_sym_idx = next(i for i, sym in enumerate(syms) if sym['name'] == 'init_module')
    exit_sym_idx = next(i for i, sym in enumerate(syms) if sym['name'] == 'cleanup_module')
    rela_this = bytearray()
    # R_X86_64_64 = 1
    rela_this.extend(struct.pack('<QQq', 0x198, (init_sym_idx << 32) | 1, 0))
    rela_this.extend(struct.pack('<QQq', 0x520, (exit_sym_idx << 32) | 1, 0))
    new_secs.append({
        'name': '.rela.gnu.linkonce.this_module',
        'type': 4,
        'flags': 0x40,
        'link': 0,
        'info': this_mod_idx,
        'align': 8,
        'entsz': 24,
        'data': rela_this,
        'bss_sz': 0,
    })

    # Collect undefined symbols and resolve CRCs from vmlinux
    crc_map = load_vmlinux_crcs(BUILD / 'vmlinux')
    undef_names = [sym['name'] for sym in syms[1:] if sym['shndx'] == 0]
    print('   Undefined kernel symbols:', undef_names, flush=True)
    ver_list = []
    for nm in undef_names + ['module_layout']:
        if nm not in crc_map:
            raise KeyError(f'Missing CRC in vmlinux for undefined symbol: {nm}')
        ver_list.append((nm, crc_map[nm]))
        print(f'     {nm:30s} -> 0x{crc_map[nm]:08x}', flush=True)

    versions_data = bytearray()
    ext_crcs_data = bytearray()
    ext_names_parts = []
    for nm, crc in ver_list:
        entry = bytearray(64)
        struct.pack_into('<Q', entry, 0, crc)
        nb = nm.encode('ascii') + b'\x00'
        assert len(nb) <= 56
        entry[8:8 + len(nb)] = nb
        versions_data.extend(entry)
        ext_crcs_data.extend(struct.pack('<I', crc))
        ext_names_parts.append(nm.encode('ascii'))
    ext_names_data = bytearray(b'\x00'.join(ext_names_parts) + b'\x00\x00')

    for sname, sdata in [
        ('__versions', versions_data),
        ('__version_ext_crcs', ext_crcs_data),
        ('__version_ext_names', ext_names_data),
    ]:
        new_secs.append({
            'name': sname,
            'type': 1,
            'flags': 0x2,
            'link': 0,
            'info': 0,
            'align': 16,
            'entsz': 0,
            'data': sdata,
            'bss_sz': 0,
        })

    # .note.Linux (exact 48 bytes from Cuttlefish 6.12.74 virtio-rng.ko)
    note_linux = bytes.fromhex(
        '0600000001000000000100004c696e757800000000000000'
        '0600000004000000010100004c696e757800000000000000'
    )
    new_secs.append({
        'name': '.note.Linux',
        'type': 7,
        'flags': 0x2,
        'link': 0,
        'info': 0,
        'align': 4,
        'entsz': 0,
        'data': bytearray(note_linux),
        'bss_sz': 0,
    })

    # Build .symtab and .strtab
    strtab_out = bytearray(b'\x00')
    symtab_out = bytearray()
    first_non_local = None
    for idx, sym in enumerate(syms):
        if idx > 0 and (sym['info'] >> 4) != 0 and first_non_local is None:
            first_non_local = idx
        elif idx > 0 and (sym['info'] >> 4) == 0 and first_non_local is not None:
            raise AssertionError('Local symbol after global symbol!')
        if sym['name']:
            st_name = len(strtab_out)
            strtab_out.extend(sym['name'].encode('ascii') + b'\x00')
        else:
            st_name = 0
        symtab_out.extend(struct.pack(
            '<IBBHQQ',
            st_name, sym['info'], sym['other'], sym['shndx'], sym['val'], sym['sz']
        ))
    if first_non_local is None:
        first_non_local = len(syms)

    symtab_idx = len(new_secs)
    strtab_idx = symtab_idx + 1
    shstrtab_idx = symtab_idx + 2

    # Fix sh_link on all SHT_RELA sections to point to symtab_idx
    for s in new_secs[1:]:
        if s['type'] == 4:
            s['link'] = symtab_idx

    new_secs.append({
        'name': '.symtab',
        'type': 2,
        'flags': 0,
        'link': strtab_idx,
        'info': first_non_local,
        'align': 8,
        'entsz': 24,
        'data': symtab_out,
        'bss_sz': 0,
    })
    new_secs.append({
        'name': '.strtab',
        'type': 3,
        'flags': 0,
        'link': 0,
        'info': 0,
        'align': 1,
        'entsz': 0,
        'data': strtab_out,
        'bss_sz': 0,
    })

    shstr_out = bytearray(b'\x00')
    sec_name_offs = [0]
    for s in new_secs[1:] + [{'name': '.shstrtab'}]:
        sec_name_offs.append(len(shstr_out))
        shstr_out.extend(s['name'].encode('ascii') + b'\x00')

    new_secs.append({
        'name': '.shstrtab',
        'type': 3,
        'flags': 0,
        'link': 0,
        'info': 0,
        'align': 1,
        'entsz': 0,
        'data': shstr_out,
        'bss_sz': 0,
    })

    # Assemble final ELF64 ET_REL (.ko)
    out = bytearray(64)
    shdrs = bytearray()
    shdrs.extend(b'\x00' * 64)  # SHT_NULL

    for idx in range(1, len(new_secs)):
        s = new_secs[idx]
        align = max(s['align'], 1)
        if align > 1 and (len(out) % align) != 0:
            out.extend(b'\x00' * (align - (len(out) % align)))
        off = len(out)
        if s['type'] == 8:  # SHT_NOBITS
            sz = s['bss_sz']
        else:
            sz = len(s['data'])
            out.extend(s['data'])
        shdrs.extend(struct.pack(
            '<IIQQQQIIQQ',
            sec_name_offs[idx],
            s['type'],
            s['flags'],
            0,
            off,
            sz,
            s['link'],
            s['info'],
            align,
            s['entsz'],
        ))

    if len(out) % 8 != 0:
        out.extend(b'\x00' * (8 - (len(out) % 8)))
    shoff = len(out)
    out.extend(shdrs)

    # ELF64 header (ET_REL = 1, EM_X86_64 = 62)
    e_ident = b'\x7fELF\x02\x01\x01' + b'\x00' * 9
    struct.pack_into(
        '<16sHHIQQQIHHHHHH',
        out, 0,
        e_ident,
        1,   # ET_REL
        62,  # EM_X86_64
        1,   # EV_CURRENT
        0,   # e_entry
        0,   # e_phoff
        shoff,
        0,   # e_flags
        64,  # e_ehsize
        0,   # e_phentsize
        0,   # e_phnum
        64,  # e_shentsize
        len(new_secs),
        shstrtab_idx,
    )

    ko_path.write_bytes(out)
    print(f'2. Successfully built {ko_path} ({len(out):,} bytes)!', flush=True)


if __name__ == '__main__':
    main()
