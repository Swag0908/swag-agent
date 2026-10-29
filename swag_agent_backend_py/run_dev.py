"""本地开发启动入口。

在 PyCharm 里直接右键本文件 -> Run 'run_dev' 即可；等价于命令行：
    .venv/bin/python run_dev.py

注意：必须在项目根目录运行（PyCharm 默认工作目录就是本文件所在目录），
否则 app/config.py 读不到根目录下的 .env。
"""

from __future__ import annotations

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8081,
        reload=True,       # 改代码自动重启；不想自动重启可改成 False
        reload_dirs=["app"],  # 只监听 app/，避免 notes-data 等目录触发重启
    )
