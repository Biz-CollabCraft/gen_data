# Demo ten-second generation

- `scripts/demo_cadence.py` reads the shared demo selection every ten wall-clock seconds.
- Profiles: normal = realistic_sparse, emergency = training_dense, live = balanced_demo.
- Only the selected mode is ticked. Mode switching does not delete sensor data or workflow records.
- Native observation spacing remains ten simulation minutes; ten seconds is real generation cadence, not sensor timestamp spacing.
- Each 24-hour simulated run rotates to the next run automatically. Files remain under `data/demo-scenarios/generated/<mode>/runs/`; no automatic deletion or retention change is applied.
- This worker is explicitly launched, not installed as a boot service. A host restart requires relaunching it.
- Per tick: 100 equipment observations. Disk usage grows continuously while the worker runs.
- The dashboard reads complete ticks and refreshes its existing ten-second polling. A mode newly selected can take up to a generation/poll interval to appear; partial ticks are never served.
- Existing fixed snapshots remain a fallback before a mode's first generated tick. `live-state.json` identifies the latest generated stream per mode.
- Stop only the process whose exact command is `.venv/bin/python scripts/demo_cadence.py` in `/home/bistell/gen_data` to stop automatic generation.
