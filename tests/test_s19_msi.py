"""MSI harvester execution and Windows source contracts; no Windows runtime proof."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import uuid
import xml.etree.ElementTree as ET

import pytest

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / '.github/workflows/build-windows.yml'
RELEASE = ROOT / '.github/workflows/release.yml'
AUTHORING = ROOT / 'packaging/annotshot.wxs'
PROOF = ROOT / 'tools/prove-msi.ps1'
NS = {'w': 'http://wixtoolset.org/schemas/v4/wxs'}
UPGRADE = '{65C27F65-972B-4DC4-8E5C-3B8D62770532}'


def step(name):
    text = WORKFLOW.read_text(encoding='utf-8')
    match = re.search(rf'^      - name: {re.escape(name)}\n(.*?)(?=^      - |\Z)', text, re.M | re.S)
    assert match, name
    return match.group(1)


@pytest.fixture
def tool():
    spec = importlib.util.spec_from_file_location('make_msi', ROOT / 'tools/make-msi.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def payload(folder, reverse=False):
    entries = [('Annotshot.exe', b'exe'), ('_internal/python.dll', b'dll'),
               ('_internal/docx/templates/default-docx-template/[Content_Types].xml', b'<Types/>'),
               ('licences/A & B.txt', b'licence'), ('docs/space [1] café.txt', b'manual'),
               ('docs/dollar$(value).txt', b'literal dollar')]
    for name, data in (reversed(entries) if reverse else entries):
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    (folder / 'empty/nested').mkdir(parents=True)
    return folder


def identities(manifest):
    return {r['path']: (r['file_id'], r['component_id'], r['guid']) for r in manifest['files']}


def test_harvest_stability_completeness_and_no_source_mutation(tool, tmp_path):
    a = payload(tmp_path / 'a')
    b = payload(tmp_path / 'other/root', reverse=True)
    before = {p.relative_to(a).as_posix(): p.read_bytes() for p in a.rglob('*') if p.is_file()}
    first = tool.generate(a, '1.2.3', tmp_path / 'out-a')
    second = tool.generate(b, '1.2.3', tmp_path / 'out-b')
    assert identities(first) == identities(second)
    assert first['empty_directories'] == second['empty_directories']
    assert set(identities(first)) == set(before)
    assert [r['canonical_key'] for r in first['files']] == sorted(r['canonical_key'] for r in first['files'])
    assert first['product'] == second['product']
    assert before == {p.relative_to(a).as_posix(): p.read_bytes() for p in a.rglob('*') if p.is_file()}
    for record in first['files']:
        assert record['sha256'] == hashlib.sha256(before[record['path']]).hexdigest()
        expected = str(uuid.uuid5(uuid.UUID(UPGRADE), 'file|x64|' + record['canonical_key'])).upper()
        assert record['guid'] == '{' + expected + '}'
        assert record['canonical_key'] == tool.key(record['path'])
        for field, prefix in [('file_id','F'), ('component_id','C')]:
            assert record[field] == prefix + hashlib.sha256(record['canonical_key'].encode()).hexdigest()
            assert len(record[field]) <= 72
    assert first['empty_directories'][0]['path'] == 'empty/nested'
    assert json.loads((tmp_path / 'out-a/manifest.json').read_text(encoding='utf-8')) == first
    tool.verify_sources(tmp_path / 'out-a/manifest.json')
    (a / 'Annotshot.exe').write_bytes(b'changed signed bytes')
    with pytest.raises(ValueError, match='source bytes changed'):
        tool.verify_sources(tmp_path / 'out-a/manifest.json')
    changed = tool.generate(a, '1.2.4', tmp_path / 'out-a')
    assert identities(first) == identities(changed)
    (a / 'new.txt').write_bytes(b'new')
    (a / 'docs/space [1] café.txt').rename(a / 'docs/renamed.txt')
    (a / '_internal/python.dll').unlink()
    third = tool.generate(a, '1.2.4', tmp_path / 'out-a')
    old, new = identities(first), identities(third)
    assert all(new[p] == old[p] for p in old.keys() & new.keys())
    assert new.keys() - old.keys() == {'new.txt', 'docs/renamed.txt'}
    assert old.keys() - new.keys() == {'docs/space [1] café.txt', '_internal/python.dll'}


def test_xml_escaping_keypaths_feature_and_metadata(tool, tmp_path):
    dist = payload(tmp_path / 'A & space')
    out = tmp_path / 'out'
    manifest = tool.generate(dist, '255.255.65535', out)
    root = ET.parse(out / 'Payload.wxs').getroot()
    icon = root.find('.//w:Icon', NS)
    arp_icon = ET.parse(AUTHORING).find('.//w:Property[@Id="ARPPRODUCTICON"]', NS)
    assert (icon.attrib['Id'] == arp_icon.attrib['Value']
            and Path(icon.attrib['Id']).suffix == Path(icon.attrib['SourceFile']).suffix == '.exe')
    components = root.findall('.//w:Component', NS)
    refs = root.findall('.//w:ComponentRef', NS)
    assert {c.attrib['Id'] for c in components} == {r.attrib['Id'] for r in refs}
    assert len(components) == len(manifest['files']) + len(manifest['empty_directories'])
    for component in components:
        assert component.attrib['Bitness'] == 'always64'
        files = component.findall('w:File', NS)
        if files:
            assert len(files) == 1 and files[0].attrib['KeyPath'] == 'yes'
            source = files[0].attrib['Source'].replace('$$', '$')
            assert Path(source).read_bytes() == (dist / next(r['path'] for r in manifest['files'] if r['component_id'] == component.attrib['Id'])).read_bytes()
            assert files[0].attrib['Name'].replace('$$', '$') == Path(source).name
        else:
            assert component.attrib['KeyPath'] == 'yes'
            assert component.find('w:CreateFolder', NS) is not None
            assert component.find('w:RemoveFolder', NS).attrib['On'] == 'uninstall'
    assert b'&amp;' in (out / 'Payload.wxs').read_bytes()
    assert '$$(value)' in (out / 'Payload.wxs').read_text(encoding='utf-8')
    assert manifest['product']['upgrade_code'] == UPGRADE
    assert manifest['product']['architecture'] == 'x64'
    again = tool.generate(dist, '255.255.65535', out)
    assert again['product']['product_code'] == manifest['product']['product_code']
    earlier = tool.generate(dist, '1.0.0', out)
    assert earlier['product']['product_code'] != manifest['product']['product_code']
    assert earlier['product']['product_code'] == tool.guid(uuid.UUID(UPGRADE), 'product|x64|1.0.0')
    assert len(set(earlier['non_file_components'].values()) | {r['guid'] for r in earlier['files']}) == len(earlier['files']) + 2
    definitions = (out / 'Identity.wxi').read_text(encoding='utf-8')
    assert f'ProductCode="{earlier["product"]["product_code"]}"' in definitions
    assert 'PackageCode' not in definitions
    # The namespace has exactly one implementation source, in authored WiX.
    assert UPGRADE not in (ROOT / 'tools/make-msi.py').read_text(encoding='utf-8')


@pytest.mark.parametrize('version', ['v1.2.3','01.2.3','1.02.3','1.2.03','1.2','1.2.3.4','1.2.3-beta','256.0.0','0.256.0','0.0.65536','-1.0.0','1.2.3\n','１.2.3'])
def test_invalid_versions_have_no_output(tool, tmp_path, version):
    dist = payload(tmp_path / 'dist')
    with pytest.raises(ValueError):
        tool.generate(dist, version, tmp_path / 'out')
    assert not (tmp_path / 'out').exists()


@pytest.mark.parametrize('bad', ['CON','aux.txt','LPT1.log','COM¹','bad:name','tail.','tail ','a?b','line\nbreak'])
def test_invalid_windows_names(tool, tmp_path, bad, monkeypatch):
    # Windows cannot hold these names (it strips, streams or refuses them), so
    # the walk reports the name instead of a real file; the name check runs
    # before any file is touched, on every system.
    dist = payload(tmp_path / 'dist')
    original_walk = tool.os.walk
    def with_bad_name(*args, **kwargs):
        for folder, dirs, files in original_walk(*args, **kwargs):
            if Path(folder) == dist:
                files = list(files) + [bad]
            yield folder, dirs, files
    monkeypatch.setattr(tool.os, 'walk', with_bad_name)
    with pytest.raises(ValueError, match='invalid Windows name'):
        tool.generate(dist, '1.0.0', tmp_path / 'out')
    assert not (tmp_path / 'out').exists()


def test_missing_exe_and_dirty_receipt(tool, tmp_path):
    dist = payload(tmp_path / 'dist')
    (dist / 'CHECK.TXT').write_text('old receipt', encoding='utf-8')
    with pytest.raises(ValueError, match='check.txt'):
        tool.generate(dist, '1.0.0', tmp_path / 'out')
    (dist / 'CHECK.TXT').unlink()
    (dist / 'Annotshot.exe').unlink()
    with pytest.raises(ValueError, match='Annotshot.exe'):
        tool.generate(dist, '1.0.0', tmp_path / 'out')


@pytest.mark.parametrize('names', [('Name.txt','name.TXT'), ('café.txt','cafe\u0301.txt')])
def test_collisions(tool, tmp_path, names, monkeypatch):
    # On a normalizing host, enumerate the alias spellings explicitly. They
    # resolve to real files; the actual harvester collision gate must reject.
    dist = payload(tmp_path / 'dist')
    for name in names:
        (dist / name).write_bytes(name.encode('utf-8'))
    assert tool.key(names[0]) == tool.key(names[1])
    original_walk = tool.os.walk
    def enumerate_aliases(*args, **kwargs):
        for folder, dirs, files in original_walk(*args, **kwargs):
            if Path(folder) == dist:
                files = [f for f in files if tool.key(f) != tool.key(names[0])] + list(names)
            yield folder, dirs, files
    monkeypatch.setattr(tool.os, 'walk', enumerate_aliases)
    with pytest.raises(ValueError, match='collision'):
        tool.generate(dist, '1.0.0', tmp_path / 'out')


@pytest.mark.parametrize('kind', ['file','directory','broken','output','ancestor'])
def test_links_and_reparse_policy(tool, tmp_path, kind):
    dist = payload(tmp_path / 'dist')
    out = tmp_path / 'out'
    if kind == 'output':
        out.symlink_to(dist, target_is_directory=True)
    elif kind == 'ancestor':
        linked = tmp_path / 'linked'
        linked.symlink_to(dist, target_is_directory=True)
        dist = linked
    else:
        destination = dist / ('Annotshot.exe' if kind == 'file' else 'empty' if kind == 'directory' else 'absent')
        (dist / 'link').symlink_to(destination, target_is_directory=kind == 'directory')
    with pytest.raises(ValueError, match='links/reparse'):
        tool.generate(dist, '1.0.0', out)
    assert 'st_file_attributes' in (ROOT / 'tools/make-msi.py').read_text(encoding='utf-8')


def test_safe_output_no_unrelated_removal(tool, tmp_path):
    dist = payload(tmp_path / 'dist')
    for out in [dist, dist.parent, dist / 'out']:
        with pytest.raises(ValueError, match='overlap'):
            tool.generate(dist, '1.0.0', out)
    out = tmp_path / 'out'
    out.mkdir()
    (out / 'precious.txt').write_text('keep', encoding='utf-8')
    with pytest.raises(ValueError, match='ownership'):
        tool.generate(dist, '1.0.0', out)
    assert (out / 'precious.txt').read_text(encoding='utf-8') == 'keep'
    (out / tool.MARKER).write_text(tool.MARKER_TEXT, encoding='utf-8')
    with pytest.raises(ValueError, match='unrelated'):
        tool.generate(dist, '1.0.0', out)
    assert (out / 'precious.txt').read_text(encoding='utf-8') == 'keep'
    (out / 'precious.txt').unlink()
    outside = tmp_path / 'outside'
    outside.write_text('preserve', encoding='utf-8')
    (out / 'Payload.wxs').symlink_to(outside)
    with pytest.raises(ValueError, match='links/reparse'):
        tool.generate(dist, '1.0.0', out)
    assert outside.read_text(encoding='utf-8') == 'preserve'


def test_wix_machine_contract_registry_shortcut_and_upgrade():
    package = ET.parse(AUTHORING).getroot().find('w:Package', NS)
    assert package.attrib == dict(Name='Annotshot', Manufacturer='Stet Software', Scope='perMachine', Version='$(var.ProductVersion)', ProductCode='$(var.ProductCode)', UpgradeCode=UPGRADE, InstallerVersion='500')
    assert package.find('w:MajorUpgrade', NS).attrib == dict(Schedule='afterInstallInitialize', AllowDowngrades='no', AllowSameVersionUpgrades='no', DowngradeErrorMessage='A newer version of Annotshot is already installed.')
    assert package.find('w:MediaTemplate', NS).attrib['EmbedCab'] == 'yes'
    assert package.find('w:StandardDirectory[@Id="ProgramFiles64Folder"]/w:Directory', NS).attrib == dict(Id='INSTALLFOLDER', Name='Annotshot')
    associations = package.find('.//w:Component[@Id="Associations"]', NS)
    assert associations.attrib['Bitness'] == 'always64'
    values = associations.findall('w:RegistryValue', NS)
    expected = {
        ('.annotshot',None): 'Annotshot.Editable', ('.snagup',None): 'Annotshot.Editable',
        ('.annotshot\\OpenWithProgids','Annotshot.Editable'): '', ('.snagup\\OpenWithProgids','Annotshot.Editable'): '',
        ('Annotshot.Editable',None): 'Annotshot editable file',
        ('Annotshot.Editable\\DefaultIcon',None): '"[INSTALLFOLDER]Annotshot.exe",0',
        ('Annotshot.Editable\\shell\\open\\command',None): '"[INSTALLFOLDER]Annotshot.exe" "%1"',
        ('Applications\\Annotshot.exe','FriendlyAppName'): 'Annotshot',
        ('Applications\\Annotshot.exe\\shell\\open\\command',None): '"[INSTALLFOLDER]Annotshot.exe" "%1"',
        ('Applications\\Annotshot.exe\\SupportedTypes','.annotshot'): '',
        ('Applications\\Annotshot.exe\\SupportedTypes','.snagup'): '',
    }
    assert {(r.attrib['Key'].removeprefix('Software\\Classes\\'), r.attrib.get('Name')): r.attrib['Value'] for r in values} == expected
    assert all(r.attrib['Root'] == 'HKLM' and r.attrib['Type'] == 'string' for r in values)
    assert len([r for r in values if r.attrib.get('KeyPath') == 'yes']) == 1
    menu = package.find('w:StandardDirectory[@Id="ProgramMenuFolder"]/w:Directory', NS)
    shortcut = menu.find('.//w:Shortcut', NS)
    assert menu.attrib['Name'] == 'Annotshot'
    assert shortcut.attrib == dict(Id='AnnotshotShortcut', Name='Annotshot', Target='[INSTALLFOLDER]Annotshot.exe', WorkingDirectory='INSTALLFOLDER', Advertise='no')
    assert menu.find('.//w:RegistryValue', NS).attrib['Root'] == 'HKLM'
    assert menu.find('.//w:RegistryValue', NS).attrib['KeyPath'] == 'yes'
    assert menu.find('.//w:RemoveFolder', NS).attrib['On'] == 'uninstall'
    assert package.find('.//w:RemoveFile', NS).attrib == dict(Id='DiagnosticReceipt', Name='check.txt', On='uninstall')
    feature = package.find('w:Feature', NS)
    assert [r.attrib['Id'] for r in feature] == ['PayloadComponents', 'Associations', 'StartMenuShortcut']
    props = {p.attrib['Id']: p.attrib['Value'] for p in package.findall('w:Property', NS)}
    assert props['ARPPRODUCTICON'] == 'AnnotshotIcon.exe'
    for key, tail in [('ARPURLINFOABOUT',''), ('ARPHELPLINK','/issues'), ('ARPURLUPDATEINFO','/releases')]:
        assert props[key] == 'https://github.com/Bill-Viking/annotshot' + tail
    arp = package.find('w:SetProperty[@Id="ARPINSTALLLOCATION"]', NS)
    assert arp.attrib['Value'] == '[INSTALLFOLDER]' and arp.attrib['After'] == 'CostFinalize'
    text = AUTHORING.read_text(encoding='utf-8')
    for forbidden in ['HKCU','UserChoice','AppData','CustomAction','Launch','ServiceInstall','UIRef','ScheduledTask','ForceDeleteOnUninstall','DISABLEROLLBACK','IgnoreRemoveFailure','PackageCode="']:
        assert forbidden not in text
    assert all(c.attrib['Bitness'] == 'always64' for c in package.findall('.//w:Component', NS))


def test_toolset_and_build_source_contract():
    tools = step('MSI tools (Windows)')
    for token in ['shell: pwsh', 'timeout-minutes: 5','ImageOS','ImageVersion','OSArchitecture','PSVersionTable.PSVersion','Get-Command dotnet','--info','--list-sdks','--list-runtimes','ProcessArchitecture',"-ne 'X64'", 'Microsoft.NETCore.App', '-ge 8','STOP missing stable .NET SDK','STOP missing x64','tool install wix --version 5.0.2 --tool-path $toolDir',"Join-Path $env:RUNNER_TEMP", "Join-Path $toolDir 'wix.exe'", '& $wix --version', '^5\\.0\\.2', 'STOP WiX version', 'STOP WiX start/version', 'STOP WiX 5.0.2 install']:
        assert token in tools
    assert tools.count('$LASTEXITCODE -ne 0') == 3
    assert 'DOTNET_ROLL_FORWARD: LatestMajor' in tools
    build = step('MSI build (Windows)')
    for token in ['DOTNET_ROLL_FORWARD: LatestMajor','timeout-minutes: 5','--dist dist/Annotshot --version $v --out build/msi','& $env:WIX_EXE build -arch x64 -i build/msi','packaging/annotshot.wxs build/msi/Payload.wxs','Annotshot-$v.msi','IsPathFullyQualified','--verify-sources build/msi/manifest.json','OpenDatabase($msi, 0)','ProductVersion','ProductCode','UpgradeCode','GITHUB_STEP_SUMMARY','UNSIGNED MSI']:
        assert token in build
    assert build.index('WIX_EXE build') < build.index('--verify-sources')
    assert build.count('$LASTEXITCODE -ne 0') == 3
    for forbidden in ['-sval','-sice','continue-on-error','Win32_Product -','tool update','dotnet-install']:
        assert forbidden not in tools + build


def test_workflow_order_signing_and_assets_source_contract():
    text = WORKFLOW.read_text(encoding='utf-8')
    names = re.findall(r'^      - name: (.+)$', text, re.M)
    index = names.index('Installer proof (Windows)')
    assert names[index:index+6] == ['Installer proof (Windows)','MSI tools (Windows)','MSI build (Windows)','Sign the MSI (Windows)','MSI proof (Windows)','Signatures (Windows)']
    assert names.index("Sign the app's files (Windows)") < index
    for name in ['MSI tools (Windows)','MSI build (Windows)','MSI proof (Windows)']:
        assert 'if:' not in step(name)
    signing = step('Sign the MSI (Windows)')
    assert "if: env.SIGN == 'true'" in signing
    for token in ['Azure/artifact-signing-action@v2','endpoint: ${{ vars.SIGNING_ENDPOINT }}','signing-account-name: ${{ vars.SIGNING_ACCOUNT }}','certificate-profile-name: ${{ vars.SIGNING_PROFILE }}',r'files: ${{ github.workspace }}\Annotshot-${{ steps.version.outputs.version }}.msi','file-digest: SHA256','timestamp-digest: SHA256','timestamp-rfc3161: http://timestamp.acs.microsoft.com']:
        assert token in signing
    signatures = step('Signatures (Windows)')
    assert 'foreach ($path in (@($signedFiles) + @($setup) + @($msi)))' in signatures
    for token in ["PublicKey.Oid.Value -ne '1.2.840.113549.1.1.1'", 'RSACertificateExtensions]::GetRSAPublicKey', '$null -eq $rsa', '$rsa.KeySize -lt 2048 -or $rsa.KeySize -gt 4096', '$rsa.Dispose()', 'finally', 'TimeStamperCertificate', 'signerHash -cne $env:SIGNER_SUBJECT_SHA256']:
        assert token in signatures
    assert signatures.index('signerHash -cne') < signatures.index('GetRSAPublicKey')
    # RSA restriction belongs only to the MSI, after the selected-files loop.
    assert 'Get-AuthenticodeSignature -LiteralPath $msi' in signatures
    assert 'GetRSAPublicKey' not in signatures.split('foreach ($file in $files) {')[1].split('\n          }')[0]
    assert 'RSA $($rsa.KeySize) bits' in signatures
    assert "Test-Path -LiteralPath 'Annotshot-${{ steps.version.outputs.version }}.msi' -PathType Leaf" in step('Exact MSI before upload (Windows)')
    evidence = step('MSI proof evidence (Windows)')
    for token in ['if: always()', 'name: msi-proof-${{ github.run_id }}-${{ github.run_attempt }}','retention-days: 14','build/msi/manifest.json','${{ runner.temp }}/annotshot-msi-proof-']:
        assert token in evidence
    for pattern in ['Annotshot-*-windows.zip','Annotshot-*-setup.exe','Annotshot-*.msix']:
        assert f'            {pattern}\n' in text
    release = RELEASE.read_text(encoding='utf-8')
    assert 'needs: [build, build_windows_signed, build_windows]' in release
    for pattern in ['zips/*.zip','zips/*-setup.exe','zips/Annotshot-*.msix','zips/Annotshot-*.msi']:
        assert f'            {pattern}\n' in release
    assert 'msi-proof' not in release
    proof = step('MSI proof (Windows)')
    for token in ['-Msi (Join-Path $PWD','-Version $v','-Manifest (Join-Path $PWD','-ProofDirectory $proof']:
        assert token in proof


def test_system_helper_source_contract_not_runtime_simulation():
    source = PROOF.read_text(encoding='utf-8')
    for token in ["$ErrorActionPreference = 'Stop'",'Set-StrictMode',"$identity.User.Value -eq 'S-1-5-18'",'$sessionId -eq 0','identity_sid=$identity.User.Value','session_id=$sessionId',"$env:QT_QPA_PLATFORM='offscreen'",'WindowsBuiltInRole]::Administrator','Get-Command $command',"Get-Service -Name Schedule", "-UserId 'S-1-5-18' -LogonType ServiceAccount -RunLevel Highest",'System32\\WindowsPowerShell\\v1.0\\powershell.exe','-NoProfile -NonInteractive -File','SetAccessRuleProtection($true,$false)',"'S-1-5-32-544'",'Set-Acl -LiteralPath',"'/i ' + (Quote $Msi)","'/x ' + (Quote $productCode)",' /qn /norestart /l*v ', '@(0,3010)', '1641/1618 fail', 'reboot_required=$true', '$process.WaitForExit($Seconds * 1000)', "'install.log'))) $Timing.InstallSeconds", "'uninstall.log'))) $Timing.UninstallSeconds", "'--check' $Timing.CheckSeconds", 'New-TimeSpan -Seconds $Timing.TaskSeconds', '$started.AddSeconds($Timing.ParentSeconds)', 'Start-Sleep -Seconds 1','RegistryView]::Registry64','Get-FileHash -LiteralPath $installed -Algorithm SHA256','metadata.empty_directories','GetFolderPath([Environment+SpecialFolder]::ProgramFiles)','CommonPrograms','CreateShortcut','link.TargetPath','link.WorkingDirectory',"'WindowsInstaller' 1", "'DisplayVersion' $Version", "'Publisher' 'Stet Software'", "'DisplayName' 'Annotshot'", "'InstallLocation' ($target + '\\')", "'DisplayIcon'",'UninstallString','NoUserRegistration $user', '$lines[-1].Trim()', '$receipt.check_exit -eq 0 -and $last -ceq "Annotshot $Version OK"', "elseif (Test-Path -LiteralPath $diagnostic)", 'check.stderr.txt', 'check.receipt.txt','Remove-Item -LiteralPath $diagnostic', 'uninstall left install folder','registry differs from before install (keys, values or kinds)','uninstall left common shortcut','AtomicReceipt $receipt',"$Name + '.tmp'", 'Move-Item -LiteralPath $temporary', '$result.nonce -ceq $Nonce','$result.version -ceq $Version', '$result.product_code -ceq $productCode','$result.upgrade_code -ceq $upgradeCode', '$info.LastTaskResult -eq 0','LastWriteTimeUtc -ge $started.ToUniversalTime()', 'missing completion receipt', 'finally', 'Stop-ScheduledTask -TaskName $taskName','Unregister-ScheduledTask -TaskName $taskName -Confirm:$false', "'install-start.json')) -and -not $receipt.removal_ok)", '$receipt.error=$_.Exception.Message', '$receipt.cleanup_error=$_.Exception.Message','if ($parentError -or $cleanupErrors.Count) { exit 1 }','literal logged-off operation UNPROVEN']:
        assert token in source, token
    for key in ['.annotshot', '.snagup','OpenWithProgids','FriendlyAppName','SupportedTypes','DefaultIcon','Annotshot.Editable\\shell\\open\\command','Applications\\Annotshot.exe\\shell\\open\\command']:
        assert key in source
    for forbidden in ['InteractiveToken','-Verb RunAs','-ExecutionPolicy','Set-ExecutionPolicy','PsExec','Win32_Product','-Wait ', '-Recurse','Everyone','Stop-Process -Name','shutdown','logoff']:
        assert forbidden not in source
    # Original failure survives attempted cleanup. Only the diagnostic is deleted.
    assert source.count('Remove-Item -LiteralPath') == 2
    assert '$receipt.success=$true' not in source.split('} catch {\n        $receipt.error=')[1]
    assert 'SYSTEM UNPROVEN' in source


def function_source(name):
    source = PROOF.read_text(encoding='utf-8')
    return source.split(f'function {name}(', 1)[1].split('\n}\n', 1)[0]


def test_packed_product_code_static_transformation_and_known_pair():
    helper = function_source('PackedProductCode')
    # {2869B2AB-0058-5282-9F29-18AB5F4A082A} -> BA2B968285002825F99281BAF5A480A2
    assert "$hex=$Code -replace '[{}-]',''" in helper
    assert '$packed=(-join $hex[7..0]) + (-join $hex[11..8]) + (-join $hex[15..12])' in helper
    assert 'for ($i=16; $i -lt 32; $i+=2) { $packed += [string]$hex[$i+1] + [string]$hex[$i] }' in helper
    assert 'return $packed' in helper
    # Python checks the rule's known vector; PowerShell is not executed here.
    code = re.sub(r'[{}-]', '', '{2869B2AB-0058-5282-9F29-18AB5F4A082A}')
    packed = code[:8][::-1] + code[8:12][::-1] + code[12:16][::-1]
    packed += ''.join(code[i:i + 2][::-1] for i in range(16, 32, 2))
    assert packed == 'BA2B968285002825F99281BAF5A480A2'


def test_product_icon_fallback_and_uninstall_static_contract():
    source = PROOF.read_text(encoding='utf-8')
    helper = function_source('RequireProductIcon')
    assert 'RegistryView]::Registry64' in function_source('OpenHive')
    assert '$machine=OpenHive ([Microsoft.Win32.RegistryHive]::LocalMachine)' in source
    assert "$publishedProduct='Software\\Classes\\Installer\\Products\\' + (PackedProductCode $productCode)" in source
    assert 'RequireProductIcon $machine $arp $publishedProduct' in source
    assert "$k=$Hive.OpenSubKey($ArpPath)" in helper
    fallback = "if ($null -ne $k -and -not [string]::IsNullOrWhiteSpace($k.GetValue('DisplayIcon'))) { return }"
    assert fallback in helper
    assert helper.index(fallback) < helper.index('$k=$Hive.OpenSubKey($PublishedPath)')
    checks = [
        "Require ($null -ne $k) 'ARP icon missing: no published product key'",
        "$icon=[string]$k.GetValue('ProductIcon')",
        "Require (-not [string]::IsNullOrWhiteSpace($icon)) 'ARP icon missing: no ProductIcon value'",
        "Require (Test-Path -LiteralPath $icon -PathType Leaf -ErrorAction SilentlyContinue) 'ARP icon missing: icon file missing'",
    ]
    assert all(check in helper for check in checks)
    assert [helper.index(check) for check in checks] == sorted(helper.index(check) for check in checks)
    assert helper.count('finally { if ($null -ne $k) { $k.Dispose() } }') == 2
    assert re.findall(r"'ARP icon missing[^']*'", source) == [
        "'ARP icon missing: no published product key'",
        "'ARP icon missing: no ProductIcon value'",
        "'ARP icon missing: icon file missing'",
    ]
    # Value DATA is used only in memory for the literal file probe.
    assert helper.count('$icon') == 3
    assert not re.search(r'Write-Host|Set-Content|AtomicReceipt|throw ', helper)
    removal = "Require (AbsentKey $machine $publishedProduct) 'uninstall left the published product key'"
    assert source.index("AcceptMsi $receipt.uninstall_exit 'uninstall'") < source.index(removal) < source.index('$receipt.removal_ok=$true')


@pytest.mark.parametrize('code,succeeded,accepted', [
    (0, True, True), (1, True, False), (3010, True, False),
    (-1, True, False), (0, False, False),
])
def test_parent_success_exit_and_callers_static_exit_contract(code, succeeded, accepted):
    source = PROOF.read_text(encoding='utf-8')
    assert source.rstrip().endswith(
        'if ($parentError -or $cleanupErrors.Count) { exit 1 }\nexit 0')
    caller = step('MSI proof (Windows)').splitlines()
    invocation = next(i for i, line in enumerate(caller) if '& ./tools/prove-msi.ps1 ' in line)
    guard = caller[invocation + 1].strip()
    assert guard == "if (-not $? -or $LASTEXITCODE -ne 0) { throw 'STOP MSI SYSTEM proof failed' }"
    # Static truth table for that exact guard; this does not execute PowerShell.
    assert (not (not succeeded or code != 0)) is accepted


def test_registry_baselines_preserve_shared_containers_and_all_owned_values():
    source = PROOF.read_text(encoding='utf-8')
    preflight = function_source('NoUserRegistration')
    shared, owned = preflight.split("    foreach ($path in @('Software\\Classes\\Annotshot.Editable'", 1)
    assert 'AbsentKey' not in shared
    for extension in ('.annotshot', '.snagup'):
        assert f'Software\\Classes\\{extension}' in shared
    assert 'NoAssociationValue (RegistryTree $Hive $path) $Label' in shared
    assert 'Software\\Classes\\Applications\\Annotshot.exe' in owned
    assert 'Require (AbsentKey $Hive $path)' in owned
    associations = function_source('NoAssociationValue')
    assert "$value.name -ine 'Annotshot.Editable'" in associations
    assert "@($value.data) -notcontains 'Annotshot.Editable'" in associations
    assert 'foreach ($child in $Tree.children) { NoAssociationValue $child $Label }' in associations
    tree = function_source('RegistryTree')
    for token in ['exists=($null -ne $k)', 'GetValueNames() | Sort-Object',
                  'name=$name', 'kind=$k.GetValueKind($name).ToString()',
                  'DoNotExpandEnvironmentNames', 'GetSubKeyNames() | Sort-Object',
                  "$state.children += RegistryTree $Hive ($Path + '\\' + $child)"]:
        assert token in tree
    assert '$registryRoots=$ownedKeys + @($arp,$innoArp)' in source
    assert 'foreach ($path in $registryRoots)' in function_source('RegistryState')
    comparison = function_source('RegistryRestored')
    assert 'NoUserRegistration $Hive $Label' in comparison
    assert '$after=RegistryState $Hive' in comparison
    assert '$differences=@(RegistryDifferences $Before $after)' in comparison
    assert 'Require ($differences.Count -eq 0)' in comparison
    worker = source.split('if ($Worker) {', 1)[1].split('# Parent does not', 1)[0]
    for name, hive in [('machine', '$machine'), ('system', '$user')]:
        assert worker.index(f'${name}Before=RegistryState {hive}') < worker.index('$receipt.install_exit=RunBounded')
        assert f'RegistryRestored {hive} ${name}Before' in worker
    parent = source.split('# Parent does not', 1)[1]
    for name, hive in [('runner', '$user'), ('parentMachine', '$machine')]:
        assert parent.index(f'${name}Before=RegistryState {hive}') < parent.index('Start-ScheduledTask -TaskName')
        assert f'RegistryRestored {hive} ${name}Before' in parent
    # Registry changes must come from MSI install/uninstall, never proof cleanup.
    for forbidden in ['DeleteSubKey', 'DeleteValue', 'CreateSubKey', 'SetValue(',
                      'Remove-ItemProperty', 'Set-ItemProperty', 'Remove-Item -Path']:
        assert forbidden not in source


def test_literal_file_operations_and_quoted_parent_worker_paths():
    import ntpath
    import shlex

    source = PROOF.read_text(encoding='utf-8')
    file_commands = ('Get-Item', 'Get-Content', 'Set-Content', 'Copy-Item',
                     'Move-Item', 'Remove-Item', 'Test-Path', 'Get-FileHash',
                     'Set-Acl', 'Split-Path')
    for command in file_commands:
        calls = re.findall(rf'\b{command}\b([^\n]*)', source)
        assert calls, command
        assert all(call.startswith(' -LiteralPath ') for call in calls), command
    assert not re.search(r'\s-Path\s', source)
    quote = function_source('Quote')
    assert "return '\"' + $Value + '\"'" in quote
    assert "$Value -notmatch '[\"\\r\\n]' -and -not $Value.EndsWith('\\')" in quote
    arguments = function_source('WorkerArguments')
    expression = re.search(r"^    \$arguments=(.*)$", arguments, re.M).group(1)
    values = dict(PSCommandPath=r'C:\source folder [1] $literal\prove-msi.ps1',
                  Msi=r'C:\MSI folder [1] $literal\Annotshot-1.2.3 [1] $.msi',
                  Version='1.2.3', ProofDirectory=r'C:\proof folder [1] $literal',
                  Nonce='a' * 32)
    # Expand only the source's literal concatenations and Quote wrappers, then
    # inspect argv. This is a static quoting guard, not a Windows launch proof.
    parts = []
    for term in expression.split(' + '):
        if term.startswith("'") and term.endswith("'"):
            parts.append(term[1:-1])
        elif term == "(Quote (Join-Path $ProofDirectory 'manifest.json'))":
            parts.append('"' + ntpath.join(values['ProofDirectory'], 'manifest.json') + '"')
        else:
            match = re.fullmatch(r'\(Quote \$(\w+)\)', term)
            assert match, term
            parts.append('"' + values[match[1]] + '"')
    argv = [a.strip('"') for a in shlex.split(''.join(parts), posix=False)]
    for option, value in [('-File', values['PSCommandPath']), ('-Msi', values['Msi']),
                          ('-Manifest', ntpath.join(values['ProofDirectory'], 'manifest.json')),
                          ('-ProofDirectory', values['ProofDirectory']), ('-Nonce', values['Nonce'])]:
        assert argv[argv.index(option) + 1] == value
    assert "if ($Phase) { $arguments += ' -Phase' }" in arguments
    assert '$arguments=WorkerArguments' in source
    assert 'RunBounded $powershell (WorkerArguments -Phase)' in source
    assert '-Argument $arguments' in source
    assert '-ProofDirectory $proof' in step('MSI proof (Windows)')
    assert 'Invoke-Expression' not in source and not re.search(r'(?<!\S)-Command\s', source)


def test_timing_sums_and_cleanup_outside_bounded_normal_phase():
    source = PROOF.read_text(encoding='utf-8')
    block = source.split('$Timing = @{', 1)[1].split('\n}', 1)[0]
    limits = {name: int(value) for name, value in re.findall(r'(\w+)=(\d+)', block)}
    assert sum(limits[k] for k in ('InstallSeconds', 'CheckSeconds', 'UninstallSeconds', 'ValidationSeconds')) == limits['WorkSeconds']
    waits = ('ChildTerminationSeconds', 'PhaseTerminationSeconds',
             'CleanupTerminationSeconds', 'InstallerIdleSeconds')
    assert all(limits[k] > 0 for k in waits)
    assert limits['WorkSeconds'] + limits['CleanupSeconds'] + sum(limits[k] for k in waits) + 120 <= limits['TaskSeconds']
    assert limits['ParentSeconds'] == limits['TaskSeconds'] + 60
    workflow_seconds = int(re.search(r'timeout-minutes: (\d+)', step('MSI proof (Windows)'))[1]) * 60
    assert limits['ParentSeconds'] + 180 <= workflow_seconds <= 30 * 60
    assert 0 < limits['PhaseMarginSeconds'] < limits['ValidationSeconds']
    supervisor, phase = source.split('if ($Worker -and -not $Phase) {', 1)[1].split('\nif ($Worker) {', 1)
    assert 'RunBounded $powershell (WorkerArguments -Phase) $Timing.WorkSeconds' in supervisor
    assert "'cleanup.log'))) $Timing.CleanupSeconds" in supervisor
    assert supervisor.index('} catch {') < supervisor.index("'cleanup.log'") < supervisor.index('} finally {')
    assert "Test-Path -LiteralPath (Join-Path $ProofDirectory 'install-start.json')" in supervisor
    assert '$receipt.success=$false' in supervisor.split('} catch {', 1)[1]
    assert 'AtomicReceipt $receipt' in supervisor
    assert '$Timing.PhaseTerminationSeconds' in supervisor
    assert '$Timing.CleanupTerminationSeconds' in supervisor
    assert "'cleanup.log'" not in phase
    for stage in ('Install', 'Check', 'Uninstall'):
        assert f'RequireWorkTime $Timing.{stage}Seconds' in phase
        assert f'$Timing.{stage}Seconds' in phase
    admission = function_source('RequireWorkTime')
    assert '$workClock.Elapsed.TotalSeconds + $Seconds' in admission
    assert '$Timing.WorkSeconds - $Timing.PhaseMarginSeconds' in admission
    assert 'New-TimeSpan -Seconds $Timing.TaskSeconds' in phase
    assert '$started.AddSeconds($Timing.ParentSeconds)' in phase
    # No uncoordinated numeric child timeout can escape this table.
    for line in source.splitlines():
        if '=RunBounded ' in line:
            assert re.search(r'\$Timing\.\w+Seconds', line), line


def test_timeout_reconciles_entire_owned_tree_before_cleanup_static_contract():
    source = PROOF.read_text(encoding='utf-8')
    native = source.split("Add-Type -TypeDefinition @'\n", 1)[1].split("\n'@", 1)[0]
    # A private job closes the spawn/exit/PID-reuse races of a PID-only walk.
    # Root starts suspended; descendants cannot escape via job breakaway.
    assert 'job=CreateJobObject(IntPtr.Zero,null)' in native
    assert 'limits.basic.flags=0x2000;' in native  # KILL_ON_JOB_CLOSE only
    assert 'true,0x08000004,' in native  # suspended + no window
    assert native.index('CreateProcess(file,') < native.index('AssignProcessToJobObject(job,process)') < native.index('ResumeThread(thread)!=')
    for token in ['TerminateJobObject(job,1)', 'clock.Elapsed.TotalMilliseconds<milliseconds',
                  'if (Empty) return true', 'info.active==0',
                  'else if (process!=IntPtr.Zero && !WaitForExit(0))']:
        assert token in native, token
    # The sole individual-process kill uses the retained handle of our suspended
    # root when assignment failed, never a snapshot PID or a process name.
    assert native.count('Check(TerminateProcess(process,1))') == 1
    assert 'TerminateProcess(handle' not in native
    bounded = function_source('RunBounded')
    assert '$Timing.ChildTerminationSeconds' in bounded
    assert bounded.index('Require $process.Empty') < bounded.index('return [int]$process.ExitCode')
    assert bounded.index('$script:terminationConfirmed=$false') < bounded.index('$process.TerminateAndWait($terminationClock,$TerminationSeconds * 1000)') < bounded.index('$script:terminationConfirmed=$true')
    assert '$terminated -and $terminationClock.Elapsed.TotalSeconds -le $TerminationSeconds' in bounded
    assert 'process tree termination UNCONFIRMED' in bounded
    assert 'finally { $process.Dispose() }' in bounded
    supervisor = source.split('if ($Worker -and -not $Phase) {', 1)[1].split('\nif ($Worker) {', 1)[0]
    assert supervisor.index('Require $script:terminationConfirmed') < supervisor.index('WaitInstallerIdle') < supervisor.index('$receipt.cleanup_exit=RunBounded')
    assert '$receipt.success=$false' in supervisor
    idle = function_source('WaitInstallerIdle')
    for token in ["[Threading.Mutex]::OpenExisting('Global\\_MSIExecute')",
                  '[Threading.WaitHandleCannotBeOpenedException] { return }',
                  '$mutex.WaitOne(0)', '[Threading.AbandonedMutexException]',
                  '$mutex.ReleaseMutex()', '$mutex.Dispose()',
                  '$clock.Elapsed.TotalSeconds -lt $Timing.InstallerIdleSeconds',
                  'Windows Installer idle UNCONFIRMED']:
        assert token in idle, token
    assert 'New-Object Threading.Mutex' not in idle


def test_termination_is_first_operation_and_has_no_process_enumeration():
    source = PROOF.read_text(encoding='utf-8')
    native = source.split("Add-Type -TypeDefinition @'\n", 1)[1].split("\n'@", 1)[0]
    termination = native.split('public bool TerminateAndWait(Stopwatch clock,int milliseconds) {', 1)[1].split('\n    public void Dispose()', 1)[0]
    # The assigned-job branch must terminate immediately through its retained
    # handle, before any query, logging, clock setup, or other diagnostic work.
    assert termination.lstrip().startswith('if (assigned) { Check(TerminateJobObject(job,1)); }')
    assert termination.index('TerminateJobObject(job,1)') < termination.index('while (clock.Elapsed.TotalMilliseconds<milliseconds)') < termination.index('if (Empty) return true;')
    assert 'StartNew' not in termination and 'clock=' not in termination
    # Every RunBounded failure uses that same clock and existing Timing bound.
    failure = function_source('RunBounded').split('} catch {\n', 1)[1]
    before_call, after_call = failure.split('$terminated=$process.TerminateAndWait($terminationClock,$TerminationSeconds * 1000)', 1)
    assert before_call.strip() == '''$failure=$_.Exception.Message
        $script:terminationConfirmed=$false
        $terminationClock=[Diagnostics.Stopwatch]::StartNew()
        try {'''
    assert after_call.lstrip().startswith('Require ($terminated -and $terminationClock.Elapsed.TotalSeconds -le $TerminationSeconds)')
    assert source.count('.TerminateAndWait(') == 1
    for forbidden in ('ParentPidTree', 'CreateToolhelp32Snapshot', 'Process32First',
                      'Process32Next', 'OpenProcess(', 'IsProcessInJob',
                      'struct Entry', 'uint root', 'Get-Process', 'GetProcesses(',
                      'Win32_Process', 'System.Collections.Generic'):
        assert forbidden not in source, forbidden


def test_registry_evidence_contains_only_sanitized_differences_never_data():
    source = PROOF.read_text(encoding='utf-8')
    assert 'registry-before-' not in source
    comparison = function_source('RegistryRestored')
    assert "$sanitized='equal'" in comparison
    assert 'if ($differences.Count) { $sanitized=$differences }' in comparison
    assert 'ConvertTo-Json -InputObject $sanitized -Depth 10 | Set-Content -LiteralPath $comparisonFile' in comparison
    differences = function_source('RegistryDifferences')
    for token in ["$change='removed'", "$change='changed'", "change='added'",
                  '$entry.signature -cne $new[$id].signature']:
        assert token in differences
    projections = re.findall(r'\[pscustomobject\]\[ordered\]@\{([^}]+)\}', differences)
    assert len(projections) == 2
    assert all(re.findall(r'(\w+)=', fields) == ['key_path', 'value_name', 'change'] for fields in projections)
    # Every file-writing line is reviewed here. New sinks fail closed rather
    # than allowing a multiline snapshot/value pipeline to escape a denylist.
    writes = [line.strip() for line in source.splitlines() if re.search(
        r'\b(?:Set-Content|Add-Content|Out-File|Export-\w+|Copy-Item|Move-Item)\b|'
        r'\[IO\.File\]::|StreamWriter|WriteAll|AppendAll|(?:^|\s)(?:\*|\d)?>{1,2}(?:\s|$)', line)]
    assert writes == [
        'ConvertTo-Json -InputObject $sanitized -Depth 10 | Set-Content -LiteralPath $comparisonFile -Encoding UTF8',
        '$Value | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $temporary -Encoding UTF8',
        'Move-Item -LiteralPath $temporary -Destination (Join-Path $ProofDirectory $Name)',
        "$receipt | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $ProofDirectory 'worker-start.json') -Encoding UTF8",
        "$receipt | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $ProofDirectory 'install-start.json') -Encoding UTF8",
        "Copy-Item -LiteralPath $diagnostic -Destination (Join-Path $ProofDirectory 'check.receipt.txt')",
        "Copy-Item -LiteralPath $Manifest -Destination (Join-Path $ProofDirectory 'manifest.json')",
        "$summary | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $ProofDirectory 'parent.json') -Encoding UTF8",
    ]
    # Native file handles are exclusively child stdout/stderr and NUL, never
    # registry material. Receipts and messages cannot acquire raw baselines.
    assert 'input=Stream(null,true); output=Stream(stdout,false); error=Stream(stderr,false)' in source
    assert source.count('=CreateFile(') == 1
    registry_variables = r'\$(?:\w*Before|after|old|new|state|Tree|Entries|entry|value|actual|Expected)\b|\.data\b|\.signature\b|GetValue\('
    assert re.findall(r'^\s+AtomicReceipt (.*)$', source, re.M) == ['$receipt', "$receipt 'phase.json'"]
    for line in source.splitlines():
        if line.strip() == '$Value | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $temporary -Encoding UTF8':
            continue  # AtomicReceipt's two callers above supply only receipts.
        if re.search(r'Set-Content|Write-Host|AtomicReceipt \$receipt|\$receipt\.\w+=', line):
            # AtomicReceipt's generic parameter is always passed a receipt;
            # preflight interpolates only key paths and value names.
            assert not re.search(registry_variables, line, re.I), line
    association = function_source('NoAssociationValue')
    assert '$($Tree.path) / $($value.name)' in association
    assert '$($value.data)' not in source


def test_process_tree_native_bridge_compiles_without_running_it(tmp_path):
    import shutil
    import subprocess

    pwsh = shutil.which('pwsh')
    if pwsh is None:
        pytest.skip('existing PowerShell compiler unavailable; Windows runtime unproven')
    native = PROOF.read_text(encoding='utf-8').split("Add-Type -TypeDefinition @'\n", 1)[1].split("\n'@", 1)[0]
    compiler = tmp_path / 'compile-only.ps1'
    compiler.write_text("$ErrorActionPreference='Stop'\nAdd-Type -TypeDefinition @'\n" + native + "\n'@\n")
    result = subprocess.run([pwsh, '-NoProfile', '-NonInteractive', '-File', str(compiler)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize('sign,msi_uploaded', [('true', True), ('false', False)])
def test_unsigned_msi_is_proved_but_not_distributed(sign, msi_uploaded):
    text = WORKFLOW.read_text(encoding='utf-8')
    upload = text.split('          name: Annotshot-windows\n', 1)[1]
    paths = upload.split('          path: |\n', 1)[1].split('          if-no-files-found:', 1)[0]
    lines = [line.strip() for line in paths.splitlines() if line.strip()]
    assert lines == ['Annotshot-*-windows.zip', 'Annotshot-*-setup.exe', 'Annotshot-*.msix',
                     "${{ env.SIGN == 'true' && 'Annotshot-*.msi' || '' }}"]
    assert '          if-no-files-found: error\n' in upload
    # Static evaluation of the guarded path; all existing paths stay unconditional.
    selected = lines[:3] + (['Annotshot-*.msi'] if sign == 'true' else [])
    assert ('Annotshot-*.msi' in selected) is msi_uploaded
    assert text.count('            Annotshot-*.msi\n') == 0
    for name in ('MSI build (Windows)', 'MSI proof (Windows)'):
        assert 'if:' not in step(name)


def test_powershell_syntax_only_when_existing_parser_available(tmp_path):
    """Parse only, never execute the helper or workflow bodies, even on Windows."""
    import shutil
    import subprocess
    pwsh = shutil.which('pwsh')
    if pwsh is None:
        pytest.skip('existing PowerShell parser unavailable; Windows runtime remains unproven')
    paths = [str(PROOF)]
    workflow = WORKFLOW.read_text(encoding='utf-8')
    for match in re.finditer(r'^        shell: pwsh\n(?:(?!^      - ).)*?^        run: \|\n((?:          [^\n]*\n|\n)+)', workflow, re.M | re.S):
        script = '\n'.join(line[10:] for line in match.group(1).splitlines())
        script = re.sub(r'\$\{\{.*?\}\}', 'fixture', script)
        path = tmp_path / f'step-{len(paths)}.ps1'
        path.write_text(script)
        paths.append(str(path))
    assert len(paths) >= 8
    parser = tmp_path / 'parse-only.ps1'
    parser.write_text("""param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Paths)
$ErrorActionPreference = 'Stop'
foreach ($path in $Paths) {
    $tokens=$null; $errors=$null
    $null=[System.Management.Automation.Language.Parser]::ParseFile($path, [ref]$tokens, [ref]$errors)
    if ($errors.Count) { $errors | ForEach-Object { Write-Output ($path + ': ' + $_.Message) }; exit 1 }
}
""")
    result = subprocess.run([pwsh, '-NoProfile', '-NonInteractive', '-File', str(parser), *paths], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
