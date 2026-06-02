"""ARQ Worker 配置。

启动命令（backend 目录下）：
    arq app.tasks.worker.WorkerSettings
"""

from arq.connections import RedisSettings

from app.core.config import get_settings
from app.tasks.autofix_task import run_autofix_task
from app.tasks.index_task import run_index_task
from app.tasks.review_task import run_review_task


class WorkerSettings:
    functions = [run_review_task, run_index_task, run_autofix_task]
    max_jobs = 10
    job_timeout = 600  # 索引任务最长 10 分钟（审查任务通常 < 2 分钟）
    # from_dsn 完整解析 host/port/db/密码/TLS，与 get_arq_pool 一致；
    # 旧手写拆分只取 host/port，是 P1-2 在 dependencies 修过、但此处遗漏的同一个 bug。
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
