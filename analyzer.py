"""Wrapper module for tests: expose the functions from python/analyzer.py
so tests can `import analyzer` from the repository root.
"""
import importlib.util
import sys
from pathlib import Path

core_path = Path(__file__).parent / 'python' / 'analyzer.py'
spec = importlib.util.spec_from_file_location('analyzer_core', str(core_path))
analyzer_core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analyzer_core)

# Re-export public names
for name in dir(analyzer_core):
    if not name.startswith('_'):
        globals()[name] = getattr(analyzer_core, name)
