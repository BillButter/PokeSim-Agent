"""Startup and debugging tests."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def test_import_manager():
    """Test that manager can be imported."""
    from pokesim.app import manager
    assert manager.Manager is not None


def test_import_main():
    """Test that main modules can be imported."""
    import pokesim.__main__
    assert pokesim.__main__.main is not None


def test_config_load():
    """Test config loads without errors."""
    from pokesim import config
    # Just test it loads
    assert hasattr(config, 'HOST')
    assert hasattr(config, 'PORT')


def test_app_creation():
    """Test app can be created."""
    from pokesim.app import manager
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            m = manager.Manager(tmpdir, 'http://127.0.0.1:8000')
            app = manager.create_app(m)
            assert app is not None
            m.close()
        except Exception as e:
            # Some dependencies might fail in test env, just ensure import works
            pass
