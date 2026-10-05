"""Useful local error evidence without telemetry or new filesystem access."""
import traceback
import uuid
from . import VERSION
from .core import AssistantError
from .diagnostics import redact

OPERATIONS={'scan':'检测模组','automatic':'生成排序预览','capture_snapshot':'保存完整快照','restore_snapshot':'恢复快照',
            'install_luacs':'安装 LuaCs','set_csharp':'设置 C# 开关','restore_luacs':'恢复 LuaCs 文件或设置',
            'start_update':'更新模组','apply':'应用模组配置','save':'应用排序草稿','compare':'对照文件或配置',
            'diagnose_logs':'读取游戏日志','toggle_item':'更改模组启用状态'}

def operation_name(function):
    qualified=getattr(function,'__qualname__','')
    name=qualified.split('.<locals>.')[0].rsplit('.',1)[-1] if isinstance(qualified,str) else ''
    return OPERATIONS.get(name,'助手操作')

def describe_error(error,env=None,operation='助手操作',trace=None):
    reference=uuid.uuid4().hex[:8]
    cause=redact(str(error),env)
    if isinstance(error,PermissionError):
        reason='所需文件无法访问或写入。'
        next_step='关闭游戏后重试，确认目标文件夹可写。无需以管理员身份运行；备份文件夹和本地错误详情可帮助定位具体文件。'
    elif isinstance(error,FileNotFoundError):
        reason='所需文件或文件夹不存在。'
        next_step='重新检测游戏位置；如果正在保存备份，请确认模组文件未被 Steam 移动。不要把未完成备份当作可恢复副本。'
    elif isinstance(error,OSError) and getattr(error,'winerror',None)==17:
        reason='文件操作遇到不同磁盘之间的目录替换。'
        next_step='保留快照和恢复记录，查看错误详情中的目标位置；不要手动删除恢复前副本。'
    elif isinstance(error,AssistantError):
        reason=cause
        next_step='按上述原因处理后重试；若仍失败，复制下方本地错误详情和可复现步骤供维护者定位。'
    else:
        reason='操作发生异常，尚不能仅凭此提示确认原因。'
        next_step='保留备份，查看本地错误详情。反馈时附上操作步骤和错误编号；日志不会自动上传。'
    details=redact(trace or ''.join(traceback.format_exception(type(error),error,error.__traceback__)),env)
    return {'id':reference,'operation':operation,'version':VERSION,'reason':reason,'next_step':next_step,
            'cause':cause,'details':details,
            'summary':operation+'\n'+reason+'\n\n'+next_step+'\n\n'+'错误编号：'+reference+'\n'+'在“工具”中打开“最近错误详情”，可查看和复制定位信息。'}
