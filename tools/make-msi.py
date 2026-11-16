#!/usr/bin/env python3
"""Standard-library WiX payload harvester. Never stages or rewrites payload bytes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import unicodedata
import uuid
import xml.etree.ElementTree as ET

NS = 'http://wixtoolset.org/schemas/v4/wxs'
ET.register_namespace('', NS)
AUTHORING = Path(__file__).resolve().parent.parent / 'packaging/annotshot.wxs'
MARKER = '.annotshot-msi-owned'
OWNED = {MARKER, 'Payload.wxs', 'Identity.wxi', 'manifest.json'}
MARKER_TEXT = 'annotshot-msi-harvester-v1\n'


def element(parent, tag, **attrs):
    return ET.SubElement(parent, f'{{{NS}}}{tag}', attrs)


def key(path):
    return unicodedata.normalize('NFC', 'INSTALLFOLDER/' + path).casefold()


def ident(prefix, canonical):
    return prefix + hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def guid(namespace, name):
    return '{' + str(uuid.uuid5(namespace, name)).upper() + '}'


def validate_version(version):
    if not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', version):
        raise ValueError('version must be canonical major.minor.patch')
    if any(n > limit for n, limit in zip(map(int, version.split('.')), (255, 255, 65535))):
        raise ValueError('version exceeds MSI limits 255.255.65535')


def validate_name(name):
    stem = name.split('.')[0].rstrip(' ').upper()
    if (name[-1:] in (' ', '.') or any(ord(c) < 32 or c in '<>:"/\\|?*' for c in name)
            or stem in {'CON', 'PRN', 'AUX', 'NUL', 'CONIN$', 'CONOUT$'}
            or re.fullmatch(r'(COM|LPT)[1-9¹²³]', stem)
            or len(name.encode('utf-16-le')) // 2 > 255):
        raise ValueError(f'invalid Windows name: {name}')


def no_link(path):
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
        raise ValueError(f'links/reparse points forbidden: {path}')
    return info


def safe_path(path):
    # Check ancestors too: resolve() alone would hide a junction or symlink.
    for ancestor in (*reversed(path.parents), path):
        if ancestor.exists() or ancestor.is_symlink():
            no_link(ancestor)
    return path.resolve()


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def generate(dist, version, out):
    validate_version(version)
    dist = safe_path(Path(os.path.abspath(dist)))
    out = safe_path(Path(os.path.abspath(out)))
    if dist == out or dist in out.parents or out in dist.parents:
        raise ValueError('input/output overlap forbidden')
    if not dist.is_dir():
        raise ValueError('payload must be a directory')
    package = ET.parse(AUTHORING).getroot().find(f'{{{NS}}}Package')
    upgrade_code = package.attrib['UpgradeCode']  # Single authored source of truth.
    namespace = uuid.UUID(upgrade_code)
    seen, files, directories, empty = {}, [], [], []
    def walk_error(error):
        raise error

    for folder, dirs, names in os.walk(dist, followlinks=False, onerror=walk_error):
        base = Path(folder)
        if base != dist and not dirs and not names:
            empty.append(base.relative_to(dist).as_posix())
        for name in dirs + names:
            validate_name(name)
            path = base / name
            info = no_link(path)
            if not path.resolve().is_relative_to(dist):
                raise ValueError(f'escaping path: {path}')
            rel = path.relative_to(dist).as_posix()
            canonical = key(rel)
            if canonical in seen:
                raise ValueError(f'case/Unicode collision: {seen[canonical]} and {rel}')
            seen[canonical] = rel
            if stat.S_ISDIR(info.st_mode):
                directories.append(rel)
            elif stat.S_ISREG(info.st_mode):
                files.append(rel)
            else:
                raise ValueError(f'not a regular payload file: {rel}')
    if 'Annotshot.exe' not in files:
        raise ValueError('no top-level Annotshot.exe')
    if any(key(rel) == key('check.txt') for rel in files):
        raise ValueError('dirty top-level check.txt receipt')
    if out.exists():
        for item in out.iterdir():
            info = no_link(item)
            if not stat.S_ISREG(info.st_mode):
                raise ValueError('non-file output contents forbidden')
        contents = {p.name for p in out.iterdir()}
        if contents and (not (out / MARKER).is_file() or
                         (out / MARKER).read_text() != MARKER_TEXT):
            raise ValueError('output lacks ownership marker')
        if contents - OWNED or any(not p.is_file() for p in out.iterdir()):
            raise ValueError('unrelated output contents forbidden')
    root = ET.Element(f'{{{NS}}}Wix')
    fragment = element(root, 'Fragment')
    element(fragment, 'Icon', Id='AnnotshotIcon.exe', SourceFile=str(dist / 'Annotshot.exe').replace('$', '$$'))
    install = element(fragment, 'DirectoryRef', Id='INSTALLFOLDER')
    nodes = {'': install}
    ids = set()

    def stable_id(prefix, canonical):
        value = ident(prefix, canonical)
        if value in ids:
            raise ValueError('generated ID collision')
        ids.add(value)
        return value

    for rel in sorted(directories, key=lambda r: (r.count('/'), key(r))):
        parent = rel.rpartition('/')[0]
        nodes[rel] = element(nodes[parent], 'Directory', Id=stable_id('D', key(rel)), Name=rel.split('/')[-1].replace('$', '$$'))
    records, components = [], []
    for rel in sorted(files, key=key):
        canonical = key(rel)
        cid, fid = stable_id('C', canonical), stable_id('F', canonical)
        component_guid = guid(namespace, 'file|x64|' + canonical)
        component = element(nodes[rel.rpartition('/')[0]], 'Component', Id=cid, Guid=component_guid, Bitness='always64')
        # WiX preprocessor escaping is separate from XML escaping.
        element(component, 'File', Id=fid, Name=rel.split('/')[-1].replace('$', '$$'),
                Source=str(dist / rel).replace('$', '$$'), KeyPath='yes')
        components.append(cid)
        records.append(dict(path=rel, canonical_key=canonical, sha256=sha(dist / rel),
                            file_id=fid, component_id=cid, guid=component_guid))
    empty_records = []
    for rel in sorted(empty, key=key):
        cid = stable_id('C', 'directory|' + key(rel))
        component_guid = guid(namespace, 'directory|x64|' + key(rel))
        component = element(nodes[rel], 'Component', Id=cid, Guid=component_guid, Bitness='always64', KeyPath='yes')
        element(component, 'CreateFolder')
        element(component, 'RemoveFolder', Id=stable_id('D', 'remove|' + key(rel)), On='uninstall')
        components.append(cid)
        empty_records.append(dict(path=rel, component_id=cid, guid=component_guid))
    group = element(fragment, 'ComponentGroup', Id='PayloadComponents')
    for cid in components:
        element(group, 'ComponentRef', Id=cid)
    metadata = dict(name='Annotshot', manufacturer='Bill Moldestad', architecture='x64',
                    version=version, product_code=guid(namespace, 'product|x64|' + version),
                    upgrade_code=upgrade_code)
    definitions = ET.Element(f'{{{NS}}}Include')
    values = dict(ProductVersion=version, ProductCode=metadata['product_code'],
                  AssociationsGuid=guid(namespace, 'registry|x64|associations'),
                  ShortcutGuid=guid(namespace, 'shortcut|x64|startmenu'))
    for name, value in values.items():
        # Definitions contain only validated version numbers and generated GUIDs.
        escaped = value.replace('&', '&amp;').replace('"', '&quot;').replace('<', '&lt;').replace('>', '&gt;')
        definitions.append(ET.ProcessingInstruction('define', f'{name}="{escaped}"'))
    manifest = dict(product=metadata, source_root=str(dist), files=records,
                    empty_directories=empty_records,
                    non_file_components=dict(Associations=values['AssociationsGuid'], StartMenuShortcut=values['ShortcutGuid']))
    # All input and ownership checks precede any output creation or replacement.
    guids = [record['guid'] for record in records + empty_records] + list(manifest['non_file_components'].values())
    if len(guids) != len(set(guids)):
        raise ValueError('generated GUID collision')
    out.mkdir(parents=True, exist_ok=True)
    (out / MARKER).write_text(MARKER_TEXT, encoding='utf-8')
    ET.indent(root)
    ET.ElementTree(root).write(out / 'Payload.wxs', encoding='utf-8', xml_declaration=True)
    ET.ElementTree(definitions).write(out / 'Identity.wxi', encoding='utf-8', xml_declaration=True)
    (out / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    for name in ('version', 'product_code', 'upgrade_code'):
        print(f'{name}: {metadata[name]}')
    return manifest


def verify_sources(manifest_path):
    manifest = json.loads(Path(manifest_path).read_text(encoding='utf-8'))
    root = Path(manifest['source_root'])
    for record in manifest['files']:
        path = root / record['path']
        no_link(path)
        if sha(path) != record['sha256']:
            raise ValueError(f'source bytes changed: {record["path"]}')
    print('signed source hashes unchanged')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dist')
    parser.add_argument('--version')
    parser.add_argument('--out')
    parser.add_argument('--verify-sources', metavar='MANIFEST')
    args = parser.parse_args(argv)
    try:
        if args.verify_sources:
            verify_sources(args.verify_sources)
        else:
            if not all((args.dist, args.version, args.out)):
                raise ValueError('--dist, --version and --out required')
            generate(args.dist, args.version, args.out)
    except (OSError, ValueError, ET.ParseError) as error:
        print(f'STOP {error}')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
