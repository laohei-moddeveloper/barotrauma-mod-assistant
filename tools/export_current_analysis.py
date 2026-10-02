"""Save a reproducible, read-only snapshot of the installed mod analysis."""
from collections import Counter
from itertools import combinations
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mod_assistant.core import atomic_json, discover, inventory
from mod_assistant.mod_analysis import (evaluate, inspect_all, luacs_runtime_detected,
                                        pair_evidence, workshop_details)


def main():
    env = discover()
    mods = inventory(env)
    metadata, _ = workshop_details(env, [mod.item_id for mod in mods], allow_network=False)
    features = inspect_all(mods, metadata)
    runtime = luacs_runtime_detected(env)
    assessments = evaluate(mods, features, runtime)
    pairs = []
    for left, right in combinations(mods, 2):
        score, reason = pair_evidence(features[left.item_id], features[right.item_id])
        if score:
            pairs.append({"left": left.name, "right": right.name, "score": score,
                          "left_enabled": left.enabled, "right_enabled": right.enabled,
                          "reason": reason})
    rows = []
    for mod in mods:
        feature = features[mod.item_id]
        assessment = assessments[mod.item_id]
        rows.append({"id": mod.item_id, "name": mod.name, "enabled": mod.enabled,
                     "types": assessment.kinds, "importance": assessment.importance,
                     "compatibility": assessment.compatibility, "reasons": assessment.reasons,
                     "compared": assessment.compared, "overlapping_pairs": assessment.risky_pairs,
                     "xml_definitions": len(feature.definitions), "code_files": feature.code_files,
                     "method_patches": len(feature.patches), "hook_registrations": len(feature.hook_names),
                     "unreadable_libraries": feature.opaque_code, "partial": feature.partial})
    output = Path(__file__).resolve().parents[1] / "Research" / "compatibility-analysis-v2.json"
    atomic_json(output, {"schema": "barotrauma-mod-analysis-v1",
                         "note": "本机静态分析快照；不是运行时兼容证明。",
                         "runtime_luacs_detected": runtime,
                         "compatibility_counts": dict(Counter(x["compatibility"] for x in rows)),
                         "mods": rows, "overlapping_pairs": pairs})
    print(f"mods={len(rows)} enabled={sum(x['enabled'] for x in rows)} "
          f"code_mods={sum(x['code_files'] > 0 for x in rows)} pairs={len(pairs)}")
    print("compatibility=" + str(dict(Counter(x["compatibility"] for x in rows))))
    print(output)


if __name__ == "__main__":
    main()
