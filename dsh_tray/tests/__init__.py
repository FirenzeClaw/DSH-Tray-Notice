"""dsh_tray 的测试包。

跑法：`python3 -m unittest discover -s dsh_tray/tests -t .`（仓库根执行）。
GUI 相关用例需要 `QT_QPA_PLATFORM=offscreen`——实测该后端下 widget 可实例化，
`isVisible()` 也返回真，因此面板行为能被断言而不是只能手点。
"""
