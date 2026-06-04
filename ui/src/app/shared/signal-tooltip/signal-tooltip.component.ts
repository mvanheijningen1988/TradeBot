import { Component, Input } from '@angular/core';
import { CommonModule, TitleCasePipe } from '@angular/common';
import { SignalRecommendation } from '../../services/signals.service';

@Component({
  selector: 'app-signal-tooltip',
  standalone: true,
  imports: [CommonModule, TitleCasePipe],
  template: `
    <div
      class="signal-tooltip"
      [class.signal-tooltip--buy]="isBuy"
      [class.signal-tooltip--sell]="!isBuy"
    >
      <div class="signal-tooltip__header">
        <span class="signal-tooltip__action">{{ isBuy ? '▲ BUY' : '▼ SELL' }}</span>
        <span class="signal-tooltip__coin">{{ signal.coin }}</span>
      </div>
      <div class="signal-tooltip__divider"></div>
      <div class="signal-tooltip__row">
        <span class="signal-tooltip__label">Signal</span>
        <span class="signal-tooltip__value" [class.text-green]="isBuy" [class.text-red]="!isBuy">
          {{ signal.signal | uppercase }}
        </span>
      </div>
      <div class="signal-tooltip__row">
        <span class="signal-tooltip__label">Score</span>
        <span class="signal-tooltip__value mono" [class.text-green]="isBuy" [class.text-red]="!isBuy">
          {{ signal.score > 0 ? '+' : '' }}{{ signal.score.toFixed(2) }}
        </span>
      </div>
      <div class="signal-tooltip__row">
        <span class="signal-tooltip__label">Confidence</span>
        <span class="signal-tooltip__value mono">{{ (signal.confidence * 100).toFixed(0) }}%</span>
      </div>
      @if (signal.rsi_short !== null && signal.rsi_short !== undefined) {
        <div class="signal-tooltip__row">
          <span class="signal-tooltip__label">RSI (9)</span>
          <span class="signal-tooltip__value mono">{{ signal.rsi_short.toFixed(2) }}</span>
        </div>
      }
      @if (signal.rsi_long !== null && signal.rsi_long !== undefined) {
        <div class="signal-tooltip__row">
          <span class="signal-tooltip__label">RSI (14)</span>
          <span class="signal-tooltip__value mono">{{ signal.rsi_long.toFixed(2) }}</span>
        </div>
      }
      @if (signal.investment_horizon) {
        <div class="signal-tooltip__row">
          <span class="signal-tooltip__label">Horizon</span>
          <span class="signal-tooltip__value">{{ formatHorizon(signal.investment_horizon) }}</span>
        </div>
      }
      <div class="signal-tooltip__row signal-tooltip__row--wrap">
        <span class="signal-tooltip__label">{{ reasons.length > 1 ? 'Reasons' : 'Reason' }}</span>
        <span class="signal-tooltip__value signal-tooltip__value--wrap">{{ reasons.join(' · ') | titlecase }}</span>
      </div>
      <div class="signal-tooltip__row">
        <span class="signal-tooltip__label">Source</span>
        <span class="signal-tooltip__value">{{ signal.source }}</span>
      </div>
      @if (signal.article_url) {
        <div class="signal-tooltip__row">
          <span class="signal-tooltip__label">Article</span>
          <a
            class="signal-tooltip__link"
            [href]="signal.article_url"
            target="_blank"
            rel="noopener noreferrer"
            (click)="$event.stopPropagation()"
          >Read source article ↗</a>
        </div>
      }
      <div class="signal-tooltip__divider"></div>
      <div class="signal-tooltip__advice" [class.text-green]="isBuy" [class.text-red]="!isBuy">
        {{ adviceHeadline }}
      </div>
      <div class="signal-tooltip__description">
        {{ adviceDescription }}
      </div>
    </div>
  `,
  styles: [`
    .signal-tooltip {
      position: absolute;
      z-index: 1000;
      min-width: 260px;
      max-width: 340px;
      padding: 14px 16px;
      border-radius: 8px;
      background: #12121a;
      border: 1px solid var(--border-color);
      font-family: var(--font-sans);
      font-size: 12px;
      color: var(--text-primary);
      pointer-events: auto;
      animation: tooltipFadeIn 0.15s ease-out;
    }

    .signal-tooltip--buy {
      border-color: rgba(0, 255, 136, 0.35);
      box-shadow: 0 4px 24px rgba(0, 0, 0, 0.6), 0 0 20px rgba(0, 255, 136, 0.12);
    }

    .signal-tooltip--sell {
      border-color: rgba(255, 51, 102, 0.35);
      box-shadow: 0 4px 24px rgba(0, 0, 0, 0.6), 0 0 20px rgba(255, 51, 102, 0.12);
    }

    .signal-tooltip__header {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 8px;
    }

    .signal-tooltip__action {
      font-family: var(--font-mono);
      font-weight: 700;
      font-size: 14px;
      letter-spacing: 1px;
    }

    .signal-tooltip--buy .signal-tooltip__action {
      color: var(--neon-green);
      text-shadow: 0 0 10px rgba(0, 255, 136, 0.5);
    }

    .signal-tooltip--sell .signal-tooltip__action {
      color: var(--neon-red);
      text-shadow: 0 0 10px rgba(255, 51, 102, 0.5);
    }

    .signal-tooltip__coin {
      font-family: var(--font-mono);
      font-weight: 700;
      font-size: 16px;
      color: var(--text-primary);
    }

    .signal-tooltip__divider {
      height: 1px;
      background: var(--border-color);
      margin: 8px 0;
    }

    .signal-tooltip__row {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 3px 0;
    }

    .signal-tooltip__label {
      color: var(--text-muted);
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }

    .signal-tooltip__value {
      font-weight: 500;
      text-align: right;
      max-width: 180px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .signal-tooltip__row--wrap {
      align-items: flex-start;
    }

    .signal-tooltip__value--wrap {
      white-space: normal;
      word-wrap: break-word;
      line-height: 1.4;
    }

    .signal-tooltip__link {
      font-family: var(--font-mono);
      font-size: 11px;
      color: var(--neon-cyan);
      text-decoration: none;
      cursor: pointer;
      transition: color 0.15s, text-shadow 0.15s;

      &:hover {
        color: var(--neon-blue);
        text-shadow: 0 0 8px rgba(0, 170, 255, 0.5);
        text-decoration: underline;
      }
    }

    .signal-tooltip__advice {
      font-family: var(--font-mono);
      font-size: 11px;
      font-weight: 600;
      text-align: center;
      letter-spacing: 0.5px;
      margin-bottom: 6px;
    }

    .signal-tooltip__description {
      font-size: 11px;
      line-height: 1.5;
      color: var(--text-secondary);
      text-align: center;
    }

    .text-green { color: var(--neon-green); }
    .text-red { color: var(--neon-red); }
    .mono { font-family: var(--font-mono); }

    @keyframes tooltipFadeIn {
      from { opacity: 0; transform: translateY(4px); }
      to { opacity: 1; transform: translateY(0); }
    }
  `],
})
export class SignalTooltipComponent {
  @Input() signal!: SignalRecommendation;
  @Input() isBuy = true;

  get reasons(): string[] {
    return (this.signal?.reason || 'sentiment_only')
      .split(',')
      .map(r => r.trim().replaceAll('_', ' '))
      .filter(r => r.length > 0);
  }

  formatHorizon(value: string): string {
    if (value === 'long_term') return 'Long-term';
    if (value === 'short_term') return 'Short-term (Day Trading)';
    if (value === 'both') return 'Both';
    if (value === 'avoid') return 'Avoid for now';
    return 'Unknown';
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
