"""状态文案：标题行与底栏两块的分工。

## 为什么要抽成纯函数

面板里显示状态的地方有两处——标题行（面板最上，原来固定写「DSH 通知」）和底栏
（新加，放 PID / 端口 / 启动方式 / 令牌）。两处必须给出一致结论，否则用户会看到
「运行中」配「无令牌」，或者标题说未运行、底栏却列出 PID。

抽成纯函数后，两处读同一个来源，测试也能直接断言文案而不必构造整个面板。

## 为什么标题行改显示状态

规格 FR-015 要求顶栏显示运行状态。原来的标题行是固定文字「DSH 通知」，实际状态
在与它相邻的控制区里——两处都有「状态」的含义，但只有一处是真的。改为标题行承担
状态、控制区专注于操作按钮，避免了同一信息在垂直方向上出现两次。
"""

from __future__ import annotations

from ..lifecycle import Instance, State

#: 各状态的短标签。用于标题行，所以不带句号、尽量短。
STATUS_TEXT = {
    State.STOPPED: "DSH 未运行",
    State.STARTING: "DSH 启动中",
    State.RUNNING: "DSH 运行中",
    State.STOPPING: "DSH 停止中",
    State.FAILED: "DSH 启动失败",
}


def status_text(state: State) -> str:
    """标题行用的状态短语。

    @param state - 生命周期状态
    @returns 状态短语；未知状态退回「DSH」而不是抛错
    """
    return STATUS_TEXT.get(state, "DSH")


def detail_text(state: State, instance: Instance | None, error: str, port: int) -> str:
    """底栏用的细节行：PID · 端口 · 启动方式 · 令牌。

    FR-017 要求未运行时不显示 PID——那时没有进程可指，列出 PID 只会让人以为
    有个实例在跑。FR-018 要求接管态的失权提示与正常态可区分，所以令牌一项用
    「带令牌」/「无令牌」两个不同词，而不是只在颜色上区分（颜色对色盲不可靠）。

    @param state - 生命周期状态
    @param instance - 运行实例；未运行时 None
    @param error - 失败原因
    @param port - 端口
    @returns 一行细节文本；无内容可显示时为空串
    """
    if state is State.RUNNING:
        if instance is None:
            # RUNNING 但拿不到实例：这是「状态已到运行、实例信息还没读到」的
            # 短暂窗口，以及状态与实例不同步的异常情况。不能落到下面的「空闲」
            # 分支——那会和标题行的「运行中」直接矛盾（FR-016）。
            return f"端口 {port} · 实例信息暂不可用"
        parts = [f"PID {instance.pid}", f"端口 {instance.port}"]
        parts.append("由托盘启动" if instance.owned else "外部启动")
        parts.append("带令牌" if instance.has_token else "无令牌")
        return " · ".join(parts)
    if state is State.STARTING:
        return f"端口 {port} · 冷启动通常需要十几秒"
    if state is State.STOPPING:
        return "正在结束会话与子进程"
    if state is State.FAILED:
        reason = error or "未知原因"
        return f"{reason} · 端口 {port}"
    return f"端口 {port} · 空闲"
