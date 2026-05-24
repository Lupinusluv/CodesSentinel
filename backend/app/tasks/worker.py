"""ARQ Worker 配置。

启动命令（backend 目录下）：
    arq app.tasks.worker.WorkerSettings
"""

from arq.connections import RedisSettings

from app.core.config import get_settings
from app.tasks.index_task import run_index_task
from app.tasks.review_task import run_review_task

_url = get_settings().redis_url.replace("redis://", "").split("/")[0].split(":")
_host = _url[0]
_port = int(_url[1]) if len(_url) > 1 else 6379


class WorkerSettings:
    functions = [run_review_task, run_index_task]
    max_jobs = 10
    job_timeout = 600          # 索引任务最长 10 分钟（审查任务通常 < 2 分钟）
    redis_settings = RedisSettings(host=_host, port=_port)
