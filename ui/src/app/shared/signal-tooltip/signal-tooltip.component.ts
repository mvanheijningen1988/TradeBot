import { Component, Input } from '@angular/core';
import { CommonModule, TitleCasePipe } from '@angular/common';
import { SignalRecommendation } from '../../services/signals.service';

@Component({
  selector: 'app-signal-tooltip',
  standalone: true,
  imports: [CommonModule, TitleCasePipe],
  templateUrl: './signal-tooltip.component.html',
  styleUrl: './signal-tooltip.component.scss',
})
export class SignalTooltipComponent {
  @Input() signal!: SignalRecommendation;
  @Input() isBuy = true;

  private readonly infoDescriptions: Record<string, string> = {
    signal: 'Overall direction derived from news sentiment, detected market events, and weighting logic.',
    score: 'Combined numeric strength of the signal. Higher positive values are more bullish; lower negative values are more bearish.',
    confidence: 'How strong the model considers this signal relative to the article evidence. Higher percentages mean stronger conviction.',
    rsi9: 'Relative Strength Index over 9 periods. Short-term momentum gauge often used for day-trading setups.',
    rsi14: 'Relative Strength Index over 14 periods. Smoother medium-term momentum gauge used for broader trend context.',
    horizon: 'Whether the current mix of sentiment and RSI looks more useful for short-term trading, long-term investing, both, or neither.',
    context: 'Short article-based explanation describing why the signal reads positive, negative, or mixed.',
    reasons: 'Detected article themes or event categories that most influenced the final signal.',
  };

  get reasons(): string[] {
    return (this.signal?.reason || 'sentiment_only')
      .split(',')
      .map(r => r.trim().replaceAll('_', ' '))
      .filter(r => r.length > 0);
  }

  get contextSummary(): string {
    const summary = this.signal?.article_summary?.trim();
    if (summary) {
      return summary;
    }

    const direction = this.isBuy ? 'Positive context' : 'Negative context';
    const reasons = this.reasons;
    const primaryReason = reasons[0] ?? 'sentiment only';
    const otherReasons = reasons.slice(1);
    const reasonText = otherReasons.length > 0
      ? `${primaryReason} with supporting factors from ${otherReasons.join(', ')}`
      : primaryReason;
    const horizon = this.signal?.investment_horizon
      && this.signal.investment_horizon !== 'unknown'
      ? ` Horizon bias: ${this.formatHorizon(this.signal.investment_horizon)}.`
      : '';

    return `${direction}: ${this.signal.source} coverage was classified as ${this.signal.signal} mainly because of ${reasonText}.${horizon}`;
  }

  formatHorizon(value: string): string {
    if (value === 'long_term') return 'Long-term';
    if (value === 'short_term') return 'Short-term (Day Trading)';
    if (value === 'both') return 'Both';
    if (value === 'avoid') return 'Avoid for now';
    return 'Unknown';
  }

  infoText(key: string): string {
    return this.infoDescriptions[key] ?? 'Additional context for this signal field.';
  }

  private readonly eventDescriptions: Record<string, { buy: string; sell: string }> = {
    institutional_adoption: {
      buy: 'Major institutions are moving into this asset, signaling long-term confidence and potential price appreciation.',
      sell: 'Institutional interest appears to be declining, which may reduce demand and downward pressure on price.',
    },
    etf_approval: {
      buy: 'ETF-related developments could open this asset to mainstream investors, historically driving significant inflows.',
      sell: 'ETF setbacks or regulatory pushback could limit broader market access and dampen investor enthusiasm.',
    },
    exchange_listing: {
      buy: 'A new exchange listing increases liquidity and exposes this coin to a wider audience, often triggering a short-term rally.',
      sell: 'Delisting concerns reduce trading access and liquidity, which can accelerate sell-offs.',
    },
    partnership: {
      buy: 'A new strategic partnership expands real-world utility, strengthening the project\'s fundamentals and growth outlook.',
      sell: 'Partnership dissolution or failed collaboration weakens the project\'s ecosystem and market confidence.',
    },
    regulation_positive: {
      buy: 'Favorable regulatory developments provide legal clarity and reduce uncertainty, attracting cautious capital.',
      sell: 'Regulatory headwinds could restrict adoption or create compliance burdens for this asset.',
    },
    regulation_negative: {
      buy: 'Despite regulatory concerns, the market may have already priced in the risk — a potential contrarian opportunity.',
      sell: 'Negative regulatory action poses material risk to this asset\'s legality, access, or utility in key markets.',
    },
    hack: {
      buy: 'A security incident has been reported — exercise extreme caution before entering any position.',
      sell: 'A security breach undermines trust in the project and can trigger prolonged sell pressure.',
    },
    network_upgrade: {
      buy: 'A network upgrade improves scalability, security, or fees — positive catalysts for adoption and price.',
      sell: 'Upgrade-related instability or delays could temporarily shake market confidence.',
    },
    token_burn: {
      buy: 'Token burns reduce circulating supply, creating scarcity that can drive price higher over time.',
      sell: 'Token burn effects may be priced in or insufficient to offset current selling pressure.',
    },
    whale_accumulation: {
      buy: 'Large holders are accumulating, signaling that smart money sees upside potential at current levels.',
      sell: 'Whale distribution detected — large holders may be taking profits, which often precedes a price decline.',
    },
    sentiment_only: {
      buy: 'Overall news sentiment is positive, with multiple sources reflecting optimism around this asset.',
      sell: 'Negative sentiment is building across news sources, suggesting growing market pessimism.',
    },
  };

  get adviceHeadline(): string {
    const abs = Math.abs(this.signal.score);
    if (this.isBuy) {
      if (abs >= 5) return '⚡ Strong buy signal';
      return '↗ Moderate buy signal';
    }
    if (abs >= 5) return '⚠ Strong sell signal';
    return '↘ Moderate sell signal';
  }

  get adviceDescription(): string {
    const reasons = this.signal.reason.split(',').map(r => r.trim());
    const primary = reasons[0] || 'sentiment_only';
    const side = this.isBuy ? 'buy' : 'sell';

    const desc = this.eventDescriptions[primary]?.[side]
      ?? (this.isBuy
        ? 'Positive indicators detected — the asset shows favorable conditions based on recent news analysis.'
        : 'Negative indicators detected — the asset shows unfavorable conditions based on recent news analysis.');

    const conf = this.signal.confidence;
    let confNote = '';
    if (conf >= 0.7) {
      confNote = ' High confidence in this analysis.';
    } else if (conf >= 0.4) {
      confNote = ' Moderate confidence — consider additional research.';
    } else {
      confNote = ' Low confidence — use as one input among many.';
    }

    return desc + confNote;
  }
}
