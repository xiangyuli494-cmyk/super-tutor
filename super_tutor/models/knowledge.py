"""Super Tutor — 知识结构模型。

定义 PDF 解析后的知识片段、学习材料以及知识图谱的节点/边/图结构。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from super_tutor.models.enums import DifficultyLevel


# ============================================================================
# KnowledgeChunk — PDF 解析后的最小知识单元
# ============================================================================


class KnowledgeChunk(BaseModel):
    """从 PDF / 学习材料中解析出的单个知识片段。

    每个 chunk 是原始文档的一个连续文本段，经过清洗和分段后独立存储，
    作为后续知识点提取和题目生成的原材料。
    """

    chunk_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="知识片段唯一标识",
    )
    material_id: str = Field(
        ...,
        description="所属学习材料 ID",
    )
    content: str = Field(
        ...,
        min_length=1,
        description="片段正文（原始文本或 Markdown）",
    )
    summary: str = Field(
        default="",
        max_length=256,
        description="片段摘要，用于全文检索与向量化（≤256 字符）",
    )
    page_start: Optional[int] = Field(
        default=None,
        ge=0,
        description="起始页码（0-based）",
    )
    page_end: Optional[int] = Field(
        default=None,
        ge=0,
        description="结束页码（0-based），单页时与 page_start 相同",
    )
    topic: str = Field(
        default="",
        description="主题标签，如'力学'、'线性代数'",
    )
    difficulty: DifficultyLevel = Field(
        default=DifficultyLevel.MEDIUM,
        description="该片段本身的难度评估",
    )
    keywords: list[str] = Field(
        default_factory=list,
        description="关键词列表，用于索引和检索",
    )
    knowledge_node_ids: list[str] = Field(
        default_factory=list,
        description="关联的知识图谱节点 ID 列表",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="扩展元数据（如字体大小、是否为标题、表格/公式标记等）",
    )
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="创建时间（ISO 8601）",
    )

    def model_post_init(self, __context: Any) -> None:
        """后处理：自动补齐 page_end，并校验页码范围。"""
        if self.page_end is None:
            object.__setattr__(self, "page_end", self.page_start)
        elif self.page_start is not None and self.page_end < self.page_start:
            raise ValueError(
                f"page_end ({self.page_end}) 不能小于 page_start ({self.page_start})"
            )


# ============================================================================
# Material — 学习材料（多个 chunk 的聚合）
# ============================================================================


class Material(BaseModel):
    """一份完整的学习材料，由一个或多个 KnowledgeChunk 聚合而成。

    对应一份上传的 PDF 文档、一个网页文章或手动录入的讲义。
    """

    material_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="材料唯一标识",
    )
    title: str = Field(
        ...,
        min_length=1,
        max_length=256,
        description="材料标题",
    )
    description: str = Field(
        default="",
        description="材料简介 / 摘要",
    )
    subject: str = Field(
        default="",
        description="学科，如'数学'、'物理'、'计算机科学'",
    )
    source_type: str = Field(
        default="pdf_upload",
        description="来源类型：pdf_upload / url / manual / scan",
    )
    source_path: Optional[str] = Field(
        default=None,
        description="原始文件路径或 URL",
    )
    total_pages: int = Field(
        default=0,
        ge=0,
        description="总页数",
    )
    language: str = Field(
        default="zh",
        description="语言代码（ISO 639-1），默认简体中文",
    )
    chunk_ids: list[str] = Field(
        default_factory=list,
        description="包含的 KnowledgeChunk ID 列表（有序）",
    )
    difficulty: DifficultyLevel = Field(
        default=DifficultyLevel.MEDIUM,
        description="整体难度评估",
    )
    status: str = Field(
        default="draft",
        description="处理状态：draft / processing / ready / archived",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="扩展元数据（作者、出版社、年份等）",
    )
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="创建时间（ISO 8601）",
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="最后更新时间（ISO 8601）",
    )

    @property
    def chunk_count(self) -> int:
        """返回包含的知识片段数量。"""
        return len(self.chunk_ids)


# ============================================================================
# KnowledgeNode — 知识图谱节点
# ============================================================================


class KnowledgeNode(BaseModel):
    """知识图谱中的一个节点，代表一个独立的概念、定理、公式或技能。

    节点之间通过 KnowledgeEdge 连接，形成有向知识图谱（DAG）。
    边的方向表示"前置依赖"关系：A → B 表示 A 是 B 的前置知识。
    """

    node_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="节点唯一标识",
    )
    label: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="节点名称，如'牛顿第二定律'、'矩阵乘法'",
    )
    description: str = Field(
        default="",
        description="概念解释，支持 Markdown",
    )
    node_type: str = Field(
        default="concept",
        description=(
            "节点类型：concept(概念) / skill(技能) / fact(事实) / "
            "theorem(定理) / definition(定义) / example(示例) / exercise(习题)"
        ),
    )
    subject: str = Field(
        default="",
        description="所属学科",
    )
    difficulty: DifficultyLevel = Field(
        default=DifficultyLevel.MEDIUM,
        description="难度等级",
    )
    importance: int = Field(
        default=3,
        ge=1,
        le=5,
        description="重要程度（1-5），5 为最高",
    )
    estimated_minutes: int = Field(
        default=15,
        ge=0,
        description="预计学习时长（分钟）",
    )
    keywords: list[str] = Field(
        default_factory=list,
        description="检索关键词",
    )
    chunk_ids: list[str] = Field(
        default_factory=list,
        description="支撑该节点的原始 KnowledgeChunk ID 列表",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="扩展元数据",
    )
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="创建时间（ISO 8601）",
    )


# ============================================================================
# KnowledgeEdge — 知识图谱边
# ============================================================================


class KnowledgeEdge(BaseModel):
    """知识图谱中的一条有向边，表示两个节点之间的关系。

    边的默认语义为"前置依赖"：source → target 表示 source 是 target 的前置知识。
    其他关系类型通过 relation 字段区分。
    """

    edge_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="边唯一标识",
    )
    source_id: str = Field(
        ...,
        description="源节点 ID（前置知识）",
    )
    target_id: str = Field(
        ...,
        description="目标节点 ID（后继知识）",
    )
    relation: str = Field(
        default="prerequisite_of",
        description=(
            "关系类型：prerequisite_of(前置) / related_to(相关) / "
            "part_of(属于) / leads_to(引出) / exemplifies(举例) / "
            "generalizes(泛化) / contradicts(对立)"
        ),
    )
    weight: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="关系强度（0.0-1.0），1.0 表示强依赖",
    )
    label: str = Field(
        default="",
        max_length=256,
        description="边的人类可读标签，如'需要先掌握'、'是…的特例'",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="扩展元数据",
    )


# ============================================================================
# KnowledgeGraph — 知识图谱容器
# ============================================================================


class KnowledgeGraph(BaseModel):
    """完整知识图谱，包含所有节点和有向边。

    提供常用的图遍历方法：前置依赖查询、后继查询、拓扑排序等。
    保证节点 ID 和边引用的内部一致性。
    """

    graph_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="图谱唯一标识",
    )
    name: str = Field(
        default="",
        description="图谱名称，如'高中物理力学知识图谱'",
    )
    subject: str = Field(
        default="",
        description="所属学科",
    )
    nodes: list[KnowledgeNode] = Field(
        default_factory=list,
        description="图谱中所有节点",
    )
    edges: list[KnowledgeEdge] = Field(
        default_factory=list,
        description="图谱中所有边",
    )

    # -- 内部索引（Pydantic model_post_init 构建）---------------------------

    def model_post_init(self, __context: Any) -> None:
        """构建节点索引，校验边引用的节点是否存在。"""
        self._node_index: dict[str, KnowledgeNode] = {
            n.node_id: n for n in self.nodes
        }
        for edge in self.edges:
            if edge.source_id not in self._node_index:
                raise ValueError(
                    f"边 {edge.edge_id!r} 引用的 source_id={edge.source_id!r} 不存在于 nodes 中"
                )
            if edge.target_id not in self._node_index:
                raise ValueError(
                    f"边 {edge.edge_id!r} 引用的 target_id={edge.target_id!r} 不存在于 nodes 中"
                )

    # -- 查询方法 -----------------------------------------------------------

    def get_node(self, node_id: str) -> Optional[KnowledgeNode]:
        """按 ID 查找节点，不存在返回 None。"""
        return self._node_index.get(node_id)

    def get_prerequisites(self, node_id: str) -> list[KnowledgeNode]:
        """返回 node_id 的所有直接前置节点（即所有 source → node_id 的 source）。"""
        prereq_ids: set[str] = set()
        for edge in self.edges:
            if edge.target_id == node_id and edge.relation == "prerequisite_of":
                prereq_ids.add(edge.source_id)
        return [
            self._node_index[nid]
            for nid in prereq_ids
            if nid in self._node_index
        ]

    def get_all_prerequisites(self, node_id: str) -> list[KnowledgeNode]:
        """返回 node_id 的所有传递前置节点（递归，拓扑顺序）。"""
        visited: set[str] = set()
        result: list[KnowledgeNode] = []

        def _dfs(nid: str) -> None:
            for prereq in self.get_prerequisites(nid):
                if prereq.node_id not in visited:
                    visited.add(prereq.node_id)
                    _dfs(prereq.node_id)
                    result.append(prereq)

        _dfs(node_id)
        return result

    def get_dependents(self, node_id: str) -> list[KnowledgeNode]:
        """返回所有直接依赖 node_id 的节点（即 node_id → target 的 target）。"""
        dep_ids: set[str] = set()
        for edge in self.edges:
            if edge.source_id == node_id and edge.relation == "prerequisite_of":
                dep_ids.add(edge.target_id)
        return [
            self._node_index[nid]
            for nid in dep_ids
            if nid in self._node_index
        ]

    def topological_order(self) -> list[KnowledgeNode]:
        """按拓扑序返回所有节点（前置知识在前）。

        使用 Kahn 算法。若存在环，尽可能返回部分排序并丢弃环中节点。
        """
        in_degree: dict[str, int] = {n.node_id: 0 for n in self.nodes}
        adj: dict[str, list[str]] = {n.node_id: [] for n in self.nodes}

        for edge in self.edges:
            if edge.relation == "prerequisite_of":
                sid, tid = edge.source_id, edge.target_id
                if sid in adj and tid in in_degree:
                    adj[sid].append(tid)
                    in_degree[tid] += 1

        # Kahn's algorithm
        queue: list[str] = [nid for nid, d in in_degree.items() if d == 0]
        ordered: list[KnowledgeNode] = []

        while queue:
            nid = queue.pop(0)
            node = self._node_index.get(nid)
            if node:
                ordered.append(node)
            for neighbor in adj.get(nid, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        return ordered

    def get_roots(self) -> list[KnowledgeNode]:
        """返回所有入度为 0 的节点（没有前置知识的起点）。"""
        has_prereq: set[str] = set()
        for edge in self.edges:
            if edge.relation == "prerequisite_of":
                has_prereq.add(edge.target_id)
        return [n for n in self.nodes if n.node_id not in has_prereq]

    def get_leaves(self) -> list[KnowledgeNode]:
        """返回所有出度为 0 的节点（没有后继知识的终点）。"""
        has_dependent: set[str] = set()
        for edge in self.edges:
            if edge.relation == "prerequisite_of":
                has_dependent.add(edge.source_id)
        return [n for n in self.nodes if n.node_id not in has_dependent]

    # -- 突变方法 -----------------------------------------------------------

    def add_node(self, node: KnowledgeNode) -> None:
        """向图谱中添加一个节点（重复 ID 将覆盖）。"""
        self.nodes.append(node)
        self._node_index[node.node_id] = node

    def add_edge(self, edge: KnowledgeEdge) -> None:
        """向图谱中添加一条边。

        Raises:
            ValueError: 若 source_id 或 target_id 引用的节点不存在。
        """
        if edge.source_id not in self._node_index:
            raise ValueError(f"source_id={edge.source_id!r} 不在图谱节点中")
        if edge.target_id not in self._node_index:
            raise ValueError(f"target_id={edge.target_id!r} 不在图谱节点中")
        self.edges.append(edge)

    def remove_node(self, node_id: str) -> None:
        """删除节点及其所有关联边。"""
        self.nodes = [n for n in self.nodes if n.node_id != node_id]
        self.edges = [
            e
            for e in self.edges
            if e.source_id != node_id and e.target_id != node_id
        ]
        self._node_index.pop(node_id, None)

    # -- 统计 ---------------------------------------------------------------

    @property
    def node_count(self) -> int:
        """节点总数。"""
        return len(self.nodes)

    @property
    def edge_count(self) -> int:
        """边总数。"""
        return len(self.edges)
