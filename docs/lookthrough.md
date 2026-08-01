# 穿透暴露

direct 暴露只反映报告直接披露；look-through 沿 ETF 联接和报告基金持仓关系传播权重。关系记录来源报告、有效期、权重、原始文本和置信度。

算法设最大深度并检测循环。未解析目标保持 unresolved，不填 0，也不把已披露部分重新归一化。coverage、unresolved weight 和 circular flag 与结果一起展示。
