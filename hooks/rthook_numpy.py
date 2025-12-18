# Runtime hook to fix numpy CPU dispatcher tracer issue
import os
import sys

# Prevent numpy from initializing the CPU dispatcher tracer multiple times
os.environ['NPY_DISABLE_CPU_FEATURES'] = ''
