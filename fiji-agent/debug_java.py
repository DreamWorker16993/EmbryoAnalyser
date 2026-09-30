import logging
import runpy
logging.basicConfig(level=logging.DEBUG)
runpy.run_path('fiji-agent/test_pyimagej.py', run_name='__main__')
