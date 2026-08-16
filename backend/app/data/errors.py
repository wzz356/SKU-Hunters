"""连接器层统一异常定义（从旧本地趋势官迁移）

约定：底层连接器（google_trends / bilibili_hot / taobao_suggest）
遇到 HTTP 错误、解析错误、业务状态错误时必须抛出 ConnectorFetchError，
绝不返回空列表/空字典把故障折叠成"正常零命中"。

趋势官捕获该异常后写入 data_gaps / caveats，保证：
  - 故障 ≠ 零命中（不误判为"平台没有相关内容"）；
  - 空数据 ≠ 0 热度（不把缺失误报成正常结果）。
"""


class ConnectorFetchError(Exception):
    """底层连接器采集失败。

    Attributes:
        connector: 连接器名（如 "bilibili"、"google_trends"）
        detail: 失败详情（HTTP 状态码、业务错误码、解析失败原因等）
    """

    def __init__(self, connector: str, detail: str):
        self.connector = connector
        self.detail = detail
        super().__init__(f"[{connector}] {detail}")
