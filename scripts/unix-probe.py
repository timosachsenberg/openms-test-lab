"""Run package smoke tests and record this process's actual loaded libraries."""
import ast
import ctypes
import json
import os
from pathlib import Path
import runpy
import sys
import traceback

root = Path(__file__).resolve().parents[1]
os.chdir(root)
result = {"status": "failed", "stub_files": 0, "stub_errors": []}
try:
    runpy.run_path(str(root / "scripts/smoke.py"), run_name="__main__")
    if os.environ.get("LAB_PYOPENMS_SPEC", "").strip():
        import pyopenms
        for path in Path(pyopenms.__file__).parent.rglob("*.pyi"):
            result["stub_files"] += 1
            try:
                ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except (SyntaxError, UnicodeError) as error:
                result["stub_errors"].append({"path": str(path), "error": str(error)})
        if result["stub_errors"]:
            raise RuntimeError("Invalid packaged Python stubs")
    result["status"] = "passed"
except Exception:
    result["error"] = traceback.format_exc()
    raise
finally:
    try:
        if sys.platform == "darwin":
            dyld = ctypes.CDLL(None)
            dyld._dyld_image_count.restype = ctypes.c_uint32
            dyld._dyld_get_image_name.argtypes = [ctypes.c_uint32]
            dyld._dyld_get_image_name.restype = ctypes.c_char_p
            loaded = sorted({dyld._dyld_get_image_name(i).decode() for i in range(dyld._dyld_image_count())})
        else:
            loaded = sorted({line.split(None, 5)[5].strip() for line in Path("/proc/self/maps").read_text().splitlines()
                             if len(line.split(None, 5)) == 6 and line.split(None, 5)[5].startswith("/")})
        result["loaded_paths"] = loaded
    except Exception:
        result["loader_capture_error"] = traceback.format_exc()
    (root / "reports/python-probe.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
