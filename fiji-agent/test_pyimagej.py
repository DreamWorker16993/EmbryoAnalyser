import json
import sys
import time
from environment import ROOT, FIJI, JAVA, configure
configure()
import imagej
import scyjava
import numpy as np

start = time.monotonic()
scyjava.config.add_option('-Xmx2g')
ij = imagej.init(str(FIJI), mode='headless')
try:
    assert ij.ui().isHeadless()
    pixels = np.arange(64, dtype=np.uint16).reshape(8, 8)
    dataset = ij.py.to_dataset(pixels)
    restored = np.asarray(ij.py.from_java(dataset))
    assert np.array_equal(pixels, restored)
    ij.py.run_macro('newImage("Fiji-agent-smoke", "8-bit black", 8, 8, 1); setPixel(2, 3, 123);')
    from scyjava import jimport
    imp = jimport('ij.WindowManager').getCurrentImage()
    assert imp is not None
    assert int(imp.getProcessor().getPixel(2, 3)) == 123
    result = {'passed': True, 'python': sys.version, 'imagej': str(ij.getVersion()),
              'fiji': str(FIJI), 'java_home': str(JAVA), 'headless': True,
              'numpy_roundtrip': True, 'macro_pixel': 123,
              'seconds': round(time.monotonic() - start, 2)}
    (ROOT / 'pyimagej-test-result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2), flush=True)
    imp.close()
finally:
    ij.dispose()
