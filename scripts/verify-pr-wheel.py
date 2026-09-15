"""Check PR #10146's installed Windows wheel: stubs, imports and DLL bundling."""
import ast
import ctypes
import hashlib
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import sys
import traceback
import zipfile

DOMAINS = ('kernel metadata chemistry analysis featurefinder format processing '
           'datastructures ml misc spectrum chromatogram experiment').split()
ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / 'reports/pr-wheel-validation.json'


def main():
    result = {'status': 'failed', 'python': sys.version, 'checks': {},
              'source': json.loads((ROOT / 'reports/pr-wheel-source.json').read_text(encoding='utf-8-sig'))}
    errors = []

    def check(name, fn):
        try:
            result['checks'][name] = {'status': 'passed', 'detail': fn()}
        except Exception:
            detail = traceback.format_exc()
            result['checks'][name] = {'status': 'failed', 'detail': detail}
            errors.append(name)
            print(detail)

    # Remove runner tool/contrib paths before the first native import. Python's
    # own runtime and Windows remain available; this is not a source build tree.
    for name in ('PYOPENMS_DLL_PATH', 'PYTHONPATH', 'OPENMS_DATA_PATH', 'OpenMS_ROOT', 'CMAKE_PREFIX_PATH'):
        os.environ.pop(name, None)
    system = Path(os.environ['SystemRoot'])
    os.environ['PATH'] = os.pathsep.join(map(str, [Path(sys.executable).parent,
        Path(sys.base_prefix), Path(sys.base_prefix) / 'DLLs', system / 'System32', system]))
    result['test_path'] = os.environ['PATH']
    dist = importlib.metadata.distribution('pyopenms')
    package = Path(dist.locate_file('pyopenms')).resolve()
    result['package'] = str(package)
    result['version'] = dist.version
    wheel = Path((ROOT / 'reports/pr-wheel-path.txt').read_text(encoding='utf-8-sig').strip())

    def provenance():
        actual = hashlib.sha256(wheel.read_bytes()).hexdigest()
        assert actual == result['source']['wheel_sha256'], (actual, result['source'])
        direct = json.loads(dist.read_text('direct_url.json'))
        assert direct['archive_info']['hashes']['sha256'] == actual, direct
        return {'installed_wheel_sha256': actual, 'direct_url': direct['url']}

    def imports():
        modules = [f'_pyopenms_{d}' for d in DOMAINS] + ['_pyopenms', '_arrow_zerocopy']
        loaded, failed = {}, {}
        for name in modules:
            try:
                mod = importlib.import_module(f'pyopenms.{name}')
                path = Path(mod.__file__).resolve()
                assert path.parent == package, path
                loaded[name] = str(path)
            except Exception:
                failed[name] = traceback.format_exc()
        assert not failed, failed
        return loaded

    def stubs():
        with zipfile.ZipFile(wheel) as archive:
            names = archive.namelist()
            assert 'pyopenms/py.typed' in names
            expected = ['pyopenms/__init__.pyi'] + [f'pyopenms/_pyopenms_{d}.pyi' for d in DOMAINS]
            assert all(n in names for n in expected), [n for n in expected if n not in names]
            stubs = [n for n in names if n.startswith('pyopenms/') and n.endswith('.pyi')]
            definitions = 0
            for name in stubs:
                data = archive.read(name)
                assert package.joinpath(*Path(name).parts[1:]).read_bytes() == data, name
                tree = ast.parse(data.decode('utf-8'), filename=name)
                definitions += sum(isinstance(n, (ast.ClassDef, ast.FunctionDef)) for n in ast.walk(tree))
            assert definitions > 0
            return {'files': len(stubs), 'definitions': definitions, 'names': stubs}

    def dependencies():
        import pefile
        binaries = [Path(dist.locate_file(p)).resolve() for p in dist.files
                    if str(p).lower().endswith(('.dll', '.pyd'))]
        closure = {}
        for binary in binaries:
            with pefile.PE(str(binary), fast_load=True) as pe:
                pe.parse_data_directories(directories=[1, 13])
                deps = [d.dll.decode('ascii') for attr in ('DIRECTORY_ENTRY_IMPORT', 'DIRECTORY_ENTRY_DELAY_IMPORT')
                        for d in getattr(pe, attr, [])]
                closure[binary.name] = deps
        (ROOT / 'reports/wheel-pe-imports.json').write_text(json.dumps(closure, indent=2), encoding='utf-8')
        unwanted = [n for n in list(closure) + [d for deps in closure.values() for d in deps]
                    if re.match(r'zlib1(?:-|\.)', n, re.I)]
        assert not unwanted, unwanted
        curls = [b for b in binaries if re.match(r'libcurl(?:-|\.)', b.name, re.I)]
        assert len(curls) == 1, curls
        openms = [(n, deps) for n, deps in closure.items() if re.match(r'OpenMS(?:-|\.)', n, re.I)]
        assert len(openms) == 1 and curls[0].name.lower() in [d.lower() for d in openms[0][1]], openms
        lib = ctypes.CDLL(str(curls[0]))
        lib.curl_version.restype = ctypes.c_char_p
        lib.curl_version.argtypes = []
        version = lib.curl_version().decode('ascii')
        expected = os.environ.get('LAB_EXPECTED_CURL', '').strip()
        if expected:
            assert version.split()[0] == f'libcurl/{expected}', version
        return {'binary_count': len(binaries), 'curl_dll': str(curls[0]),
                'curl_version': version, 'zlib1_absent': True, 'openms_imports': openms[0][1]}

    check('exact_installed_artifact', provenance)
    check('all_15_extension_imports', imports)
    check('packaged_utf8_stubs', stubs)
    check('bundled_curl_and_zlib', dependencies)
    result['status'] = 'failed' if errors else 'passed'
    REPORT.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a', encoding='utf-8') as f:
            f.write('\n## PR wheel checks\n\n')
            for name, info in result['checks'].items():
                f.write(f"- {name}: **{info['status']}**\n")
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
