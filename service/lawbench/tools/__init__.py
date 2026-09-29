"""给 AI 的工具 case_*（Spec 4.4、20.4；契约 contracts/tools/）。本卡实现 8 个；case_calc_sentence 归 T24，
case_archive_match、case_save_archive_plan 归 T23。

所有工具只作用于当前任务所属的案件；参数先按工具契约的 $defs/args 校验（不合格 INVALID_ARGUMENT），
工具参数里没有路径，材料一律用 case_list_materials 给出的材料名。单次返回不超过 8000 字。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .. import contracts
from ..errors import ApiError


@dataclass
class ToolContext:
    root: str
    case_id: str
    task: dict
    tasks: object       # case.task.TaskStore
    materials: object   # case.materials.Materials

    def index(self) -> dict:
        return self.materials.index(self.case_id)

    def material_by_name(self, name: str) -> dict:
        for m in self.index()["materials"]:
            if m["name"] == name:
                return m
        raise ApiError("MATERIAL_NOT_FOUND", "unknown_material")


def _registry() -> dict[str, Callable[[ToolContext, dict], dict]]:
    from . import drafts, edit_list, inputs, materials
    return {
        "case_list_materials": materials.list_materials,
        "case_read_material": materials.read_material,
        "case_search": materials.search,
        "case_read_input": inputs.read_input,
        "case_read_wiki": inputs.read_wiki,
        "case_save_draft": drafts.save_draft,
        "case_suggest_wiki": drafts.suggest_wiki,
        "case_save_edit_list": edit_list.save_edit_list,
    }


TOOLS = tuple(_registry())


def run(ctx: ToolContext, tool: str, args: dict, validate_result: bool = True) -> dict:
    impl = _registry().get(tool)
    if impl is None:
        raise ApiError("INVALID_ARGUMENT", "unknown_tool")
    schema = f"tools/{tool}.schema.json"
    if contracts.errors(schema, "#/$defs/args", args):
        raise ApiError("INVALID_ARGUMENT", "args_contract")
    value = impl(ctx, args)
    if validate_result:
        contracts.validate(schema, "#/$defs/result", value)
    return value
