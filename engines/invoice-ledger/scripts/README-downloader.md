# 下载与整理入口

当前完整入口：`python scripts/invoke.py workflow.py`，具体命令和状态见references/10-collection-and-paper.md。

workflow.py支持只读IMAP、导出EML、本地PDF/ZIP、正文链接重试、浏览器文件绑定、核验入账和贴票批次。首次运行使用自带环境包，不要求宿主安装业务依赖。

decode_results.py仍可处理兼容连接器的base64工具响应；不是邮箱登录器。archive_files.py接受显式映射并校验哈希，不移动删除原始解码文件。classify_archived.py仅作PDF分类辅助；正式贴票打印使用workflow.py prepare，不能直接将分类统计表当作新增可报金额。

私有任务目录内的collection.json及原始资料需一起备份。返回非零时阅读明细，不得将部分结果宣称为全量成功。
