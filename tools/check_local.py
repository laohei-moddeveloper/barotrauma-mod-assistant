"""Local integration verification. Explicit --install performs a real subscribed-mod sync."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mod_assistant.core import atomic_json, discover, inventory, validate_manifest
from mod_assistant.engine import UpdateEngine

parser = argparse.ArgumentParser()
parser.add_argument("--install", action="store_true")
parser.add_argument("--offline", action="store_true")
parser.add_argument("--report", default="Research/integration-result.json")
args = parser.parse_args()
env = discover()
mods = inventory(env)
errors = {}
for mod in mods:
    try: validate_manifest(mod.source, env)
    except Exception as error: errors[mod.item_id] = str(error)
report = {"mod_count": len(mods), "manifest_errors": errors}
if args.install:
    stages = {}
    def emit(event):
        if event["kind"] == "item" and stages.get(event["id"]) != event["stage"]:
            stages[event["id"]] = event["stage"]
            print(event["id"], event["stage"], event["detail"], flush=True)
    report["run"] = UpdateEngine(env, emit).run([m.item_id for m in mods], online=not args.offline)
atomic_json(Path(args.report), report)
print(json.dumps({"mods": len(mods), "manifest_errors": errors,
                  "completed": len(report.get("run", {}).get("completed", {})),
                  "errors": report.get("run", {}).get("errors", {}),
                  "seconds": report.get("run", {}).get("seconds")}, ensure_ascii=False))
