"""启动配置：端口、令牌、应用数据目录等（Spec 1.3）。

DSH 会清掉子进程继承的环境变量，Host 插件在 env 里显式传 LB_* 变量；命令行参数优先于环境变量。
"""
from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass, field

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
PRODUCT_DIR_NAME = "lawbench"  # <应用数据> = %APPDATA%\<产品名>\；产品名待 T20 定，Host 插件用 LB_APPDATA 显式传
DEFAULT_FORWARD_PORT = 18765


def _default_appdata() -> pathlib.Path:
    base = os.environ.get("APPDATA") or str(pathlib.Path.home())
    return pathlib.Path(base) / PRODUCT_DIR_NAME


def _default_skills_dirs() -> list[pathlib.Path]:
    return [REPO_ROOT / "skills"]


@dataclass
class Config:
    token: str
    appdata: pathlib.Path = field(default_factory=_default_appdata)
    port: int = 0
    forward_port: int = DEFAULT_FORWARD_PORT
    # Skill 加载位置（Spec 10.1）：<安装目录>/skills/、%ProgramData%\<产品名>\skills\；第一个目录放 capsules.default.json
    skills_dirs: list[pathlib.Path] = field(default_factory=_default_skills_dirs)
    contracts_dir: pathlib.Path = REPO_ROOT / "contracts"
    # 开发和测试环境校验所有返回，生产关闭（Spec 20.11）
    validate_responses: bool = True

    @classmethod
    def from_env(cls, **override) -> "Config":
        env = os.environ
        kw: dict = {}
        if env.get("LB_TOKEN"):
            kw["token"] = env["LB_TOKEN"]
        if env.get("LB_PORT"):
            kw["port"] = int(env["LB_PORT"])
        if env.get("LB_APPDATA"):
            kw["appdata"] = pathlib.Path(env["LB_APPDATA"])
        if env.get("LB_FORWARD_PORT"):
            kw["forward_port"] = int(env["LB_FORWARD_PORT"])
        if env.get("LB_SKILLS_DIRS"):
            kw["skills_dirs"] = [pathlib.Path(p) for p in env["LB_SKILLS_DIRS"].split(os.pathsep) if p]
        if env.get("LB_CONTRACTS_DIR"):
            kw["contracts_dir"] = pathlib.Path(env["LB_CONTRACTS_DIR"])
        if env.get("LB_VALIDATE_RESPONSES"):
            kw["validate_responses"] = env["LB_VALIDATE_RESPONSES"] not in ("0", "false", "no")
        kw.update({k: v for k, v in override.items() if v is not None})
        if not kw.get("token"):
            raise SystemExit("缺少启动令牌：用 --token 或环境变量 LB_TOKEN 传入")
        return cls(**kw)
