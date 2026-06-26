"""Super Tutor — API 路由层。

提供 FastAPI Router 模块，覆盖材料管理、测验、学习仪表盘等全部 HTTP 端点。
"""

from super_tutor.routes.dashboard import router as dashboard_router
from super_tutor.routes.materials import router as materials_router
from super_tutor.routes.quizzes import router as quizzes_router

__all__ = [
    "dashboard_router",
    "materials_router",
    "quizzes_router",
]
