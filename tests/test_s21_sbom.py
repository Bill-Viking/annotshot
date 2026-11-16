"""Frozen inventory and additive release-workflow contracts, without a build."""
import base64
from email.message import Message
import hashlib
import importlib.util
from importlib.metadata import PackagePath
import json
from pathlib import Path
import re
import sys
from types import ModuleType, SimpleNamespace
import uuid
import zipfile

import pytest

ROOT = Path(__file__).resolve().parent.parent
STEP = 'Parts list (CycloneDX SBOM)'
# Freeze every existing workflow byte, including the surrounding steps. These
# constants never depend on HEAD or on whether a change has been committed.
EXPECTED_WORKFLOW_SHA256 = {
    'build-windows.yml': 'f5ff37bc302fd2ada7f210565165ed73b5eddf922fe9d037ece7f7b486491323',
    'release.yml': '34b6c55a472a401e9cbe03533ba6966a6a259c56fa4d0c63a912d2919ca562a3',
}


@pytest.fixture
def tool(monkeypatch):
    spec = importlib.util.spec_from_file_location('sbom_tool', ROOT / 'tools/make-sbom.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'qt_version', lambda: '6.12.0')
    monkeypatch.setattr(module, 'app_version', lambda: '0.4.2')
    return module


def distribution(name, files=(), **fields):
    info = Message()
    info['Name'] = name
    for key, value in fields.items():
        for item in value if isinstance(value, list) else [value]:
            info[key.replace('_', '-')] = item
    return SimpleNamespace(metadata=info, version='1.2.3', files=list(files))


def record_file(name, content, mode='sha256', padded=False):
    item = PackagePath(name)
    value = base64.urlsafe_b64encode(hashlib.new(mode, content).digest()).decode('ascii')
    item.hash = SimpleNamespace(mode=mode, value=value if padded else value.rstrip('='))
    return item


@pytest.fixture
def frozen(tmp_path, monkeypatch, tool):
    bundle = tmp_path / 'bundle'
    bundle.mkdir()
    exe = bundle / 'Annotshot.exe'
    exe.write_bytes(b'fake executable')
    font = bundle / '_internal' / 'annotshot' / 'fonts' / 'VT323-Regular.ttf'
    font.parent.mkdir(parents=True)
    font.write_bytes(b'font bytes')
    data = bundle / '_internal' / 'data_only' / 'payload.dat'
    data.parent.mkdir()
    data.write_bytes(b'package data')
    binary = bundle / '_internal' / 'unknown.dll'
    binary.write_bytes(b'binary bytes')
    owned = bundle / '_internal' / 'sample' / 'native.so'
    owned.parent.mkdir()
    owned.write_bytes(b'owned binary')
    (bundle / '_internal' / '_ssl.so').write_bytes(b'stdlib extension')
    with zipfile.ZipFile(bundle / '_internal' / 'base_library.zip', 'w') as archive:
        archive.writestr('encodings/__init__.pyc', b'fake bytecode')
    dists = [distribution('Sample_Lib', [record_file('sample/native.so', b'owned binary')], License_Expression='MIT OR Apache-2.0'),
             distribution('Data-Only', [record_file('data_only/payload.dat', b'package data')], License='Own licence'),
             distribution('pytest'), distribution('PyInstaller'), distribution('pip')]
    monkeypatch.setattr(tool.metadata, 'distributions', lambda: dists)
    monkeypatch.setattr(tool.metadata, 'packages_distributions', lambda: {'sample': ['Sample_Lib']})
    modules = {'sample', 'sample.child', 'annotshot', 'json', '_struct', '_pyi_rth_utils.qt'}
    # Exercise the real archive traversal through a fake PyInstaller reader.
    reader_module = ModuleType('PyInstaller.archive.readers')

    class Reader:
        def __init__(self, path):
            assert Path(path) == exe
            self.toc = {'PYZ.pyz': (0, 0, 0, 0, 'z'),
                        'annotshot_entry': (0, 0, 0, 0, 's'),
                        'pyiboot01_bootstrap': (0, 0, 0, 0, 's'),
                        'pyi_rth_pyside6': (0, 0, 0, 0, 's')}

        def open_embedded_archive(self, name):
            assert name == 'PYZ.pyz'
            return SimpleNamespace(toc=dict.fromkeys(modules))

    reader_module.CArchiveReader = Reader
    monkeypatch.setitem(sys.modules, 'PyInstaller', ModuleType('PyInstaller'))
    monkeypatch.setitem(sys.modules, 'PyInstaller.archive', ModuleType('PyInstaller.archive'))
    monkeypatch.setitem(sys.modules, 'PyInstaller.archive.readers', reader_module)
    out = tmp_path / 'parts.cdx.json'
    args = ['--bundle', str(bundle), '--exe', str(exe), '--label', 'windows', '--out', str(out)]
    return SimpleNamespace(bundle=bundle, exe=exe, font=font, binary=binary, out=out,
                           args=args, modules=modules, dists=dists)


def test_frozen_inventory_and_cyclonedx(tool, frozen, capsys):
    assert tool.main(frozen.args) == 0
    text = frozen.out.read_text(encoding='utf-8')
    bom = json.loads(text)
    assert set(bom) == {'bomFormat', 'specVersion', 'serialNumber', 'version', 'metadata', 'components'}
    assert bom['bomFormat'] == 'CycloneDX' and bom['specVersion'] == '1.5' and bom['version'] == 1
    uuid.UUID(bom['serialNumber'].removeprefix('urn:uuid:'))
    assert bom['metadata']['timestamp'].endswith('+00:00')
    assert bom['metadata']['properties'] == [{
        'name': 'annotshot:version-source',
        'value': "read from the build environment in the same job, right after the build; not re-verified against the bundle's bytes"}]
    app = bom['metadata']['component']
    assert app == {'type': 'application', 'name': 'Annotshot', 'version': '0.4.2',
                   'licenses': [{'license': {'id': 'MIT'}}],
                   'properties': [{'name': 'annotshot:build', 'value': 'windows'}]}
    components = bom['components']
    assert [c['name'] for c in components] == sorted(c['name'] for c in components)
    assert len({c['bom-ref'] for c in components}) == len(components)
    by_name = {c['name']: c for c in components}
    sample = by_name['Sample_Lib']
    assert sample['type'] == 'library'
    assert sample['purl'] == sample['bom-ref'] == 'pkg:pypi/sample-lib@1.2.3'
    assert sample['version'] == '1.2.3'
    assert sample['licenses'] == [{'expression': 'MIT OR Apache-2.0'}]
    assert by_name['Data-Only']['licenses'] == [{'license': {'name': 'Own licence'}}]
    assert not {'pytest', 'PyInstaller', 'pip'} & by_name.keys()
    unknown = by_name['_internal/unknown.dll']
    assert unknown['type'] == 'file'
    assert unknown['hashes'] == [{'alg': 'SHA-256', 'content': hashlib.sha256(b'binary bytes').hexdigest()}]
    assert unknown['properties'] == [{'name': 'annotshot:owner', 'value': 'not owned by an installed Python package'}]
    assert properties(by_name['_internal/_ssl.so'])['annotshot:owner'] == UNOWNED
    assert properties(by_name['_internal/sample/native.so'])['annotshot:owner'] == 'verified: sample-lib'
    font = by_name['_internal/annotshot/fonts/VT323-Regular.ttf']
    assert font['licenses'] == [{'license': {'id': 'OFL-1.1'}}]
    assert font['hashes'][0]['content'] == hashlib.sha256(b'font bytes').hexdigest()
    assert by_name['Qt']['type'] == 'framework' and by_name['Qt']['version'] == '6.12.0'
    assert by_name['Qt']['licenses'] == [{'license': {'id': 'LGPL-3.0-only'}}]
    assert 'PySide6 wheels' in by_name['Qt']['properties'][0]['value']
    assert by_name['CPython']['version'] == tool.platform.python_version()
    assert by_name['CPython']['licenses'] == [{'license': {'id': 'PSF-2.0'}}]
    assert str(frozen.bundle.parent) not in text
    assert frozen.bundle.parent.as_posix() not in text
    for component in components:
        assert not Path(component['name']).is_absolute()
    assert capsys.readouterr().out == 'SBOM: 2 libraries, 3 binary files (1 verified, 0 stdlib, 2 not owned), 8 total components, 0 links skipped\n'
    assert tool.main(frozen.args) == 0
    again = json.loads(frozen.out.read_text(encoding='utf-8'))
    for key in ('serialNumber',):
        bom.pop(key)
        again.pop(key)
    bom['metadata'].pop('timestamp')
    again['metadata'].pop('timestamp')
    assert bom == again


def test_unaccounted_modules_stop_without_output(tool, frozen, capsys):
    frozen.modules.update({'missing_one.child', 'missing_two'})
    assert tool.main(frozen.args) == 1
    assert capsys.readouterr().out == 'STOP unaccounted modules: missing_one, missing_two\n'
    assert not frozen.out.exists()


def add_file(frozen, rel, content=b'binary bytes'):
    path = frozen.bundle / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def inventory(tool, frozen):
    assert tool.main(frozen.args) == 0
    return {c['name']: c for c in json.loads(frozen.out.read_text(encoding='utf-8'))['components']}


def symlink_or_skip(link, target):
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        link.symlink_to(target, target_is_directory=target.is_dir())
    except (OSError, NotImplementedError) as error:
        pytest.skip(f'symlinks unavailable: {error}')


def test_platform_sysconfigdata_is_runtime_only(tool, frozen, capsys):
    frozen.modules.add('_sysconfigdata__darwin_darwin')
    assert tool.main(frozen.args) == 0
    frozen.out.unlink()
    capsys.readouterr()
    # The prefix must include its final underscore; no broader allowance.
    frozen.modules.add('_sysconfigdata')
    assert tool.main(frozen.args) == 1
    assert capsys.readouterr().out == 'STOP unaccounted modules: _sysconfigdata\n'
    assert not frozen.out.exists()


def test_bundle_links_are_skipped_without_duplicate_files(tool, frozen, capsys):
    rel = 'Contents/Frameworks/libssl.3.dylib'
    real = add_file(frozen, rel, b'ssl runtime')
    symlink_or_skip(frozen.bundle / 'Contents/Resources/libssl.3.dylib', real)
    symlink_or_skip(frozen.bundle / 'Contents/MacOS/libssl.3.dylib', real)
    # A directory alias must not be traversed, either.
    symlink_or_skip(frozen.bundle / 'Contents/Resources/frameworks', real.parent)
    by_name = inventory(tool, frozen)
    ssl = [c for c in by_name.values() if c['name'].endswith('libssl.3.dylib')]
    assert [c['name'] for c in ssl] == [rel]
    assert ssl[0]['hashes'][0]['content'] == hashlib.sha256(b'ssl runtime').hexdigest()
    assert capsys.readouterr().out == 'SBOM: 2 libraries, 4 binary files (1 verified, 0 stdlib, 3 not owned), 9 total components, 3 links skipped\n'


@pytest.mark.parametrize('kind', ['file', 'directory', 'missing', 'executable', 'missing-executable'])
def test_external_bundle_link_stops_before_reading(tool, frozen, capsys, kind):
    target = frozen.bundle.parent / 'outside'
    if kind == 'directory':
        target.mkdir()
    elif kind in {'file', 'executable'}:
        target.write_bytes(b'outside data')
    rel = 'Contents/Resources/libssl.3.dylib'
    if kind in {'executable', 'missing-executable'}:
        frozen.exe.unlink()
        rel = frozen.exe.relative_to(frozen.bundle).as_posix()
    symlink_or_skip(frozen.bundle / rel, target)
    assert tool.main(frozen.args) == 1
    assert capsys.readouterr().out == f'STOP symbolic link points outside bundle: {rel}\n'
    assert not frozen.out.exists()


@pytest.mark.parametrize('rel', ['Contents/MacOS/Annotshot', 'Annotshot.exe'])
def test_application_executable_is_never_a_component(tool, frozen, monkeypatch, rel):
    # Both a Mach-O magic and an executable suffix exercise binary payloads.
    exe = add_file(frozen, rel, b'\xcf\xfa\xed\xfeapplication')
    monkeypatch.setattr(tool, 'archive_modules', lambda path: frozen.modules)
    frozen.args[frozen.args.index('--exe') + 1] = str(exe)
    # Even a matching metadata path must not select an application owner.
    frozen.dists.append(distribution('Not-An-App-Dependency', [rel]))
    by_name = inventory(tool, frozen)
    assert rel not in by_name and 'Not-An-App-Dependency' not in by_name


UNOWNED = 'not owned by an installed Python package'


def properties(component):
    return {p['name']: p['value'] for p in component['properties']}


@pytest.mark.parametrize('name', ['json.so', '_ssl.pyd'])
def test_stdlib_name_without_matching_bytes_is_unowned(tool, frozen, monkeypatch, tmp_path, name):
    originals = tmp_path / 'lib-dynload'
    originals.mkdir()
    (originals / name).write_bytes(b'interpreter bytes')
    monkeypatch.setattr(tool, 'stdlib_extension_dir', lambda: originals)
    rel = 'vendor/' + name
    add_file(frozen, rel, b'vendor bytes')
    component = inventory(tool, frozen)[rel]
    assert properties(component)['annotshot:owner'] == UNOWNED
    assert component['hashes'][0]['content'] == hashlib.sha256(b'vendor bytes').hexdigest()


def test_real_stdlib_extension_copy_is_listed_with_byte_evidence(tool, frozen, capsys, monkeypatch):
    folder = tool.stdlib_extension_dir()
    original = next((p for p in sorted(folder.glob('*'))
                     if p.is_file() and p.suffix.lower() in {'.so', '.pyd'}), None)
    if original is None:
        # Some venvs leave platstdlib/lib-dynload empty. Still exercise real
        # native bytes, with the lookup folder supplied by this test fixture.
        spec = importlib.util.find_spec('_ssl')
        if spec and spec.origin and Path(spec.origin).is_file():
            original = Path(spec.origin)
            monkeypatch.setattr(tool, 'stdlib_extension_dir', lambda: original.parent)
    if original is None:
        pytest.skip('interpreter has no native standard-library extension to copy')
    rel = 'arbitrary/deep/' + original.name
    content = original.read_bytes()
    add_file(frozen, rel, content)
    component = inventory(tool, frozen)[rel]
    assert properties(component)['annotshot:owner'] == 'stdlib (bytes match the build interpreter)'
    assert component['hashes'][0]['content'] == hashlib.sha256(content).hexdigest()
    assert capsys.readouterr().out == ('SBOM: 2 libraries, 4 binary files '
        '(1 verified, 1 stdlib, 2 not owned), 9 total components, 0 links skipped\n')


@pytest.mark.parametrize('platform', ['win32', 'darwin', 'linux'])
def test_stdlib_extension_folder_comes_from_running_interpreter(tool, monkeypatch, tmp_path, platform):
    monkeypatch.setattr(tool.sys, 'platform', platform)
    monkeypatch.setattr(tool.sys, 'base_prefix', str(tmp_path / 'base'))
    monkeypatch.setattr(tool.sysconfig, 'get_path', lambda name: str(tmp_path / name))
    expected = tmp_path / ('base/DLLs' if platform == 'win32' else 'platstdlib/lib-dynload')
    assert tool.stdlib_extension_dir() == expected


def test_pyinstaller_dot_rename_selects_owner_by_verified_path(tool, frozen):
    rels = ['PIL/__dot__dylibs/libtiff.6.dylib',
            'PIL/__dot__dylibs/version__dot__1/libtiff.6.dylib']
    for rel in rels:
        add_file(frozen, 'Contents/Frameworks/' + rel)
    frozen.dists.append(distribution('pillow', [
        record_file(rel.replace('__dot__', '.'), b'binary bytes') for rel in rels]))
    by_name = inventory(tool, frozen)
    assert by_name['pillow']['type'] == 'library'
    for rel in rels:
        assert properties(by_name['Contents/Frameworks/' + rel])['annotshot:owner'] == 'verified: pillow'


@pytest.mark.parametrize('selected', [False, True])
def test_foreign_basename_never_proves_ownership(tool, frozen, monkeypatch, selected):
    rel = 'foreign/common.dll'
    add_file(frozen, rel)
    frozen.dists.append(distribution('Vendor', [record_file('vendor/common.dll', b'binary bytes')]))
    if selected:
        frozen.modules.add('vendor')
        monkeypatch.setattr(tool.metadata, 'packages_distributions', lambda: {
            'sample': ['Sample_Lib'], 'vendor': ['Vendor']})
    by_name = inventory(tool, frozen)
    assert properties(by_name[rel])['annotshot:owner'] == UNOWNED
    assert ('Vendor' in by_name) == selected


@pytest.mark.parametrize('digest', ['changed', 'missing', 'unsupported', 'invalid', 'short'])
@pytest.mark.parametrize('rel', ['vendor/native.dll', 'vendor/payload.dat'])
def test_record_path_without_verified_bytes_lists_file_and_selects_nothing(tool, frozen, digest, rel):
    content = b'final signed or rewritten bytes'
    add_file(frozen, '_internal/' + rel, content)
    item = record_file(rel, b'wheel bytes')
    if digest == 'missing':
        item = rel
    elif digest == 'unsupported':
        item.hash.mode = 'md5'
    elif digest == 'invalid':
        item.hash.value = '!not-base64!'
    elif digest == 'short':
        item.hash.value = 'YQ'
    frozen.dists.append(distribution('Vendor', [item]))
    by_name = inventory(tool, frozen)
    assert 'Vendor' not in by_name
    component = by_name['_internal/' + rel]
    assert properties(component) == {'annotshot:owner': UNOWNED,
        'annotshot:owner-evidence': 'path matches vendor; bytes not verified'}
    assert component['hashes'][0]['content'] == hashlib.sha256(content).hexdigest()


@pytest.mark.parametrize('rel', ['vendor/common.dll', 'vendor/payload.dat'])
def test_all_installed_distributions_compete_for_path_even_when_one_digest_matches(tool, frozen, rel):
    add_file(frozen, '_internal/' + rel)
    frozen.dists.extend([distribution('B', [rel]),
                         distribution('A', [record_file(rel, b'binary bytes')])])
    by_name = inventory(tool, frozen)
    assert not {'A', 'B'} & by_name.keys()
    assert properties(by_name['_internal/' + rel]) == {'annotshot:owner': 'ambiguous: a, b'}


@pytest.mark.parametrize('mode', ['sha256', 'sha384', 'sha512'])
@pytest.mark.parametrize('padded', [False, True])
def test_record_path_and_digest_verify_and_select_owner(tool, frozen, mode, padded):
    rel = 'vendor/native.dll'
    add_file(frozen, '_internal/' + rel)
    frozen.dists.append(distribution('Vendor', [record_file(rel, b'binary bytes', mode, padded)]))
    by_name = inventory(tool, frozen)
    assert by_name['Vendor']['type'] == 'library'
    assert properties(by_name['_internal/' + rel]) == {'annotshot:owner': 'verified: vendor'}


def test_bundled_build_tools_are_listed_only_when_present(tool, frozen):
    for name in ('pytest', 'PyInstaller', 'pip'):
        data = frozen.bundle / '_internal' / (name + '.dist-info') / 'METADATA'
        data.parent.mkdir()
        data.write_text('package metadata', encoding='utf-8')
        next(d for d in frozen.dists if d.metadata['Name'] == name).files.append(record_file(name + '.dist-info/METADATA', b'package metadata'))
    assert tool.main(frozen.args) == 0
    components = json.loads(frozen.out.read_text(encoding='utf-8'))['components']
    assert {'pytest', 'PyInstaller', 'pip'} <= {c['name'] for c in components}
    assert all('licenses' not in c for c in components if c['name'] in {'pytest', 'PyInstaller', 'pip'})


@pytest.mark.parametrize('root', ['', '_internal/', 'Contents/Resources/', 'Contents/Frameworks/', 'Contents/MacOS/'])
def test_relocated_file_ownership(tool, frozen, root):
    path = frozen.bundle / root / 'data_only' / 'extra.dll'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'library')
    frozen.dists[1].files.append(record_file('data_only/extra.dll', b'library'))
    assert tool.main(frozen.args) == 0
    components = json.loads(frozen.out.read_text(encoding='utf-8'))['components']
    component = next(c for c in components if c['name'] == root + 'data_only/extra.dll')
    assert properties(component)['annotshot:owner'] == 'verified: data-only'


@pytest.mark.parametrize('name,content', [('other.pyd', b'pyd'), ('other.so', b'so'),
    ('other.dylib', b'dylib'), ('other.so.6.12', b'versioned so'), ('elf', b'\x7fELFpayload'), ('helper.bin', b'\x7fELFpayload'), ('helper.exe', b'MZ'), ('macho', b'\xcf\xfa\xed\xfepayload'),
    ('plain', b'text')])
def test_binary_detection(tool, frozen, name, content):
    path = frozen.bundle / name
    path.write_bytes(content)
    assert tool.main(frozen.args) == 0
    components = json.loads(frozen.out.read_text(encoding='utf-8'))['components']
    found = next((c for c in components if c['name'] == name), None)
    assert (found is not None) == (name != 'plain')
    if found:
        assert found['hashes'][0]['content'] == hashlib.sha256(content).hexdigest()


@pytest.mark.parametrize('magic', sorted({b'\x7fELF', b'\xfe\xed\xfa\xce', b'\xce\xfa\xed\xfe',
    b'\xfe\xed\xfa\xcf', b'\xcf\xfa\xed\xfe', b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca',
    b'\xca\xfe\xba\xbf', b'\xbf\xba\xfe\xca'}))
def test_every_executable_magic_ignores_filename_suffix(tool, frozen, magic):
    rel = 'vendor/opaque.data'
    add_file(frozen, rel, magic + b'payload')
    component = inventory(tool, frozen)[rel]
    assert properties(component)['annotshot:owner'] == UNOWNED
    assert component['hashes'][0]['content'] == hashlib.sha256(magic + b'payload').hexdigest()


@pytest.mark.parametrize('name', ['helper.exe', 'helper', 'helper.bin'])
def test_pe_signature_at_lfanew_is_listed(tool, frozen, name):
    content = bytearray(132)
    content[:2] = b'MZ'
    content[0x3c:0x40] = (128).to_bytes(4, 'little')
    content[128:] = b'PE\0\0'
    add_file(frozen, name, content)
    component = inventory(tool, frozen)[name]
    assert properties(component)['annotshot:owner'] == UNOWNED
    assert component['hashes'][0]['content'] == hashlib.sha256(content).hexdigest()


@pytest.mark.parametrize('content', [b'MZ', b'MZ' + b'\0' * 62,
    b'MZ' + b'\0' * 58 + (0xffffffff).to_bytes(4, 'little'),
    b'MZ' + b'\0' * 58 + (64).to_bytes(4, 'little') + b'PX\0\0'])
def test_mz_without_valid_pe_signature_is_not_content_evidence(tool, frozen, content):
    path = add_file(frozen, 'opaque.data', content)
    assert not tool.binary(path)


def test_hardlinked_binary_paths_are_each_listed(tool, frozen):
    original = add_file(frozen, 'vendor/one.dll')
    alias = frozen.bundle / 'vendor/two.dll'
    try:
        alias.hardlink_to(original)
    except (OSError, NotImplementedError) as error:
        pytest.skip(f'hardlinks unavailable: {error}')
    by_name = inventory(tool, frozen)
    assert by_name['vendor/one.dll']['hashes'] == by_name['vendor/two.dll']['hashes']


def test_license_fallbacks(tool):
    info = distribution('Example', Classifier=['Topic :: Utilities', 'License :: OSI Approved :: MIT License']).metadata
    assert tool.distribution_licenses(info) == [{'license': {'name': 'License :: OSI Approved :: MIT License'}}]
    assert tool.distribution_licenses(distribution('Example').metadata) == []
    info['License'] = 'Upstream terms'
    assert tool.distribution_licenses(info) == [{'license': {'name': 'Upstream terms'}}]
    info['License-Expression'] = 'BSD-2-Clause'
    assert tool.distribution_licenses(info) == [{'expression': 'BSD-2-Clause'}]


def test_readers_include_outer_modules(tool, frozen, monkeypatch):
    readers = sys.modules['PyInstaller.archive.readers']
    original = readers.CArchiveReader

    def reader(path):
        archive = original(path)
        archive.toc['outer_unknown'] = (0, 0, 0, 0, 'm')
        return archive

    monkeypatch.setattr(readers, 'CArchiveReader', reader)
    assert tool.main(frozen.args) == 1
    assert not frozen.out.exists()


def step_block(text, name):
    start = text.index('      - name: ' + name + '\n')
    end = text.find('      - ', start + 1)
    return text[start:end if end != -1 else len(text)]


@pytest.mark.parametrize('filename,label', [('build-windows.yml', 'windows'), ('release.yml', '${{ matrix.label }}')])
def test_workflow_additions_only_and_step_order(filename, label):
    path = '.github/workflows/' + filename
    text = (ROOT / path).read_text(encoding='utf-8')
    block = step_block(text, STEP)
    assert text.count('      - name: ' + STEP + '\n') == 1
    assert text.index('- name: Licence texts and the manual in the bundle') < text.index('- name: ' + STEP)
    assert 'if:' not in block and 'continue-on-error' not in block
    assert 'python tools/make-sbom.py --bundle ' in block
    assert '--exe ' in block and '--label ' in block and '--out ' in block
    assert f'Annotshot-${{{{ steps.version.outputs.version }}}}-{label}.cdx.json' in block
    if filename == 'build-windows.yml':
        names = re.findall(r'^      - name: (.+)$', text, re.M)
        position = names.index(STEP)
        assert names[position - 1:position + 2] == ["Sign the app's files (Windows)", STEP,
                                                  'Installer build (Windows)']
        assert '--bundle dist/Annotshot --exe dist/Annotshot/Annotshot.exe --label windows' in block
        asset = '            Annotshot-*-windows.cdx.json\n'
        assert asset in text.split('          name: Annotshot-windows\n', 1)[1]
    else:
        assert text.index('- name: ' + STEP) < text.index('- name: Zip (macOS)')
        assert 'bundle=dist/Annotshot\n' in block and 'bundle=dist/Annotshot.app\n' in block
        assert 'exe=dist/Annotshot/Annotshot\n' in block
        assert 'exe=dist/Annotshot.app/Contents/MacOS/Annotshot\n' in block
        assert '--bundle "$bundle" --exe "$exe" --label "${{ matrix.label }}"' in block
        asset = '            Annotshot-*-${{ matrix.label }}.cdx.json\n'
        assert asset in text.split('          name: Annotshot-${{ matrix.label }}\n', 1)[1]
        release_asset = '            zips/*.cdx.json\n'
        assert release_asset in text.split('      - uses: softprops/action-gh-release@v2\n', 1)[1]
    # Fixed text is independent of the checkout's commit state. The signing
    # suite separately preserves the complete pre-existing Windows steps block.
    expected = EXPECTED_SBOM_STEPS[filename]
    actual = block.split('      # The Windows installer,', 1)[0]
    assert actual == expected
    if filename == 'release.yml':
        assert step_block(text, 'Zip (macOS)') == EXPECTED_ZIP_MACOS
        assert step_block(text, 'Zip (Linux)') == EXPECTED_ZIP_LINUX
    assert hashlib.sha256(text.encode('utf-8')).hexdigest() == EXPECTED_WORKFLOW_SHA256[filename]


EXPECTED_SBOM_STEPS = {
    'build-windows.yml': '      - name: Parts list (CycloneDX SBOM)\n'
        '        run: python tools/make-sbom.py --bundle dist/Annotshot --exe dist/Annotshot/Annotshot.exe --label windows --out "Annotshot-${{ steps.version.outputs.version }}-windows.cdx.json"\n\n',
    'release.yml': '      - name: Parts list (CycloneDX SBOM)\n'
        '        run: |\n'
        '          bundle=dist/Annotshot\n'
        '          exe=dist/Annotshot/Annotshot\n'
        '          if [[ "$RUNNER_OS" == "macOS" ]]; then\n'
        '            bundle=dist/Annotshot.app\n'
        '            exe=dist/Annotshot.app/Contents/MacOS/Annotshot\n'
        '          fi\n'
        '          python tools/make-sbom.py --bundle "$bundle" --exe "$exe" --label "${{ matrix.label }}" --out "Annotshot-${{ steps.version.outputs.version }}-${{ matrix.label }}.cdx.json"\n\n',
}
EXPECTED_ZIP_MACOS = ('      - name: Zip (macOS)\n'
    "        if: runner.os == 'macOS'\n"
    '        run: ditto -c -k --sequesterRsrc --keepParent dist/Annotshot.app "Annotshot-${{ steps.version.outputs.version }}-macos.zip"\n\n')
EXPECTED_ZIP_LINUX = ('      - name: Zip (Linux)\n'
    "        if: runner.os == 'Linux'\n"
    '        run: (cd dist && zip -qry "../Annotshot-${{ steps.version.outputs.version }}-linux.zip" Annotshot)\n\n')


def test_workflow_guard_needs_no_git_or_other_process(monkeypatch):
    import subprocess

    def forbidden(*args, **kwargs):
        pytest.fail('workflow guard must not launch a process')

    monkeypatch.setattr(subprocess, 'run', forbidden)
    for filename, label in [('build-windows.yml', 'windows'), ('release.yml', '${{ matrix.label }}')]:
        test_workflow_additions_only_and_step_order(filename, label)


def test_fixed_workflow_guard_rejects_linux_zip_regression(monkeypatch):
    original = Path.read_text

    def mutated(path, *args, **kwargs):
        text = original(path, *args, **kwargs)
        return text.replace('zip -qry ', 'zip -q ') if path.name == 'release.yml' else text

    monkeypatch.setattr(Path, 'read_text', mutated)
    with pytest.raises(AssertionError):
        test_workflow_additions_only_and_step_order('release.yml', '${{ matrix.label }}')
