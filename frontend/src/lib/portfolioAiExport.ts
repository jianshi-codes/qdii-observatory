import type { PortfolioConsistencyPayload, PortfolioPayload } from '../api/types'

function portfolioWithoutPrivateIdentifiers(portfolio: PortfolioPayload) {
  return {
    ...portfolio,
    positions: portfolio.positions.map((position) => {
      const publicPosition: Partial<typeof position> = { ...position }
      delete publicPosition.id
      delete publicPosition.fund_id
      delete publicPosition.platform
      return publicPosition
    }),
  }
}

function analysisWithoutDatabaseIdentifiers(analysis: PortfolioConsistencyPayload) {
  return {
    ...analysis,
    funds: analysis.funds.map((fund) => {
      const publicFund: Partial<typeof fund> = { ...fund }
      delete publicFund.fund_id
      return publicFund
    }),
    overlaps: analysis.overlaps.map((overlap) => {
      const publicOverlap: Partial<typeof overlap> = { ...overlap }
      delete publicOverlap.left_fund_id
      delete publicOverlap.right_fund_id
      return publicOverlap
    }),
  }
}

export function buildPortfolioAiContext(
  portfolio: PortfolioPayload,
  analysis: PortfolioConsistencyPayload,
  generatedAt = new Date(),
) {
  return {
    schema_version: 'qdii_portfolio_ai_context.v1',
    generated_at: generatedAt.toISOString(),
    purpose: 'AI-assisted portfolio research; not an order instruction or guaranteed-return forecast.',
    privacy: {
      mode: 'PRIVATE_FINANCIAL_DATA_WITH_IDENTIFIERS_REDACTED',
      included: [
        'units, exact market values, profit amounts, and recurring-investment amounts',
        'cash-flow records and user-entered notes',
        'consistency analysis, limitations, and public source links',
      ],
      omitted: ['platform names', 'position, fund, and overlap database identifiers'],
      external_sharing_warning: 'Pasting this content into an AI service sends personal financial data outside the local application.',
    },
    portfolio_snapshot: portfolioWithoutPrivateIdentifiers(portfolio),
    consistency_analysis: analysisWithoutDatabaseIdentifiers(analysis),
    requested_analysis: [
      'Check data freshness, missing coverage, and whether the evidence supports a conclusion.',
      'Assess fund, country, industry, and disclosed-security concentration and overlap.',
      'Explain consistency deviations without inferring undisclosed trades as facts.',
      'Discuss fee drag, cash flows, and recurring-investment execution risks.',
      'Offer scenario-based research options and list the investor information needed before personalized advice.',
    ],
    disclaimers: [
      'Quarterly disclosed holdings are delayed snapshots and may differ from the current portfolio.',
      'Missing values are unknown, not zero.',
      'The consistency model cannot identify actual manager trades or predict future returns.',
      'The output is research context and does not constitute investment, legal, tax, or accounting advice.',
    ],
  }
}

export type PortfolioAiContext = ReturnType<typeof buildPortfolioAiContext>

export function portfolioAiJson(context: PortfolioAiContext): string {
  return `${JSON.stringify(context, null, 2)}\n`
}

export function portfolioChatGptPrompt(context: PortfolioAiContext): string {
  return `你是一名谨慎的基金组合研究助手。请基于下方完整持仓 JSON 做证据驱动分析。\n\n要求：\n1. 先检查数据日期、覆盖率、缺失值与限制；缺失值不得按 0。\n2. 分析基金、国家/地区、行业与披露证券的集中度和重叠。\n3. 解释“实际与静态披露估算”的偏差，但不得把未披露调仓当作事实。\n4. 分析持仓金额、收益、费率、现金流、定投及待确认订单之间的关系。\n5. 明确区分数据事实、合理推断和无法验证的判断，并尽量附上 JSON 中的公开来源链接。\n6. 不承诺收益，不直接下达买卖指令。给出条件式、情景化的研究选项，并说明每个选项的风险与前提。\n7. 在给出个性化建议前，先列出仍需确认的信息，例如投资期限、风险承受能力、流动性需求、税务环境和再平衡约束。\n8. 最后输出：核心发现、主要风险、待确认问题、可选后续行动、数据局限。\n\n完整持仓 JSON（包含个人财务数据，请勿继续公开传播）：\n\n${portfolioAiJson(context)}`
}
