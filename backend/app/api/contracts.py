"""竞品只读 API 契约；历史报告的扩展字段按原值保留。"""

from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, JsonValue

Granularity = Literal["day", "week", "month"]
T = TypeVar("T")


class Document(BaseModel):
    """允许历史报告携带版本扩展字段，不裁剪业务证据。"""

    model_config = ConfigDict(extra="allow")


class Envelope(BaseModel, Generic[T]):
    """成功响应的数据封套。"""

    data: T


class ErrorDetail(BaseModel):
    """可供前端展示的稳定错误结构。"""

    code: str
    message: str
    details: list[dict[str, str]]


class ErrorResponse(BaseModel):
    """失败响应与成功数据互斥。"""

    error: ErrorDetail


class ReportEntry(Document):
    """商品对导航中的轻量报告条目。"""

    report_id: str
    start_date: str
    end_date: str
    self_spu: str
    competitor_spu: str
    self_name: str | None
    competitor_name: str | None
    self_image_url: str | None
    competitor_image_url: str | None
    updated_at: str


class ProductPair(Document):
    """本品和单个竞品及其各周期报告索引。"""

    self_spu: str
    competitor_spu: str
    self_name: str | None
    competitor_name: str | None
    self_image_url: str | None
    competitor_image_url: str | None
    latest_reports: dict[Granularity, ReportEntry | None]
    report_counts: dict[Granularity, int]


class ProductPairs(Document):
    """首次加载所需的商品对列表。"""

    updated_at: str | None
    items: list[ProductPair]


class Periods(Document):
    """指定年月中的报告及全部可导航上下文。"""

    self_spu: str
    competitor_spu: str
    granularity: Granularity
    context: str
    contexts: list[str]
    report_count: int
    items: list[ReportEntry]


class CoreMetric(Document):
    """四项核心指标的原值和差距；空值与零值分别保留。"""

    id: str
    label: str
    unit: str
    self_value: float | None
    competitor_value: float | None
    gap_value: float | None
    gap_rate_pct: float | None
    gap_mode: str
    gap_text: str
    status: str


class ReportMeta(Document):
    """报告业务周期，其他元数据由报告版本提供。"""

    period: str
    period_start: str
    period_end: str
    granularity: Granularity


class TrendReport(Document):
    """趋势查询中的轻量报告。"""

    report_id: str
    meta: ReportMeta
    quality_status: str
    report_status: str
    core_metrics: list[CoreMetric]


class Trends(Document):
    """指定商品对和周期范围的趋势数据。"""

    self_spu: str
    competitor_spu: str
    granularity: Granularity
    start_date: str
    end_date: str
    items: list[TrendReport]


class Report(Document):
    """完整历史报告；模块内容按原报告契约透传，不重新计算。"""

    schema_version: str
    meta: ReportMeta
    quality_status: str
    report_status: str
    core_metrics: list[CoreMetric]
    traffic_sources: list[JsonValue] | dict[str, JsonValue]
    keywords: dict[str, JsonValue]
    customer_profile: dict[str, JsonValue]
    promotion: dict[str, JsonValue]
    tabs: list[JsonValue]
    ai_findings: list[JsonValue]
    ai_recommendations: list[JsonValue]
    risks: list[JsonValue]


class SkuComponent(Document):
    """报告生成时的五字段 SKU 快照。"""

    spu_id: str | None
    sku_id: str | None
    barcode_69: str | None
    product_name: str | None
    specification: str | None


class ReportSkus(Document):
    """报告使用的 SKU 构成及来源数据集。"""

    report_id: str
    dataset_id: str | None
    source_dataset_ids: list[str]
    granularity: Granularity
    start_date: str
    end_date: str
    spu_id: str
    sku_count: int
    items: list[SkuComponent]


class AnalysisStatus(Document):
    """分析任务状态；阶段进度和统计字段由任务快照提供。"""

    schema_version: str
    status: str
    stage: str
    process_alive: bool
    progress_age_seconds: int | None
    stale: bool
