# Synthetic catalog and asynchronous desktop benchmark entry.
from sgp4.io import fix_checksum
from .propagators import DEMO_TLE


def synthetic_tle_catalog(count):
    # Synthetic stress data based on Vallado's historical verification orbit.
    # Distinct catalog IDs, RAANs and anomalies; not an operational catalog.
    line1,line2 = DEMO_TLE.splitlines()[1:]
    lines = []
    for i in range(count):
        number = f'{i+10000:05d}'
        first = line1[:2]+number+line1[7:]
        second = line2[:2]+number+line2[7:17]+f'{(i%100)*3.6:8.4f}'+line2[25:43]+f'{(i//100)*3.6:8.4f}'+line2[51:]
        lines.extend([f'Synthetic-{number}',fix_checksum(first),fix_checksum(second)])
    return '\n'.join(lines)


def run(w,app):
    from .benchmark_run import Benchmark
    w.benchmark_controller = Benchmark(w,app,synthetic_tle_catalog)


