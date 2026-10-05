"""Validate persisted preferences before passing them to Tk or background tasks."""
from pathlib import Path
import json
import shutil
import time


def normalize_preferences(value):
    result = dict(value) if isinstance(value, dict) else {}
    for key, default, low, high in [('download_slots', 4, 1, 12),
                                     ('install_slots', 3, 1, 6), ('timeout', 180, 30, 900)]:
        raw = result.get(key, default)
        try:
            number = int(raw) if type(raw) is int or isinstance(raw, str) else default
        except (ValueError, OverflowError):
            number = default
        result[key] = max(low, min(high, number))
    for key in ('auto_snapshot', 'light_detection'):
        raw = result.get(key, True)
        result[key] = raw if type(raw) is bool else (
            raw.casefold() == 'true' if isinstance(raw, str) and raw.casefold() in ('true', 'false') else True)
    if not isinstance(result.get('game_directory', ''), str):
        result['game_directory'] = ''
    backup=result.get('snapshot_directory','')
    result['snapshot_directory']=backup if isinstance(backup,str) and (not backup or Path(backup).is_absolute()) else ''
    history=result.get('snapshot_locations',[])
    result['snapshot_locations']=list(dict.fromkeys(path for path in history if isinstance(path,str) and Path(path).is_absolute()))[:10] if isinstance(history,list) else []
    return result


def load_preferences(path: Path):
    warnings = []
    writable = True
    try:
        original = path.read_text(encoding='utf-8-sig')
        data = json.loads(original)
        if not isinstance(data, dict):
            raise ValueError('Expected an object')
    except FileNotFoundError:
        data = {}
    except (ValueError, UnicodeError):
        data = {}
        # Preserve invalid data before future preference saves replace it.
        saved = path.with_name('settings.invalid-' + str(time.time_ns()) + '.json')
        try:
            shutil.copy2(path, saved)
            warnings.append('助手设置损坏，原文件已另存；本次使用默认设置。')
        except OSError:
            writable = False
            warnings.append('助手设置无法读取或另存；本次使用默认设置且不保存更改。')
    except OSError:
        data = {}
        writable = False
        warnings.append('助手设置无法读取或另存；本次使用默认设置且不保存更改。')
    normalized = normalize_preferences(data)
    if any(normalized.get(key) != raw for key, raw in data.items()):
        warnings.append('部分运行参数无效，已使用有效范围或默认值。')
    return normalized, warnings, writable
