"""One bounded, local checkpoint. It stores identifiers, never executable commands."""
import json
import time
from .core import AssistantError, atomic_json, reject_link


class TaskCheckpoint:
    def __init__(self, env):
        self.env = env
        self.path = env.work / 'update-task.json'

    def check_paths(self):
        # Check before mkdir/read/replace, including absent or dangling targets.
        for path in (self.env.player, self.env.work.parent, self.env.work, self.path):
            try:
                reject_link(path)
            except FileNotFoundError:
                pass

    def load(self):
        try:
            self.check_paths()
            if self.path.stat().st_size > 256 * 1024:
                raise ValueError('size')
            data = json.loads(self.path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            return None
        except (OSError, ValueError, AssistantError) as error:
            raise AssistantError('更新任务记录无法读取；原记录已保留，可重新选择模组更新。') from error
        ids, completed = (data.get('ids'), data.get('completed')) if isinstance(data, dict) else (None, None)
        if (not isinstance(data, dict) or data.get('schema') != 1
                or data.get('game') != str(self.env.game.resolve())
                or type(data.get('online')) is not bool
                or not isinstance(ids, list) or not isinstance(completed, list)
                or len(ids) > 2000
                or any(not isinstance(item, str) or not item.isascii() or not item.isdecimal()
                       or len(item) > 20 or not 0 < int(item) < 2**64 for item in ids)
                or len(set(ids)) != len(ids)
                or any(not isinstance(item, str) or item not in ids for item in completed)):
            raise AssistantError('更新任务记录格式或游戏目录不匹配；未恢复任务。')
        return data

    def pending(self):
        data = self.load()
        if not data:
            return [], False
        done = set(data['completed'])
        return [item for item in data['ids'] if item not in done], data['online']

    def begin(self, ids, online):
        self.check_paths()
        self.env.work.mkdir(parents=True, exist_ok=True)
        self.data = {'schema': 1, 'game': str(self.env.game.resolve()), 'ids': list(ids),
                     'completed': [], 'online': bool(online), 'updated': time.time(), 'state': 'running'}
        self.save()

    def complete(self, item):
        if item not in self.data['completed']:
            self.data['completed'].append(item)
            self.save()

    def finish(self, state):
        self.data['state'] = state
        self.save()

    def save(self):
        self.check_paths()
        self.data['updated'] = time.time()
        atomic_json(self.path, self.data)
