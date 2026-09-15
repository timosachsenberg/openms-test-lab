"""Exercise native imports, NumPy interoperability, and mzML read/write."""
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import sys
import traceback


def main():
    report_dir = Path('reports')
    report_dir.mkdir(exist_ok=True)
    result = {'python': sys.version, 'executable': sys.executable,
              'platform': platform.platform(), 'status': 'failed'}
    try:
        result['packages'] = {d.metadata['Name']: d.version for d in importlib.metadata.distributions()}
        if not os.environ.get('LAB_PYOPENMS_SPEC', 'pyopenms').strip():
            result['status'] = 'skipped'
            return
        import numpy as np
        import pyopenms as oms
        result['pyopenms'] = oms.__version__
        result['module'] = oms.__file__
        mass = oms.AASequence.fromString('PEPTIDE').getMonoWeight()
        assert 799 < mass < 800, mass
        spectrum = oms.MSSpectrum()
        spectrum.setMSLevel(1)
        spectrum.setRT(12.5)
        mz = np.array([100.0, 200.0, 300.0], dtype=np.float64)
        intensities = np.array([10.0, 20.0, 30.0], dtype=np.float32)
        spectrum.set_peaks((mz, intensities))
        experiment = oms.MSExperiment()
        experiment.addSpectrum(spectrum)
        mzml = report_dir / 'smoke.mzML'
        oms.MzMLFile().store(str(mzml), experiment)
        restored = oms.MSExperiment()
        oms.MzMLFile().load(str(mzml), restored)
        assert restored.size() == 1
        np.testing.assert_allclose(restored[0].get_peaks()[0], mz)
        np.testing.assert_allclose(restored[0].get_peaks()[1], intensities)
        result.update(status='passed', peptide_mass=mass, spectra=restored.size())
    except Exception:
        result['error'] = traceback.format_exc()
        raise
    finally:
        (report_dir / 'python-smoke.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
