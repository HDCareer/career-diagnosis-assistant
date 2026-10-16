# HTML 报告组件

只负责根据已校验 JSON 排版，不生成专业结论。正式调用通过包内 scripts/workflow_orchestrator.py 和 renderer_adapter.py。二维码可选。默认只生成 HTML，CDN 字体和样式需要联网加载；无网时可阅读但外观可能不同。非 PNG 图片转换需要 Pillow。不要直接绕过编排器运行本目录脚本处理案例。
