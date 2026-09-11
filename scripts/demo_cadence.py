"""Generate the selected demo profile every ten wall-clock seconds.

Sensor observations retain the native ten-minute simulation interval. Completed
run files and maintenance records are never removed. Stop this worker to stop ticks.
"""
import json
import os
import signal
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from app.runtime.manager import RuntimeManager

ROOT = Path('/home/bistell/ontology_dashboard/data/demo-scenarios')
GEN = Path('/home/bistell/gen_data')
OUTPUT = ROOT / 'generated'
PERIOD = 10.0
PROFILES = {'normal': 'realistic_sparse', 'emergency': 'training_dense', 'live': 'balanced_demo'}


def main():
    import fcntl
    ROOT.mkdir(parents=True, exist_ok=True)
    lock = (ROOT/'cadence.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    managers, runs, next_at = {}, {}, {}
    state = json.loads((ROOT/'live-state.json').read_text()) if (ROOT/'live-state.json').exists() else {}
    deadline = time.monotonic()
    try:
        while not stop.is_set():
            mode = json.loads((ROOT/'selection.json').read_text()).get('mode', 'live') if (ROOT/'selection.json').exists() else 'live'
            if mode not in PROFILES:
                raise ValueError('Unknown selected mode')
            if mode not in managers:
                managers[mode] = RuntimeManager(output_root=OUTPUT/mode,
                    mapping_path=GEN/'mappings/opcua_nodes.v1.json', opcua_endpoint='opc.tcp://127.0.0.1:4840/gen-data/')
            manager = managers[mode]
            if mode not in runs:
                run_id = 'demo-10s-' + mode + '-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
                manager.start_run(run_id=run_id, start_at=next_at.get(mode), duration_hours=24,
                    interval_minutes=10, product_cycle_minutes=20, rate_profile=PROFILES[mode],
                    speed=60, tick_interval_seconds=10, continuous=False, publish_opcua=False)
                runs[mode] = run_id
            run_id = runs[mode]
            result = manager.tick(run_id)
            outputs = manager.outputs(run_id)
            state[mode] = {'stream': outputs['source'], 'run_id': run_id,
                'updated_at': datetime.now(timezone.utc).isoformat(), 'tick_interval_seconds': 10,
                'observation_interval_minutes': 10, 'profile': PROFILES[mode],
                'source_record_count': result['source_record_count']}
            temp = ROOT/'live-state.tmp'
            temp.write_text(json.dumps(state), encoding='utf-8')
            os.replace(temp, ROOT/'live-state.json')
            print(json.dumps({'mode': mode, **state[mode]}), flush=True)
            context = manager._get(run_id)
            if context.state.current_observed_at >= context.producer.end_at:
                next_at[mode] = context.state.current_observed_at
                manager.stop(run_id)
                del runs[mode]
            deadline += PERIOD
            now = time.monotonic()
            if deadline <= now:
                deadline += (int((now-deadline)/PERIOD)+1)*PERIOD
            stop.wait(max(0, deadline-time.monotonic()))
    finally:
        for manager in managers.values():
            manager.shutdown()


if __name__ == '__main__':
    main()
