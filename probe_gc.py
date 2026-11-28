# Temporary probe plugin (this branch is deleted after the probe): no cycle collection on any thread.
import gc
def pytest_configure(config):
    gc.disable()
    print("probe_gc: cycle collector disabled")
