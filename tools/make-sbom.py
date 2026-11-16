#!/usr/bin/env python3
"""Describe the libraries and files actually present in an Annotshot frozen build."""
import argparse
import base64
import binascii
from datetime import datetime, timezone
import hashlib
from importlib import metadata
import json
from pathlib import Path, PurePosixPath
import platform
import re
import sys
import sysconfig
from urllib.parse import quote
import uuid
import zipfile


# PyInstaller relocates site-packages contents under these collection roots.
COLLECTION_ROOTS = ('', '_internal/', 'Contents/Frameworks/',
                    'Contents/Resources/', 'Contents/MacOS/')
BOOTSTRAP = {'_pyi_rth_utils', 'pyiboot01_bootstrap', 'pyimod01_archive', 'pyimod02_importers',
             'pyimod03_ctypes', 'pyimod04_pywin32'}
BINARY_SUFFIXES = {'.dll', '.pyd', '.so', '.dylib', '.exe'}
MAGICS = {b'\x7fELF', b'\xfe\xed\xfa\xce', b'\xce\xfa\xed\xfe',
          b'\xfe\xed\xfa\xcf', b'\xcf\xfa\xed\xfe', b'\xca\xfe\xba\xbe',
          b'\xbe\xba\xfe\xca', b'\xca\xfe\xba\xbf', b'\xbf\xba\xfe\xca'}


def archive_modules(exe):
    """Read both CArchive scripts/modules and the embedded PYZ module index."""
    from PyInstaller.archive.readers import CArchiveReader
    archive = CArchiveReader(str(exe))
    modules = set()
    for name, entry in archive.toc.items():
        kind = entry[-1]
        if kind == 'z':
            modules.update(archive.open_embedded_archive(name).toc)
        elif kind in {'s', 'm', 'M'}:
            modules.add(name)
    return modules


def normalized(name):
    return re.sub(r'[-_.]+', '-', name).lower()


def relative_path(value):
    """Metadata paths may use either separator; never emit an absolute path."""
    text = str(value).replace('\\', '/')
    path = PurePosixPath(text)
    if path.is_absolute() or '..' in path.parts or re.match(r'^[A-Za-z]:', text):
        return None
    return path.as_posix()


def payload_paths(rel):
    paths = {rel[len(root):] for root in COLLECTION_ROOTS if rel.startswith(root)}
    return paths | {path.replace('__dot__', '.') for path in paths}


def bundle_files(bundle):
    """Skip aliases, and reject links that escape the bundle before reading it."""
    root = bundle.resolve()
    files, links = [], 0
    for path in sorted(bundle.rglob('*'), key=lambda p: p.relative_to(bundle).as_posix()):
        if path.is_symlink():
            if not path.resolve().is_relative_to(root):
                raise ValueError('symbolic link points outside bundle: ' +
                                 path.relative_to(bundle).as_posix())
            links += 1
            continue
        if path.is_file():
            files.append(path)
    return files, links


def distribution_licenses(info):
    expression = info.get('License-Expression', '').strip()
    if expression:
        return [{'expression': expression}]
    license_text = info.get('License', '').strip()
    if license_text:
        return [{'license': {'name': license_text}}]
    classifiers = sorted({value for value in info.get_all('Classifier', [])
                          if value.startswith('License ::')})
    return [{'license': {'name': value}} for value in classifiers]


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def file_component(path, rel, **extra):
    return dict(type='file', name=rel, **{'bom-ref': 'file:' + quote(rel, safe='/')},
                hashes=[{'alg': 'SHA-256', 'content': sha256(path)}], **extra)


def binary(path):
    if (path.suffix.lower() in BINARY_SUFFIXES
            or re.search(r'\.so(?:\.\d+)+$', path.name.lower())):
        return True
    with path.open('rb') as stream:
        magic = stream.read(4)
        if magic in MAGICS:
            return True
        if magic[:2] == b'MZ':
            stream.seek(0x3c)
            offset = stream.read(4)
            if len(offset) == 4:
                stream.seek(int.from_bytes(offset, 'little'))
                return stream.read(4) == b'PE\0\0'
    return False


def stdlib_extension_dir():
    if sys.platform == 'win32':
        return Path(sys.base_prefix) / 'DLLs'
    return Path(sysconfig.get_path('platstdlib')) / 'lib-dynload'


def stdlib_extension(path):
    original = stdlib_extension_dir() / path.name
    return original.is_file() and sha256(path) == sha256(original)


def record_matches(path, record_hash):
    """Accept only a usable strong RECORD digest, verified against these bytes."""
    if record_hash is None or record_hash.mode not in {'sha256', 'sha384', 'sha512'}:
        return False
    value = record_hash.value
    if not re.fullmatch(r'[A-Za-z0-9_-]+={0,2}', value):
        return False
    try:
        expected = base64.b64decode(value + '=' * (-len(value) % 4),
                                    altchars=b'-_', validate=True)
    except (ValueError, binascii.Error):
        return False
    digest = hashlib.new(record_hash.mode)
    if len(expected) != digest.digest_size:
        return False
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.digest() == expected


def qt_version():
    from PySide6.QtCore import qVersion
    return qVersion()


def app_version():
    # Script execution puts tools/, rather than the project root, on sys.path.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from annotshot import __version__
    return __version__


def generate(bundle, exe, label, out):
    bundle, exe, out = Path(bundle), Path(exe), Path(out)
    if not bundle.is_dir():
        raise ValueError('bundle directory and executable required')
    files, skipped_links = bundle_files(bundle)
    if not exe.is_file():
        raise ValueError('bundle directory and executable required')
    if not exe.resolve().is_relative_to(bundle.resolve()):
        raise ValueError('executable must be inside the bundle')
    if out.resolve().is_relative_to(bundle.resolve()):
        raise ValueError('output must be outside the bundle')
    files = [path for path in files if not path.samefile(exe)]
    modules = archive_modules(exe)
    # base_library.zip is a separate frozen archive on onedir builds.
    for path in files:
        if path.name == 'base_library.zip':
            with zipfile.ZipFile(path) as archive:
                modules.update(name[:-4].replace('/', '.') for name in archive.namelist()
                               if name.endswith('.pyc'))
    tops = {name.split('.')[0] for name in modules}
    owners = metadata.packages_distributions()
    distributions = {}
    file_owners = {}
    for dist in metadata.distributions():
        name = dist.metadata.get('Name')
        if not name:
            raise ValueError('installed distribution has no Name metadata')
        key = normalized(name)
        distributions[key] = dist
        for item in dist.files or ():
            rel = relative_path(item)
            if rel:
                file_owners.setdefault(rel, {}).setdefault(key, []).append(
                    getattr(item, 'hash', None))
    selected, unaccounted = set(), []
    for top in sorted(tops):
        if (top in {'annotshot', 'annotshot_entry'} or top in sys.stdlib_module_names
                or top.startswith('_sysconfigdata_')
                or top in BOOTSTRAP or top.startswith('pyi_rth_')):
            continue
        names = {normalized(name) for name in owners.get(top, [])}
        if not names or names - distributions.keys():
            unaccounted.append(top)
        else:
            selected.update(names)
    if unaccounted:
        raise ValueError('unaccounted modules: ' + ', '.join(unaccounted))
    file_components = []
    binary_count = verified_count = stdlib_count = 0
    for path in files:
        rel = path.relative_to(bundle).as_posix()
        found = {}
        for candidate in payload_paths(rel):
            for key, hashes in file_owners.get(candidate, {}).items():
                found.setdefault(key, []).extend(hashes)
        evidence = None
        owner = 'not owned by an installed Python package'
        if len(found) > 1:
            owner = 'ambiguous: ' + ', '.join(sorted(found))
        elif found:
            key, hashes = next(iter(found.items()))
            if any(record_matches(path, digest) for digest in hashes):
                selected.add(key)
                owner = 'verified: ' + key
            else:
                evidence = f'path matches {key}; bytes not verified'
        is_binary = binary(path)
        if is_binary and not found and stdlib_extension(path):
            owner = 'stdlib (bytes match the build interpreter)'
        extra = {}
        if path.name == 'VT323-Regular.ttf':
            extra['licenses'] = [{'license': {'id': 'OFL-1.1'}}]
        if is_binary:
            binary_count += 1
            verified_count += owner.startswith('verified: ')
            stdlib_count += owner.startswith('stdlib ')
        if is_binary or evidence is not None or len(found) > 1:
            properties = [{'name': 'annotshot:owner', 'value': owner}]
            if evidence:
                properties.append({'name': 'annotshot:owner-evidence', 'value': evidence})
            extra['properties'] = properties
        if extra:
            file_components.append(file_component(path, rel, **extra))
    if not any(path.name == 'VT323-Regular.ttf' for path in files):
        raise ValueError('bundle has no VT323-Regular.ttf')
    components = []
    for key in sorted(selected):
        dist = distributions[key]
        name, version = dist.metadata['Name'], dist.version
        purl = f'pkg:pypi/{key}@{quote(version, safe="")}'
        component = {'type': 'library', 'name': name, 'version': version,
                     'purl': purl, 'bom-ref': purl}
        licenses = distribution_licenses(dist.metadata)
        if licenses:
            component['licenses'] = licenses
        components.append(component)
    library_count = len(components)
    components.extend([
        {'type': 'framework', 'name': 'Qt', 'version': qt_version(), 'bom-ref': 'framework:qt',
         'licenses': [{'license': {'id': 'LGPL-3.0-only'}}],
         'properties': [{'name': 'annotshot:bundled', 'value': 'ships inside the PySide6 wheels'}]},
        {'type': 'library', 'name': 'CPython', 'version': platform.python_version(),
         'bom-ref': 'runtime:cpython', 'licenses': [{'license': {'id': 'PSF-2.0'}}]},
        *file_components,
    ])
    components.sort(key=lambda component: component['name'])
    bom = {'bomFormat': 'CycloneDX', 'specVersion': '1.5',
           'serialNumber': 'urn:uuid:' + str(uuid.uuid4()), 'version': 1,
           'metadata': {'timestamp': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                        'properties': [{'name': 'annotshot:version-source',
                                        'value': 'read from the build environment in the same job, right after the build; not re-verified against the bundle\'s bytes'}],
                        'component': {'type': 'application', 'name': 'Annotshot',
                                      'version': app_version(), 'licenses': [{'license': {'id': 'MIT'}}],
                                      'properties': [{'name': 'annotshot:build', 'value': label}]}},
           'components': components}
    out.write_text(json.dumps(bom, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    unowned_count = binary_count - verified_count - stdlib_count
    print(f'SBOM: {library_count} libraries, {binary_count} binary files '
          f'({verified_count} verified, {stdlib_count} stdlib, {unowned_count} not owned), '
          f'{len(components)} total components, {skipped_links} links skipped')
    return bom


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', required=True)
    parser.add_argument('--exe', required=True)
    parser.add_argument('--label', choices=('windows', 'macos', 'linux'), required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args(argv)
    try:
        generate(args.bundle, args.exe, args.label, args.out)
    except Exception as error:
        print(f'STOP {error}')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
