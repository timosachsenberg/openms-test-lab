"""Inventory Windows package DLLs, imports, symbol coverage and real load paths.

A DLL found in System32 is not automatically an OS component. MSVC runtime
families are classified first, and their preinstalled versions are recorded.
Static candidates describe availability; runtime traces establish loaded paths.
"""
import argparse
from collections import Counter, defaultdict
import csv
import ctypes as c
from ctypes import wintypes as w
from functools import lru_cache
import hashlib
import importlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import traceback

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / 'reports'
SYSTEM = Path(os.environ['SystemRoot']) / 'System32'
VC = re.compile(r'^(?:msvcp|msvcr|vcruntime|concrt|vcomp|vccorlib|vcamp|mfc|mfcm)\d', re.I)
DEBUG = re.compile(r'^(?:msvcp\d+(?:_\d+)?d|msvcr\d+d|vcruntime\d+(?:_\d+)?d|concrt\d+d|vcomp\d+d|ucrtbased)(?:-|\.)', re.I)


def save(name, data):
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / name).write_text(json.dumps(data, indent=2), encoding='utf-8')


def clean_environment():
    env = os.environ.copy()
    for name in list(env):
        if name.upper() in {'PYTHONPATH', 'PYOPENMS_DLL_PATH', 'OPENMS_DATA_PATH', 'OPENMS_ROOT',
                            'CMAKE_PREFIX_PATH', 'QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH'}:
            env.pop(name)
    env['PATH'] = os.pathsep.join(map(str, [Path(sys.executable).parent, Path(sys.base_prefix),
        Path(sys.base_prefix) / 'DLLs', SYSTEM, SYSTEM.parent]))
    return env


def loaded_modules():
    k = c.WinDLL('kernel32', use_last_error=True)
    k.GetCurrentProcess.restype = w.HANDLE
    k.K32EnumProcessModules.argtypes = [w.HANDLE, c.POINTER(w.HMODULE), w.DWORD, c.POINTER(w.DWORD)]
    k.K32EnumProcessModules.restype = w.BOOL
    k.K32GetModuleFileNameExW.argtypes = [w.HANDLE, w.HMODULE, w.LPWSTR, w.DWORD]
    k.K32GetModuleFileNameExW.restype = w.DWORD
    modules = (w.HMODULE * 4096)()
    needed = w.DWORD()
    handle = k.GetCurrentProcess()
    if not k.K32EnumProcessModules(handle, modules, c.sizeof(modules), c.byref(needed)):
        raise c.WinError(c.get_last_error())
    assert needed.value <= c.sizeof(modules)
    paths = []
    for module in modules[:needed.value // c.sizeof(w.HMODULE)]:
        buffer = c.create_unicode_buffer(32768)
        if k.K32GetModuleFileNameExW(handle, module, buffer, len(buffer)):
            paths.append(buffer.value)
    return sorted(set(paths), key=str.lower)


def python_probe():
    result = {'python': sys.version, 'executable': sys.executable, 'base_prefix': sys.base_prefix,
              'path': os.environ['PATH'], 'before': loaded_modules(), 'imports': {}}
    domains = 'kernel metadata chemistry analysis featurefinder format processing datastructures ml misc spectrum chromatogram experiment'.split()
    names = ['numpy', 'matplotlib._path', 'nanobind_backend', 'pyopenms']
    names += [f'pyopenms._pyopenms_{d}' for d in domains] + ['pyopenms._pyopenms', 'pyopenms._arrow_zerocopy']
    for name in names:
        try:
            mod = importlib.import_module(name)
            result['imports'][name] = {'status': 'passed', 'path': getattr(mod, '__file__', '')}
        except Exception:
            result['imports'][name] = {'status': 'failed', 'error': traceback.format_exc()}
    result['after'] = loaded_modules()
    result['new_loads'] = sorted(set(result['after']) - set(result['before']))
    save('python-loaded-modules.json', result)
    print(f"Recorded {len(result['after'])} actual Python process modules")
    return int(any(v['status'] == 'failed' for v in result['imports'].values()))


@lru_cache(maxsize=None)
def binary(path):
    import pefile
    path = Path(path)
    record = {'path': str(path), 'name': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
              'bytes': path.stat().st_size, 'imports': [], 'file_version': None, 'product': None}
    try:
        with pefile.PE(str(path), fast_load=True) as pe:
            pe.parse_data_directories(directories=[1, 2, 13])
            record['machine'] = hex(pe.FILE_HEADER.Machine)
            record['linker_version'] = f'{pe.OPTIONAL_HEADER.MajorLinkerVersion}.{pe.OPTIONAL_HEADER.MinorLinkerVersion}'
            record['managed'] = bool(pe.OPTIONAL_HEADER.DATA_DIRECTORY[14].VirtualAddress)
            record['clr_flags'] = pe.get_dword_at_rva(pe.OPTIONAL_HEADER.DATA_DIRECTORY[14].VirtualAddress + 16) if record['managed'] else 0
            # IL-only AnyCPU assemblies inherit the 64-bit test process architecture.
            record['load_machine'] = '0x8664' if record['managed'] and record['clr_flags'] & 1 and not record['clr_flags'] & 2 else record['machine']
            record['manifests'] = []
            for resource in getattr(getattr(pe, 'DIRECTORY_ENTRY_RESOURCE', None), 'entries', []):
                if resource.id == 24:
                    for identity in resource.directory.entries:
                        for language in identity.directory.entries:
                            data = language.data.struct
                            record['manifests'].append(pe.get_data(data.OffsetToData, data.Size).decode('utf-8', 'replace'))
            for attr, delay in [('DIRECTORY_ENTRY_IMPORT', False), ('DIRECTORY_ENTRY_DELAY_IMPORT', True)]:
                for dep in getattr(pe, attr, []):
                    record['imports'].append({'dll': dep.dll.decode('ascii'), 'delay': delay,
                        'symbols': [symbol.name.decode('ascii') if symbol.name else f'#{symbol.ordinal}' for symbol in dep.imports]})
            for group in getattr(pe, 'FileInfo', []):
                for entry in group:
                    for table in getattr(entry, 'StringTable', []):
                        values = {k.decode('utf-8', 'replace'): v.decode('utf-8', 'replace') for k, v in table.entries.items()}
                        record['file_version'] = values.get('FileVersion', record['file_version'])
                        record['product'] = values.get('ProductName', record['product'])
            fixed = getattr(pe, 'VS_FIXEDFILEINFO', [])
            if fixed:
                info = fixed[0]
                record['numeric_version'] = [info.FileVersionMS >> 16, info.FileVersionMS & 65535,
                                              info.FileVersionLS >> 16, info.FileVersionLS & 65535]
    except Exception as exc:
        record['parse_error'] = str(exc)
    return record


@lru_cache(maxsize=None)
def exports(path):
    import pefile
    with pefile.PE(path, fast_load=True) as pe:
        pe.parse_data_directories(directories=[0])
        names = set()
        for sym in getattr(getattr(pe, 'DIRECTORY_ENTRY_EXPORT', None), 'symbols', []):
            names.add(f'#{sym.ordinal}')
            if sym.name:
                names.add(sym.name.decode('ascii'))
        return names


def is_os_dll(path):
    name = Path(path).name.lower()
    if VC.match(name) or name == 'ucrtbased.dll':
        return False
    product = binary(str(path)).get('product') or ''
    # These documented Windows APIs retain Internet Explorer branding in resources.
    return name in {'ucrtbase.dll', 'wininet.dll', 'urlmon.dll'} or bool(re.search(r'windows.*operating system', product, re.I))


def audit(native_only=False):
    owners, paths, versions = {}, {}, {}
    for dist in ([] if native_only else metadata.distributions()):
        owner = dist.metadata.get('Name', 'unknown')
        versions[owner] = dist.version
        for file in dist.files or []:
            if Path(file).suffix.lower() in ('.dll', '.pyd', '.exe'):
                path = Path(dist.locate_file(file)).resolve()
                if path.is_file():
                    owners[str(path).lower()] = owner
                    paths[str(path)] = owner
    native_root = Path('C:/OpenMS')
    if native_only and not native_root.exists():
        raise RuntimeError('Native-only audit requires the installed package at C:/OpenMS')
    if native_root.exists():
        for path in native_root.rglob('*'):
            if path.is_file() and path.suffix.lower() in ('.dll', '.pyd', '.exe'):
                paths[str(path.resolve())] = 'OpenMS-desktop'
                owners[str(path.resolve()).lower()] = 'OpenMS-desktop'
    records = [dict(binary(path), owner=owner) for path, owner in paths.items()]
    by_owner = defaultdict(lambda: defaultdict(list))
    for item in records:
        by_owner[item['owner']][item['name'].lower()].append(item['path'])
    python_files = []
    for directory in (Path(sys.base_prefix), Path(sys.base_prefix) / 'DLLs'):
        python_files += list(directory.glob('*.dll')) + list(directory.glob('*.pyd'))
    python_map = {p.name.lower(): str(p) for p in python_files}
    save('python-runtime-binaries.json', [binary(str(p)) for p in python_files])

    edges, symbol_issues = [], []
    for item in records:
        for dependency in item['imports']:
            name = dependency['dll'].lower()
            available = [p for p in by_owner[item['owner']].get(name, [])
                         if binary(p).get('load_machine') == item.get('load_machine')]
            system_dir = SYSTEM if item.get('load_machine') == '0x8664' else SYSTEM.parent / 'SysWOW64'
            system_candidate = system_dir / name
            provider, classification = None, None
            if name.startswith(('api-ms-', 'ext-ms-')):
                classification = 'windows-api-set'
            elif available:
                # Presence alone does not prove the loader searches this folder.
                provider = next((p for p in available if Path(p).parent == Path(item['path']).parent), available[0])
                classification = 'bundled-same-directory' if Path(provider).parent == Path(item['path']).parent else 'bundled-other-directory'
            elif item['owner'] != 'OpenMS-desktop' and name in python_map and binary(python_map[name]).get('load_machine') == item.get('load_machine'):
                provider, classification = python_map[name], 'python-runtime'
            elif system_candidate.is_file() and binary(str(system_candidate)).get('load_machine') == item.get('load_machine'):
                provider = str(system_candidate)
                classification = 'preinstalled-msvc-runtime' if VC.match(name) else ('windows-component' if is_os_dll(provider) else 'preinstalled-non-os')
            else:
                classification = 'not-in-package-python-or-system32'
            edge = {'owner': item['owner'], 'importer': item['path'], 'dependency': dependency['dll'],
                    'delay': dependency['delay'], 'classification': classification, 'candidate': provider,
                    'bundle_candidates': available, 'msvc': bool(VC.match(name)), 'symbol_count': len(dependency['symbols'])}
            if provider and VC.match(name):
                edge['candidate_version'] = binary(provider)['file_version']
                missing = sorted(set(dependency['symbols']) - exports(provider))
                edge['missing_exports'] = missing
                if missing:
                    symbol_issues.append(edge)
            edges.append(edge)

    # Side-by-side presence is evidence of a runner prerequisite, not proof that
    # the activation context selects it. Preserve unresolved edges for review.
    sxs_names = {e['dependency'].lower() for e in edges if e['classification'] == 'not-in-package-python-or-system32' and e['msvc']}
    sxs_matches = []
    for directory in (SYSTEM.parent / 'WinSxS').glob('*_microsoft.vc*'):
        if directory.is_dir():
            for name in sxs_names:
                path = directory / name
                if path.is_file():
                    info = binary(str(path))
                    sxs_matches.append({k: info.get(k) for k in ('path', 'name', 'machine', 'file_version', 'sha256')})
    save('side-by-side-runtime-candidates.json', sxs_matches)

    python_trace = {'after': [], 'imports': {}} if native_only else json.loads((REPORTS / 'python-loaded-modules.json').read_text(encoding='utf-8'))
    runtime = []

    def loaded_record(path, process):
        if not Path(path).is_file():
            return {'path': path, 'process': process, 'provider': 'file-unavailable'}
        info = binary(path)
        owner = owners.get(str(Path(path).resolve()).lower())
        if owner:
            provider = owner
        elif Path(path).resolve().is_relative_to(Path(sys.base_prefix).resolve()):
            provider = 'python-runtime'
        elif VC.match(Path(path).name):
            provider = 'preinstalled-msvc-runtime'
        elif Path(path).resolve().is_relative_to(SYSTEM.parent.resolve()):
            provider = 'windows-component' if is_os_dll(path) else 'preinstalled-non-os'
        else:
            provider = 'external-to-audited-packages'
        return {k: info.get(k) for k in ('path', 'name', 'file_version', 'numeric_version', 'sha256', 'product')} | {
            'process': process, 'provider': provider, 'msvc': bool(VC.match(Path(path).name))}

    runtime += [loaded_record(p, 'python') for p in python_trace['after']]
    native_trace = None
    fileinfos = list(native_root.rglob('FileInfo.exe')) if native_root.exists() else []
    if native_only and len(fileinfos) != 1:
        raise RuntimeError('Native-only audit requires exactly one FileInfo.exe')
    if fileinfos:
        env = clean_environment()
        env['PATH'] = os.pathsep.join(map(str, [fileinfos[0].parent, SYSTEM, SYSTEM.parent]))
        process = subprocess.run([sys.executable, str(ROOT / 'scripts/trace-native.py'), str(fileinfos[0]),
            str(REPORTS / 'native-loaded-modules.json'), '--help'], env=env, cwd=ROOT,
            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=90)
        (REPORTS / 'native-trace.log').write_text(process.stdout + process.stderr, encoding='utf-8')
        if (REPORTS / 'native-loaded-modules.json').exists():
            native_trace = json.loads((REPORTS / 'native-loaded-modules.json').read_text(encoding='utf-8'))
            runtime += [loaded_record(p, 'FileInfo') for p in native_trace['loads']]
        else:
            native_trace = {'trace_error': process.stderr, 'exit_code': process.returncode}

    runtime_configs = []
    config_roots = [native_root] if native_root.exists() else []
    if not native_only:
        config_roots.append(Path(metadata.distribution('pyopenms').locate_file('pyopenms')))
    for directory in config_roots:
        for path in directory.rglob('*.runtimeconfig.json'):
            runtime_configs.append({'path': str(path), 'config': json.loads(path.read_text(encoding='utf-8-sig'))})
    save('dotnet-runtime-requirements.json', runtime_configs)
    save('binary-inventory.json', records)
    save('dependency-edges.json', edges)
    save('loaded-module-providers.json', runtime)
    with (REPORTS / 'dependency-edges.csv').open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['owner','importer','dependency','delay','classification','candidate','candidate_version','msvc','symbol_count'], extrasaction='ignore')
        writer.writeheader(); writer.writerows(edges)
    before = json.loads((REPORTS / 'runner-before.json').read_text(encoding='utf-8-sig'))
    after = json.loads((REPORTS / 'runner-after.json').read_text(encoding='utf-8-sig'))
    before_map = {r['name'].lower(): r for r in before['runtimes']}
    runtime_changes = [r for r in after['runtimes'] if r['name'].lower() not in before_map or
                       before_map[r['name'].lower()]['sha256'] != r['sha256']]
    summary = {'native_only': native_only, 'binary_counts': dict(Counter(r['owner'] for r in records)), 'python_packages': versions,
        'dependency_classifications': {owner: dict(Counter(e['classification'] for e in edges if e['owner'] == owner)) for owner in by_owner},
        'bundled_msvc': [{k:r.get(k) for k in ('owner','path','name','file_version','linker_version','sha256')} for r in records if VC.match(r['name'])],
        'external_msvc_dependencies': [e for e in edges if e['msvc'] and not e['classification'].startswith('bundled')],
        'unresolved_dependencies': [e for e in edges if e['classification'] == 'not-in-package-python-or-system32'],
        'preinstalled_non_os_dependencies': [e for e in edges if e['classification'] == 'preinstalled-non-os'],
        'missing_msvc_exports': symbol_issues, 'loaded_msvc': [r for r in runtime if r['msvc']],
        'side_by_side_runtime_candidates': sxs_matches,
        'debug_binaries': [r['path'] for r in records if DEBUG.match(r['name'])],
        'system_runtime_changes_after_installer': runtime_changes,
        'python_import_failures': {k:v for k,v in python_trace['imports'].items() if v['status'] != 'passed'},
        'native_trace_exit': native_trace.get('exit_code') if native_trace else None,
        'limitations': ['Hosted runner is not a bare Windows image.',
            'PATH isolation leaves System32, the Python runtime and already loaded modules available.',
            'Static bundle candidates may need explicit DLL search directories or preloading.',
            'Side-by-side runtime candidates are inventoried; activation contexts and registry COM providers are not resolved.',
            'Runtime traces cover the listed Python imports and FileInfo --help, not all plugin or Thermo RAW paths.',
            'Export checks verify names/ordinals in selected MSVC candidates, not complete ABI compatibility.',
            'Managed assemblies and runtimeconfig requirements are recorded; .NET host discovery is not modeled as PE imports.']}
    save('dll-audit-summary.json', summary)
    print(json.dumps({k:summary[k] for k in ('binary_counts','bundled_msvc','loaded_msvc','unresolved_dependencies','missing_msvc_exports','debug_binaries','native_trace_exit')}, indent=2))
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as f:
            f.write('## DLL audit completed\n\nDownload the audit artifact for exact versions, SHA-256 hashes, PE imports, and observed load paths.\n\n')
            f.write('The hosted runner already contains MSVC and .NET runtimes. Successful execution alone does not establish clean-machine compatibility.\n')
    return int(bool(summary['python_import_failures']) or (native_trace is not None and summary['native_trace_exit'] != 0))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--phase', choices=['python', 'probe', 'audit'], required=True)
    parser.add_argument('--native-only', action='store_true', help='Audit the installed desktop package without importing or requiring pyOpenMS')
    args = parser.parse_args()
    if args.native_only and args.phase != 'audit':
        parser.error('--native-only is only valid with --phase audit')
    if args.phase == 'python':
        result = subprocess.run([sys.executable, __file__, '--phase', 'probe'], env=clean_environment(), cwd=ROOT)
        sys.exit(result.returncode)
    sys.exit(python_probe() if args.phase == 'probe' else audit(args.native_only))

