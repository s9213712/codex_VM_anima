from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
STATE=ROOT/'.state'
OUTPUT=ROOT/'.outputs'
DB=STATE/'jobs.sqlite3'
KEY=STATE/'api.key'
MODEL='circlestone-labs/Anima-Base-v1.0-Diffusers'
REVISION='073c3a9db359c31ad0e8aa268d15775473c2176c'
