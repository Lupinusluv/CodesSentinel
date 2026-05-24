# ARQ Worker 配置 —— feat/arq-worker 分支中正式接入
# MVP 阶段所有任务通过 FastAPI BackgroundTasks 执行，此文件为占位。

from app.core.config import get_settings


class WorkerSettings:
    """ARQ WorkerSettings，供 `arq app.tasks.worker.WorkerSettings` 启动。"""

    functions: list = []  # 任务函数将在 feat/arq-worker 中注册

    @classmethod
    def get_redis_settings(cls):
        from arq.connections import RedisSettings
        url = get_settings().redis_url
        # arq 需要 host/port 形式，从 URL 简单解析
        # redis://localhost:6379/0 → host=localhost, port=6379
        parts = url.replace("redis://", "").split("/")[0].split(":")
        host = parts[0]
        port = int(parts[1]) if len(parts) > 1 else 6379
        return RedisSettings(host=host, port=port)
