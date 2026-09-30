"""395 预处理服务：单页识别（OCR）与 9B 抽取（Spec 第 6 节）。"""

from pathlib import Path

__version__ = "1.0.0"
CONTRACT_VERSION_FALLBACK = "1.3"   # 395 上只部署 prep395\，读不到仓库 contracts\VERSION 时用这个；改契约版本时同步改


def _contract_version() -> str:
    """读仓库 contracts/VERSION（开发机、测试）；部署到 395 后没有这个文件，退回写死的版本。"""
    try:
        v = (Path(__file__).resolve().parents[2] / "contracts" / "VERSION").read_text(encoding="utf-8").strip()
        return v or CONTRACT_VERSION_FALLBACK
    except OSError:
        return CONTRACT_VERSION_FALLBACK


CONTRACT_VERSION = _contract_version()
