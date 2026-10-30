#!/usr/bin/env python3
"""Turn your own Touhou 8 / Touhou 11 install (with thcrap + the English patch already set up)
into a self-contained folder that Playden can run on a jailbroken PS5.

    python make_ps5_package.py <game folder> <output folder> [--copy-saves]

The game folder must contain the original Japanese exe (th08.exe v1.00d or th11.exe v1.00a) and a
thcrap folder made by thcrap_configure with the "thpatch-en" configuration.
"""
import argparse
import hashlib
import io
import json
import re
import shutil
import struct
import sys
from pathlib import Path

import pefile
from keystone import Ks, KS_ARCH_X86, KS_MODE_32

GAMES = {
    'th08': {'exe': 'th08.exe', 'build': 'v1.00d', 'dats': ['th08.dat', 'thbgm.dat'],
             'sha256': '330fbdbf58a710829d65277b4f312cfbb38d5448b3df523e79350b879213d924', 'size': 840704,
             'saves': ['score.dat', 'th08.cfg']},
    'th11': {'exe': 'th11.exe', 'build': 'v1.00a', 'dats': ['th11.dat', 'thbgm.dat'],
             'sha256': '2978b17f6184d100d249d4311348dd30c5c32ec75c014b667a525b797d3d8813', 'size': 688128,
             'saves': ['scoreth11.dat', 'th11.cfg']},
}

# 32-bit thcrap files the game needs at run time (the rest of thcrap/bin is the configurator,
# the updater and 64-bit builds).
BIN_FILES = ['thcrap.dll', 'thcrap_tsa.dll', 'thcrap_tasofro.dll', 'win32_utf8.dll', 'jansson.dll',
             'zlib-ng.dll', 'libpng16.dll', 'fribidi.dll', 'act_nut_lib.dll', 'steam_api.dll',
             'bmpfont_create_gdi.dll', 'bmpfont_create_gdiplus.dll']

# Some old Intel-compiled exes keep this banner right after the section table.
INTEL_BANNER = b'Intel(R) C/C++ Compiler Version 4.5 0001'


def fail(message):
    sys.exit('error: ' + message)


# --- the exe: a loader stub instead of thcrap_loader --------------------------------------------

def add_loader_stub(exe_bytes, config):
    """Adds a section whose code loads thcrap\\bin\\thcrap.dll next to the exe, calls
    thcrap_init(<run configuration JSON>) and then jumps to the game's own entry point."""
    pf = pefile.PE(data=bytes(exe_bytes))
    imports = {i.name: i.address for e in pf.DIRECTORY_ENTRY_IMPORT if e.dll.lower() == b'kernel32.dll'
               for i in e.imports if i.name}
    pf.close()
    if b'LoadLibraryA' not in imports or b'GetProcAddress' not in imports:
        fail('the exe does not import LoadLibraryA and GetProcAddress')
    load_library, get_proc = imports[b'LoadLibraryA'], imports[b'GetProcAddress']

    d = bytearray(exe_bytes)
    pe = struct.unpack_from('<I', d, 0x3c)[0]
    nsec = struct.unpack_from('<H', d, pe + 6)[0]
    opt = pe + 24
    sectab = opt + struct.unpack_from('<H', d, pe + 20)[0]
    entry = struct.unpack_from('<I', d, opt + 16)[0]
    base = struct.unpack_from('<I', d, opt + 28)[0]
    secalign, filealign = struct.unpack_from('<II', d, opt + 32)
    size_of_image = struct.unpack_from('<I', d, opt + 56)[0]
    slot = bytes(d[sectab + nsec * 40: sectab + (nsec + 1) * 40])
    first_raw = min(struct.unpack_from('<I', d, sectab + k * 40 + 20)[0] for k in range(nsec))
    if slot not in (bytes(40), INTEL_BANNER) or sectab + (nsec + 1) * 40 > first_raw:
        fail('no room in the exe header for another section')

    vbase = base + size_of_image
    wide = lambda s: (s + '\0').encode('utf-16-le')
    strings = [
        ('kernel32', b'kernel32.dll\0'),
        ('gmf', b'GetModuleFileNameW\0'),
        ('scd', b'SetCurrentDirectoryW\0'),
        ('sdd', b'SetDllDirectoryW\0'),
        ('llw', b'LoadLibraryW\0'),
        ('init', b'thcrap_init\0'),
        ('bin', wide('thcrap\\bin\\')),
        ('dll', wide('thcrap.dll')),
        ('json', json.dumps(config, separators=(',', ':')).encode() + b'\0'),
    ]
    code_size = 0x200
    addr, blob = {}, b''
    for name, data in strings:
        blob += b'\0' * (len(blob) % 2)
        addr[name] = vbase + code_size + len(blob)
        blob += data
    buf_offset = (code_size + len(blob) + 3) & ~3
    buf = vbase + buf_offset

    asm = f"""
    pushad
    push {addr['kernel32']}
    call dword ptr [{load_library:#x}]
    mov ebx, eax
    push {addr['gmf']}
    push ebx
    call dword ptr [{get_proc:#x}]
    push 260
    push {buf}
    push 0
    call eax
    mov edi, {buf}
    lea edi, [edi+eax*2]
    back:
    sub edi, 2
    cmp word ptr [edi], 0x5c
    jne back
    mov word ptr [edi+2], 0
    push {addr['scd']}
    push ebx
    call dword ptr [{get_proc:#x}]
    push {buf}
    call eax
    add edi, 2
    mov esi, {addr['bin']}
    copy_bin:
    lodsw
    stosw
    test ax, ax
    jnz copy_bin
    push {addr['sdd']}
    push ebx
    call dword ptr [{get_proc:#x}]
    push {buf}
    call eax
    sub edi, 2
    mov esi, {addr['dll']}
    copy_dll:
    lodsw
    stosw
    test ax, ax
    jnz copy_dll
    push {addr['llw']}
    push ebx
    call dword ptr [{get_proc:#x}]
    push {buf}
    call eax
    test eax, eax
    jz done
    push {addr['init']}
    push eax
    call dword ptr [{get_proc:#x}]
    test eax, eax
    jz done
    push {addr['json']}
    call eax
    add esp, 4
    done:
    popad
    mov eax, {base + entry:#x}
    jmp eax
    """
    code = bytes(Ks(KS_ARCH_X86, KS_MODE_32).asm(asm, vbase)[0])
    assert len(code) < code_size

    section = (code.ljust(code_size, b'\xcc') + blob).ljust(buf_offset + 1024, b'\0')
    raw_size = -(-len(section) // filealign) * filealign
    virtual_size = -(-len(section) // secalign) * secalign
    raw_pointer = -(-len(d) // filealign) * filealign
    d += b'\0' * (raw_pointer - len(d)) + section.ljust(raw_size, b'\0')
    d[sectab + nsec * 40: sectab + (nsec + 1) * 40] = struct.pack(
        '<8sIIIIIIHHI', b'.thc', len(section), size_of_image, raw_size, raw_pointer, 0, 0, 0, 0, 0xE0000060)
    struct.pack_into('<H', d, pe + 6, nsec + 1)
    struct.pack_into('<I', d, opt + 16, size_of_image)
    struct.pack_into('<I', d, opt + 56, size_of_image + virtual_size)
    struct.pack_into('<I', d, opt + 64, 0)
    return bytes(d)


# --- thcrap fixes for Playden ---------------------------------------------------------------------

def patch_win32_utf8(path):
    """GetStartupInfoU converts lpDesktop and lpTitle without a NULL check; Playden's Wine leaves both
    NULL, so the game crashes at start. Skipping the two conversions leaves them NULL."""
    d = bytearray(path.read_bytes())
    patterns = [rb'\x83\x3d....\x00(\x75)\x48\x8b\x74\x24\x0c\x8d\x4e\x02',
                rb'\x8b\x15....\x85\xd2(\x75)\x4c\x8b\x74\x24\x10\x8d\x4e\x02']
    for pattern in patterns:
        found = list(re.finditer(pattern, d, re.S))
        if len(found) != 1:
            already = list(re.finditer(pattern.replace(rb'(\x75)', rb'(\xeb)'), d, re.S))
            if len(already) == 1:
                continue
            fail(f'{path.name}: GetStartupInfoU not recognised (this thcrap build is not supported)')
        d[found[0].start(1)] = 0xEB
    path.write_bytes(d)


def register_exe(versions_path, game, info, exe):
    """thcrap identifies the game by the exe's hash and size: list the patched exe as the original."""
    text = versions_path.read_text(encoding='utf-8')
    entry = f'["{game}", "{info["build"]}", "(original)"],\n'
    sha_line = f'\t\t"{info["sha256"]}": ' + entry
    size_line = f'\t\t"{info["size"]}": ' + entry
    if sha_line not in text or size_line not in text:
        fail(f'{versions_path} does not list the original {game} exe')
    new_sha = f'\t\t"{hashlib.sha256(exe).hexdigest()}": ' + entry
    new_size = f'\t\t"{len(exe)}": ' + entry
    if new_sha not in text:
        text = text.replace(sha_line, sha_line + new_sha)
    if new_size not in text:
        text = text.replace(size_line, size_line + new_size)
    versions_path.write_text(text, encoding='utf-8', newline='')


def patch_th08_binhacks(path):
    """Touhou 8 checks its own exe's size and checksum; the patched exe fails it and the check then
    reads past its list. thcrap's TH8ScorefileFixer works around a failure by writing into the read-only
    .rdata section, which faults on Playden. Drop that hook and make the check pass instead."""
    text = path.read_text(encoding='utf-8')
    match = re.search(r'\t\t"TH8ScorefileFixer": \{[^{}]*\},\n', text)
    if match:
        text = text[:match.start()] + text[match.end():]
    if 'playden_skip_exe_check' not in text:
        key = '\t"binhacks": {\n'
        if text.count(key) != 1:
            fail(f'{path.name}: binhacks section not found')
        text = text.replace(key, key +
                            '\t\t"playden_skip_exe_check": {\n'
                            '\t\t\t"title": "Accept the modified th08.exe (exe size/checksum self-check always passes)",\n'
                            '\t\t\t"addr": "0x44858D",\n'
                            '\t\t\t"code": "31C0 // C2 0C00",\n'
                            '\t\t\t"expected": "55 // 8BEC // 83EC 2C"\n'
                            '\t\t},\n')
    path.write_text(text, encoding='utf-8', newline='')


# --- Home screen icon ----------------------------------------------------------------------------

def write_icon(exe_path, out_path):
    """The exe's own icon as a 512x512 opaque PNG, the format Playden uses for icon0.png."""
    try:
        from PIL import Image
    except ImportError:
        print('  (Pillow not installed: no icon0.png)')
        return
    pf = pefile.PE(str(exe_path))
    icons, group = {}, None
    for res in pf.DIRECTORY_ENTRY_RESOURCE.entries:
        for entry in res.directory.entries:
            leaf = entry.directory.entries[0].data.struct
            data = pf.get_data(leaf.OffsetToData, leaf.Size)
            if res.id == 3:
                icons[entry.id] = data
            elif res.id == 14 and group is None:
                group = data
    pf.close()
    if group is None:
        return
    count = struct.unpack_from('<H', group, 4)[0]
    entries, images, offset = b'', b'', 6 + 16 * count
    for k in range(count):
        w, h, colors, reserved, planes, bits, _, icon_id = struct.unpack_from('<BBBBHHIH', group, 6 + 14 * k)
        image = icons[icon_id]
        entries += struct.pack('<BBBBHHII', w, h, colors, reserved, planes, bits, len(image), offset + len(images))
        images += image
    ico = Image.open(io.BytesIO(struct.pack('<HHH', 0, 1, count) + entries + images))
    ico.size = max(ico.info['sizes'])
    rgba = ico.convert('RGBA').resize((512, 512), Image.NEAREST)
    icon = Image.new('RGB', (512, 512))
    icon.paste(rgba, (0, 0), rgba)
    icon.save(out_path)


# --- main --------------------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('game_folder', type=Path)
    parser.add_argument('output_folder', type=Path)
    parser.add_argument('--copy-saves', action='store_true', help='also copy your score file and settings')
    args = parser.parse_args()
    src, out = args.game_folder, args.output_folder

    game = next((g for g, info in GAMES.items() if (src / info['exe']).is_file()), None)
    if not game:
        fail('no th08.exe or th11.exe in ' + str(src))
    info = GAMES[game]
    exe = (src / info['exe']).read_bytes()
    if hashlib.sha256(exe).hexdigest() != info['sha256']:
        fail(f'{info["exe"]} is not the original Japanese {info["build"]} exe')
    config_path = src / 'thcrap/config/thpatch-en.js'
    if not config_path.is_file():
        fail('thcrap/config/thpatch-en.js not found: set up thcrap with the English patch first')
    if out.exists() and any(out.iterdir()):
        fail(f'{out} is not empty')

    print(f'{game} {info["build"]} -> {out}')
    (out / 'thcrap/bin').mkdir(parents=True, exist_ok=True)

    config = json.loads(config_path.read_text(encoding='utf-8'))
    config.update(game=game, build=info['build'])
    patched = add_loader_stub(exe, config)
    (out / info['exe']).write_bytes(patched)
    print('  exe patched')

    for name in info['dats'] + (info['saves'] if args.copy_saves else []):
        if (src / name).is_file():
            shutil.copy2(src / name, out / name)
    for name in BIN_FILES:
        if not (src / 'thcrap/bin' / name).is_file():
            fail(f'thcrap/bin/{name} missing')
        shutil.copy2(src / 'thcrap/bin' / name, out / 'thcrap/bin' / name)
    shutil.copytree(src / 'thcrap/config', out / 'thcrap/config')
    shutil.copytree(src / 'thcrap/repos', out / 'thcrap/repos')
    print('  game data and thcrap copied')

    patch_win32_utf8(out / 'thcrap/bin/win32_utf8.dll')
    register_exe(out / 'thcrap/repos/nmlgc/base_tsa/versions.js', game, info, patched)
    if game == 'th08':
        patch_th08_binhacks(out / 'thcrap/repos/nmlgc/base_tsa/th08.v1.00d.js')
    print('  thcrap fixes applied')

    write_icon(src / info['exe'], out / 'icon0.png')
    print('done')


if __name__ == '__main__':
    main()
