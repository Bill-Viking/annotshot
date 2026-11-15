"""Windows release signing: workflow guards, order and attached downloads."""
import hashlib
import itertools
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / '.github' / 'workflows' / 'build-windows.yml'
RELEASE = ROOT / '.github' / 'workflows' / 'release.yml'
# SHA-256 of the complete pre-move Windows steps block, including comments/order.
ORIGINAL_WINDOWS_STEPS_SHA256 = 'a15f3a16dcdee6ea4e4228cc66caf33da4f5141ee4d8247f8b1c13898f5ad654'
CONDITION = "((github.event_name == 'push' && startsWith(github.ref, 'refs/tags/v')) || (github.event_name == 'workflow_dispatch' && inputs.sign))"
SIGNER_SUBJECT_SHA256 = '245dc45e91f6a982cc5c39835225e6a18970f589707a56d69a2ba83201f305e0'
SIGNING_STEPS = (
    'Signing settings (Windows)',
    'Azure sign-in (Windows)',
    'Files to sign (Windows)',
    "Sign the app's files (Windows)",
    'Sign the installer (Windows)',
    'Signatures (Windows)',
)
VARIABLES = (
    'AZURE_CLIENT_ID', 'AZURE_TENANT_ID', 'AZURE_SUBSCRIPTION_ID',
    'SIGNING_ENDPOINT', 'SIGNING_ACCOUNT', 'SIGNING_PROFILE',
)


def _read_workflow(path):
    text = path.read_text(encoding='utf-8')
    # Parse too when a YAML reader is already available; never install one.
    try:
        import yaml
    except ImportError:
        parsed = None
    else:
        parsed = yaml.safe_load(text)
    return text, parsed


@pytest.fixture
def workflow():
    return _read_workflow(WORKFLOW)


@pytest.fixture
def release_workflow():
    return _read_workflow(RELEASE)


def _job(text, name):
    match = re.search(rf'^  {re.escape(name)}:\n(.*?)(?=^  \w+:|\Z)',
                      text, re.M | re.S)
    assert match, f'no job {name}'
    return match.group(1)


def _steps(text):
    return re.findall(r'^      - (?:name|uses): (.*?\n.*?)(?=^      - |\Z)',
                      _job(text, 'build_windows'), re.M | re.S)


def _step(text, name):
    found = [s for s in _steps(text) if s.splitlines()[0] == name]
    assert len(found) == 1, f'wanted one step named {name}'
    return found[0]


def test_sign_input_is_boolean_and_defaults_off(release_workflow):
    text, parsed = release_workflow
    dispatch = re.search(r'^  workflow_dispatch:\n(.*?)(?=^\S|^  \w|\Z)',
                         text, re.M | re.S).group(1)
    assert re.search(r'^    inputs:\n      sign:\n', dispatch, re.M)
    assert re.search(r'^        type: boolean$', dispatch, re.M)
    assert re.search(r'^        default: false$', dispatch, re.M)
    assert 'Works only from a ref the release environment allows.' in dispatch
    if parsed is not None:
        # YAML 1.1 readers may read the Actions key "on" as True.
        triggers = parsed.get('on', parsed.get(True))
        sign = triggers['workflow_dispatch']['inputs']['sign']
        assert sign['type'] == 'boolean' and sign['default'] is False


def test_reusable_windows_contract_and_unchanged_steps(workflow):
    text, parsed = workflow
    build = _job(text, 'build_windows')
    header, steps = build.split('    steps:\n', 1)
    assert hashlib.sha256(('    steps:\n' + steps).encode()).hexdigest() == ORIGINAL_WINDOWS_STEPS_SHA256
    assert len(_steps(text)) == 19
    assert re.search(r'^on:\n  workflow_call:\n    inputs:\n      sign:\n        type: boolean\n        required: true\n', text, re.M)
    assert re.findall(r'^  (\w+):$', text.split('jobs:\n', 1)[1], re.M) == ['build_windows']
    assert '    runs-on: windows-latest\n' in header
    assert "    environment: ${{ inputs.sign && 'release' || '' }}\n" in header
    assert "      SIGN: ${{ inputs.sign && 'true' || 'false' }}\n" in header
    assert '      QT_QPA_PLATFORM: offscreen\n' in header
    assert '    defaults:\n      run:\n        shell: bash\n' in header
    assert 'permissions:' not in text  # Permissions are inherited from the caller.
    if parsed is not None:
        triggers = parsed.get('on', parsed.get(True))
        assert triggers == {'workflow_call': {'inputs': {'sign': {'type': 'boolean', 'required': True}}}}
        assert parsed['jobs']['build_windows']['env'] == {
            'QT_QPA_PLATFORM': 'offscreen', 'SIGN': "${{ inputs.sign && 'true' || 'false' }}"}


def test_only_signed_caller_has_oidc(release_workflow):
    text, parsed = release_workflow
    assert '\npermissions:\n  contents: read\n' in text
    for name, signed, display in [('build_windows_signed', True, 'build (windows, signed)'),
                                  ('build_windows', False, 'build (windows)')]:
        job = _job(text, name)
        predicate = CONDITION if signed else '!' + CONDITION
        assert f'    if: ${{{{ {predicate} }}}}\n' in job
        assert f'    name: {display}\n' in job
        assert '    uses: ./.github/workflows/build-windows.yml\n' in job
        assert f'    with:\n      sign: {str(signed).lower()}\n' in job
        assert '    permissions:\n      contents: read\n' in job
        assert ('id-token:' in job) is signed
        assert 'steps:' not in job and 'runs-on:' not in job
        if parsed is not None:
            permissions = {'contents': 'read', **({'id-token': 'write'} if signed else {})}
            assert parsed['jobs'][name]['permissions'] == permissions
            assert parsed['jobs'][name]['with'] == {'sign': signed}
    unix = _job(text, 'build')
    for forbidden in ('id-token:', 'environment:', 'SIGN:', 'Azure/', 'windows-latest'):
        assert forbidden not in unix
    assert re.findall(r'^            label: (\w+)$', unix, re.M) == ['macos', 'linux']
    assert text.count('id-token:') == 1
    assert '      id-token: write\n' in _job(text, 'build_windows_signed')


def _evaluate(expression, replacements):
    for source, value in replacements.items():
        expression = expression.replace(source, repr(value))
    expression = expression.replace('&&', 'and').replace('||', 'or').replace('!', 'not ')
    return eval(expression, {'__builtins__': {}}, {})


@pytest.mark.parametrize('event,ref,requested,expected', [
    ('push', 'refs/tags/v0.4.1', False, True),
    ('push', 'refs/tags/v0.4.1', True, True),
    ('push', 'refs/heads/main', False, False),
    ('workflow_dispatch', 'refs/tags/v0.4.1', False, False),
    ('workflow_dispatch', 'refs/heads/main', False, False),
    ('workflow_dispatch', 'refs/tags/v0.4.1', True, True),
    ('workflow_dispatch', 'refs/heads/main', True, True),
    ('pull_request', 'refs/tags/v0.4.1', True, False),
])
def test_callers_are_exclusive_for_each_event(release_workflow, event, ref, requested, expected):
    text, _ = release_workflow
    for name, runs in [('build_windows_signed', expected), ('build_windows', not expected)]:
        expression = re.search(r'^    if: \$\{\{ (.+) \}\}$', _job(text, name), re.M).group(1)
        assert _evaluate(expression, {
            "startsWith(github.ref, 'refs/tags/v')": ref.startswith('refs/tags/v'),
            'github.event_name': event, 'inputs.sign': requested}) is runs


def test_release_requires_successful_signed_windows_and_handles_skipped_unsigned(release_workflow):
    text, parsed = release_workflow
    release = _job(text, 'release')
    assert '    needs: [build, build_windows_signed, build_windows]\n' in release
    expression = re.search(r'^    if: \$\{\{ (.+) \}\}$', release, re.M).group(1)
    assert '!cancelled()' in expression  # Overrides the implicit success() on a skipped need.
    # Evaluate the actual source predicate across all dependency results and events.
    # This is a constrained static check, not GitHub expression-engine execution.
    results = ('success', 'failure', 'cancelled', 'skipped')
    for event, tag, cancelled, unix, signed, unsigned in itertools.product(
            ('push', 'workflow_dispatch', 'pull_request'), (False, True), (False, True),
            results, results, results):
        actual = _evaluate(expression, {
            'cancelled()': cancelled,
            "startsWith(github.ref, 'refs/tags/v')": tag,
            'github.event_name': event,
            'needs.build.result': unix,
            'needs.build_windows_signed.result': signed,
            'needs.build_windows.result': unsigned})
        assert actual is (event == 'push' and tag and not cancelled
                          and unix == signed == 'success' and unsigned == 'skipped')
    if parsed is not None:
        assert parsed['jobs']['release']['needs'] == ['build', 'build_windows_signed', 'build_windows']


def test_all_azure_actions_are_gated_by_sign(workflow):
    text, parsed = workflow
    actions = [s for s in _steps(text) if re.search(r'^        uses: Azure/', s, re.M)]
    assert len(actions) == 3
    for step in actions:
        assert re.search(r"^        if: env.SIGN == 'true'$", step, re.M)
    if parsed is not None:
        for job in parsed['jobs'].values():
            for step in job['steps']:
                if step.get('uses', '').startswith('Azure/'):
                    assert step['if'] == "env.SIGN == 'true'"


def test_signing_steps_keep_the_ruled_order_and_gates(workflow):
    text, parsed = workflow
    names = [s.splitlines()[0] for s in _steps(text)]
    order = (
        'Build', 'Frozen self-check', 'Licence texts and the manual in the bundle',
        *SIGNING_STEPS[:4], 'Installer build (Windows)', SIGNING_STEPS[4],
        'Installer proof (Windows)', SIGNING_STEPS[5], 'MSIX (Windows)', 'Zip (Windows)',
    )
    positions = [names.index(n) for n in order]
    assert positions == sorted(positions)
    assert names[positions[0]:positions[-1] + 1] == list(order)
    for name in SIGNING_STEPS:
        assert "        if: env.SIGN == 'true'\n" in _step(text, name)
    if parsed is not None:
        yaml_names = [s.get('name') for s in parsed['jobs']['build_windows']['steps']]
        assert [yaml_names.index(n) for n in order] == sorted(yaml_names.index(n) for n in order)


def test_installer_is_signed_before_the_installed_copy_is_proven(workflow):
    text, _ = workflow
    assert text.index('- name: Sign the installer (Windows)') < text.index('- name: Installer proof (Windows)')
    build = _step(text, 'Installer build (Windows)')
    proof = _step(text, 'Installer proof (Windows)')
    for step in (build, proof):
        assert "        if: runner.os == 'Windows'\n" in step
        assert "          $v = '${{ steps.version.outputs.version }}'\n" in step
        assert '          $setup = Join-Path $PWD "Annotshot-$v-setup.exe"\n' in step
    assert 'installer built:' in build and '/VERYSILENT' not in build
    for word in ('/VERYSILENT', "'--check'", 'unins000.exe', 'installer OK:'):
        assert word in proof


def test_no_step_prints_repository_variable_values(workflow):
    text, _ = workflow
    # Look at print commands, including interpolated environment and Actions values.
    value = r'(?:\$(?:env:|\{env:)(?:AZURE_|SIGNING_)\w+\}?|\$\{\{\s*vars\.(?:AZURE_|SIGNING_)\w+\s*\}\})'
    for line in text.splitlines():
        if re.search(r'\b(?:Write-Host|echo)\b', line, re.I):
            assert not re.search(value, line), line
    settings = _step(text, SIGNING_STEPS[0])
    assert "Write-Host 'signing settings OK'" in settings
    assert 'Write-Host "STOP signing is on and these repository variables are empty:' in settings
    assert settings.count('Write-Host') == 2


def test_no_signer_subject_or_hash_is_printed(workflow):
    text, _ = workflow
    assert 'signed by: $subject' not in text
    assert "Write-Host 'signer OK: matches the expected identity'" in text
    for line in text.splitlines():
        if re.search(r'\b(?:Write-Host|echo)\b', line, re.I):
            # Check the output argument, not a guard using Subject before it.
            output = re.split(r'\b(?:Write-Host|echo)\b', line, flags=re.I)[1]
            assert not re.search(r'\$(?:subject\b|signerHash\b|signature\.(?:SignerCertificate|TimeStamperCertificate)|env:SIGNER_SUBJECT_SHA256)', output, re.I), line


def test_release_keeps_the_three_attachment_patterns(release_workflow):
    text, parsed = release_workflow
    release = _job(text, 'release')
    files = re.search(r'^          files: \|\n((?:            .+\n)+)', release, re.M).group(1)
    expected = ['zips/*.zip', 'zips/*-setup.exe', 'zips/Annotshot-*.msix']
    assert [line.strip() for line in files.splitlines()] == expected
    assert '    permissions:\n      contents: write\n' in release
    if parsed is not None:
        steps = parsed['jobs']['release']['steps']
        attach = next(s for s in steps if s.get('uses') == 'softprops/action-gh-release@v2')
        assert attach['with']['files'].splitlines() == expected


def test_settings_read_all_six_variables_without_printing_values(workflow):
    text, _ = workflow
    step = _step(text, SIGNING_STEPS[0])
    assert '        shell: pwsh\n' in step
    for name in VARIABLES:
        assert f'          {name}: ${{{{ vars.{name} }}}}\n' in step
        assert f"'{name}'" in step
    assert '[string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($_))' in step
    assert 'if ($missing.Count)' in step and 'exit 1' in step


def test_file_list_preserves_makers_and_stops_on_bad_signatures(workflow):
    text, _ = workflow
    step = _step(text, SIGNING_STEPS[2])
    assert '        id: signlist\n' in step
    assert "Get-ChildItem -LiteralPath 'dist/Annotshot' -Recurse -File" in step
    assert "'.exe', '.dll', '.pyd'" in step
    assert 'Get-AuthenticodeSignature -LiteralPath $file.FullName' in step
    assert "'NotSigned' { $toSign += $file.FullName }" in step
    assert "'Valid' { $makers++ }" in step
    assert 'default { Write-Host "STOP' in step and 'has signature status' in step
    assert '$app -notin $toSign' in step
    assert 'STOP dist/Annotshot/Annotshot.exe must be on the list' in step
    assert '"files<<$delimiter"' in step
    assert '$toSign | Out-File -FilePath $env:GITHUB_OUTPUT' in step
    assert '$delimiter | Out-File -FilePath $env:GITHUB_OUTPUT' in step
    assert '"makers=$makers"' in step


def test_actions_use_the_ruled_inputs_and_absolute_installer_path(workflow):
    text, _ = workflow
    login = _step(text, SIGNING_STEPS[1])
    assert '        uses: Azure/login@v3\n' in login
    for key, name in zip(('client-id', 'tenant-id', 'subscription-id'), VARIABLES[:3]):
        assert f'          {key}: ${{{{ vars.{name} }}}}\n' in login
    for name in (SIGNING_STEPS[3], SIGNING_STEPS[4]):
        step = _step(text, name)
        assert '        uses: Azure/artifact-signing-action@v2\n' in step
        for key, variable in zip(('endpoint', 'signing-account-name', 'certificate-profile-name'), VARIABLES[3:]):
            assert f'          {key}: ${{{{ vars.{variable} }}}}\n' in step
        for setting in ('file-digest: SHA256', 'timestamp-rfc3161: http://timestamp.acs.microsoft.com', 'timestamp-digest: SHA256'):
            assert f'          {setting}\n' in step
    assert '          files: ${{ steps.signlist.outputs.files }}\n' in _step(text, SIGNING_STEPS[3])
    assert r'          files: ${{ github.workspace }}\Annotshot-${{ steps.version.outputs.version }}-setup.exe' in _step(text, SIGNING_STEPS[4])


def test_signature_proof_checks_status_subject_and_timestamps(workflow):
    text, _ = workflow
    step = _step(text, SIGNING_STEPS[5])
    assert "Get-ChildItem -LiteralPath 'dist/Annotshot' -Recurse -File" in step
    assert "'.exe', '.dll', '.pyd'" in step
    assert "if ($signature.Status -ne 'Valid')" in step
    assert 'SIGNED_FILES: ${{ steps.signlist.outputs.files }}' in step
    assert "$signedFiles = @($env:SIGNED_FILES -split '\\r?\\n' | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })" in step
    assert 'foreach ($path in (@($signedFiles) + @($setup)))' in step
    assert '$null -eq $signature.SignerCertificate' in step
    assert '[string]::IsNullOrWhiteSpace($signature.SignerCertificate.Subject)' in step
    assert '$null -eq $signature.TimeStamperCertificate' in step
    assert '[Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($signature.SignerCertificate.Subject))' in step
    assert '[Convert]::ToHexString(' in step and ').ToLowerInvariant()' in step
    assert text.count('SIGNER_SUBJECT_SHA256:') == 1
    assert f'\nenv:\n  SIGNER_SUBJECT_SHA256: {SIGNER_SUBJECT_SHA256}\n' in text
    assert 'if ($signerHash -cne $env:SIGNER_SUBJECT_SHA256) { Write-Host "STOP $path has an unexpected signer identity"; exit 1 }' in step
    assert '$subject =' not in step
    assert "$app =" not in step  # Never derive the expectation from the app.
    assert 'signatures OK: Annotshot.exe, the installer,' in step
    assert "files keep their makers' signatures" in step
    assert "${{ steps.signlist.outputs.makers }}" in step
    assert 'The package itself stays unsigned because the Microsoft Store signs it.' in text
    assert 'On a signed run, the files inside carry our signature.' in text


@pytest.mark.parametrize('case', ['both_executables_wrong_signer', 'unsigned_dll_wrong_signer'])
def test_wrong_signer_rejection_is_inside_the_loop_over_every_selected_file(workflow, case):
    """Source checks on PowerShell, including the verdict's two regressions.

    Valid status and a timestamp cannot bypass the fixed-identity rejection.
    These are static guards, not an Authenticode execution proof.
    """
    text, _ = workflow
    step = _step(text, SIGNING_STEPS[5])
    loop = step.split('foreach ($path in (@($signedFiles) + @($setup))) {', 1)[1]
    loop = loop.split('\n          }', 1)[0]
    expected_lines = [
        '            $signature = Get-AuthenticodeSignature -LiteralPath $path',
        '            if ($signature.Status -ne \'Valid\') { Write-Host "STOP $path has signature status $($signature.Status)"; exit 1 }',
        '            if ($null -eq $signature.SignerCertificate -or [string]::IsNullOrWhiteSpace($signature.SignerCertificate.Subject)) { Write-Host "STOP $path has no signer subject"; exit 1 }',
        '            if ($null -eq $signature.TimeStamperCertificate) { Write-Host "STOP $path has no timestamp"; exit 1 }',
        '            $signerHash = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($signature.SignerCertificate.Subject))).ToLowerInvariant()',
        '            if ($signerHash -cne $env:SIGNER_SUBJECT_SHA256) { Write-Host "STOP $path has an unexpected signer identity"; exit 1 }',
    ]
    assert loop.strip('\n').splitlines() == expected_lines
    selection = _step(text, SIGNING_STEPS[2])
    if case == 'both_executables_wrong_signer':
        assert '$app -notin $toSign' in selection
        assert '$setup = Join-Path $PWD "Annotshot-$v-setup.exe"' in step
    else:
        assert "'.exe', '.dll', '.pyd'" in selection
        assert "'NotSigned' { $toSign += $file.FullName }" in selection
    # Only the earlier all-files loop applies to the preserved maker files.
    maker_loop = step.split('foreach ($file in $files) {', 1)[1].split('\n          }', 1)[0]
    assert 'Status -ne \'Valid\'' in maker_loop
    assert 'SignerCertificate' not in maker_loop and 'TimeStamperCertificate' not in maker_loop
