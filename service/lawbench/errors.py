"""统一错误码与给律师看的中文提示（Spec 20.1；契约 common.schema.json#/$defs/error_code）。"""
from __future__ import annotations

MESSAGES: dict[str, str] = {
    "INVALID_ARGUMENT": "请求参数有误",
    "OUT_OF_CASE": "超出当前案件范围",
    "CASE_NOT_FOUND": "找不到该案件，请重新打开",
    "CASE_ROOT_IS_LINK": "请直接选择实际文件夹",
    "CASE_IN_SYNC_FOLDER": "该文件夹在云同步目录中，请移到本机普通文件夹后再打开",
    "MATERIAL_NOT_FOUND": "没有这份材料，请先查看材料清单",
    "MATERIAL_NOT_READY": "这份材料还不能读取（待识别或处理失败）",
    "TASK_NOT_FOUND": "找不到该任务",
    "INPUT_CHANGED": "选用的材料已被修改，请复核后重新选择",
    "BUDGET_EXCEEDED": "已达到本次任务的上限，已保存草稿",
    "SERVER_UNREACHABLE": "无法连接服务器，请检查网络",
    "KEY_INVALID": "Key 无效或已停用，请联系管理员",
    "SERVER_BUSY": "服务器繁忙，排队已超过 5 分钟，请稍后再试",
    "CONTEXT_TOO_LONG": "内容超出模型上限，请缩小范围或调大窗口",
    "OUTPUT_TRUNCATED": "输出达到上限，已保存为草稿，可调大\"最大生成量\"后继续",
    "TIMEOUT": "本次生成时间过长，已停止并保存草稿",
    "HOST_NOT_ALLOWED": "不允许连接该地址",
    "PREP_UNAVAILABLE": "395 暂时不可用，恢复后会自动继续",
    "CANCELLED": "已取消",
    "SERVICE_UNAVAILABLE": "工作台服务未启动，请稍后重试",
    "INTERNAL": "内部错误，请重试；多次出现请联系技术支持",
    "OFFICE_DIR_NOT_SET": "请先在设置中指定日常办公文件夹",
    "CONVERTER_UNAVAILABLE": "无法把文件转成 PDF，请在 Word 或 WPS 中另存为 PDF 后放入案件文件夹",
    "TEMPLATE_MISSING": "缺少模板文件，请联系管理员",
    "ENGINE_FAILED": "发票整理未完成，请查看下方的输出信息",
    "ENGINE_BUSY": "发票整理正在进行中，请等它完成再操作",
    "PLAN_NOT_CONFIRMED": "请先确认办案结果",
    "ORIGINAL_HAS_REVISIONS": "原文件含未处理的修订，请先接受或拒绝后再生成",
    "CASE_CARD_INVALID": "案件卡片（工作区/wiki/case.json）已损坏，请重新生成 wiki",
}


class ApiError(Exception):
    """业务错误：接口按 HTTP 200 + 失败体返回。`reason` 只给日志用，不含路径和内容。"""

    def __init__(self, code: str, reason: str | None = None, detail: str | None = None):
        """detail：给律师看的具体说明（如哪份材料、为什么），替换该码的通用提示；不进日志。"""
        if code not in MESSAGES:
            raise ValueError(f"未知错误码 {code}")
        super().__init__(code)
        self.code = code
        self.reason = reason
        self.detail = detail

    @property
    def message(self) -> str:
        return self.detail or MESSAGES[self.code]


def fail_body(code: str, message: str | None = None) -> dict:
    return {"ok": False, "error": {"code": code, "message": message or MESSAGES[code]}}
