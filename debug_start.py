#!/usr/bin/env python3
import sys
import traceback
import os

sys.path.insert(0, '/home/butter/dev/PokeSim-Agent')
sys.path.insert(0, '/tmp/opencode/pokesim-upstream')
sys.path.insert(0, '/tmp/opencode/pokesim-libs')

try:
    print("DEBUG: Starting imports...", flush=True)
    import pokesim
    print(f"DEBUG: pokesim {pokesim.__version__} imported", flush=True)
    
    print("DEBUG: Importing manager...", flush=True)
    from pokesim.app import manager
    print("DEBUG: Manager imported OK", flush=True)
    
    print("DEBUG: Creating manager instance...", flush=True)
    import tempfile
    d = '/tmp/pokesim-debug-start'
    os.makedirs(d, exist_ok=True)
    m = manager.Manager(d, 'http://127.0.0.1:8000')
    print("DEBUG: Manager created OK", flush=True)
    
    print("DEBUG: Creating app...", flush=True)
    app = manager.create_app(m)
    print("DEBUG: App created OK", flush=True)
    
    m.close()
    print("DEBUG: All OK!", flush=True)
    
except Exception as e:
    print(f"FATAL ERROR: {e}", flush=True)
    traceback.print_exc()
    sys.exit(1)
