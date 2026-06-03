import { Component, OnInit, inject } from '@angular/core';
import { CommonModule, Location } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterModule } from '@angular/router';
import { BotService } from '../../services/bot.service';
import { ExchangeService, Exchange, MarketInfo, BudgetAvailable } from '../../services/exchange.service';
import { DropdownComponent, DropdownOption } from '../../shared/dropdown/dropdown.component';

@Component({
  selector: 'app-bot-create',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterModule, DropdownComponent],
  templateUrl: './bot-create.component.html',
  styleUrl: './bot-create.component.scss',
})
export class BotCreateComponent implements OnInit {
  private botService = inject(BotService);
  private exchangeService = inject(ExchangeService);
  private router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly location = inject(Location);

  exchanges: Exchange[] = [];
  markets: MarketInfo[] = [];
  error = '';
  private coinIcons: Record<string, { img_url?: string }> = {};
  private preselectedCoin = '';
  budgetInfo: BudgetAvailable | null = null;
  budgetLoading = false;
  fees: { taker: number; maker: number } | null = null;
  feesLoading = false;

  exchangeOptions: DropdownOption[] = [];
  marketOptions: DropdownOption[] = [];
  strategyOptions: DropdownOption[] = [
    { value: 'grid_trading', label: 'Grid Trading' },
    { value: 'dca', label: 'Dollar Cost Averaging' },
    { value: 'martingale', label: 'Martingale' },
  ];
  profitModeOptions: DropdownOption[] = [
    { value: 'withdraw', label: 'Withdraw' },
    { value: 'compound', label: 'Compound' },
    { value: 'skim', label: 'Skim' },
  ];
  intervalOptions: DropdownOption[] = [
    { value: 'hourly', label: 'Hourly' },
    { value: 'daily', label: 'Daily' },
    { value: 'weekly', label: 'Weekly' },
    { value: 'biweekly', label: 'Biweekly' },
    { value: 'monthly', label: 'Monthly' },
  ];

  form = {
    name: '',
    exchange_id: 0 as string | number,
    market: '' as string | number,
    strategy: 'grid_trading' as string | number,
    budget_quote: 0,
    profit_mode: 'withdraw' as string | number,
    profit_skim_pct: 0,
  };

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  params: any = {
    upper_price: 0,
    lower_price: 0,
    num_grids: 10,
  };

  ngOnInit(): void {
    this.preselectedCoin = (this.route.snapshot.queryParamMap.get('coin') ?? '').toUpperCase();

    this.exchangeService.list().subscribe((exs) => {
      this.exchanges = exs;
      this.exchangeOptions = exs.map((e) => ({ value: e.id, label: e.name }));

      // Auto-select the first exchange when navigating from a signal
      if (this.preselectedCoin && exs.length > 0) {
        this.form.exchange_id = exs[0].id;
        this.onExchangeChange();
      }
    });
  }

  onExchangeChange(): void {
    const exId = this.form.exchange_id as number;
    if (exId > 0) {
      this.exchangeService
        .getMarkets(exId)
        .subscribe((m) => {
          this.markets = m;
          if (Object.keys(this.coinIcons).length > 0) {
            this.buildMarketOptions();
          } else {
            this.exchangeService.getIcons().subscribe((icons) => {
              this.coinIcons = icons as Record<string, { img_url?: string }>;
              this.buildMarketOptions();
            });
          }
        });
      this.loadFees(exId);
    }
  }

  private loadFees(exchangeId: number): void {
    this.feesLoading = true;
    this.exchangeService.getFees(exchangeId).subscribe({
      next: (f) => {
        this.fees = { taker: parseFloat(f.taker), maker: parseFloat(f.maker) };
        this.feesLoading = false;
      },
      error: () => {
        this.fees = null;
        this.feesLoading = false;
      },
    });
  }

  private buildMarketOptions(): void {
    this.marketOptions = this.markets.map((mk) => {
      const base = mk.base.toUpperCase();
      const icon = this.coinIcons[base]?.img_url;
      return { value: mk.market, label: mk.market, ...(icon ? { icon } : {}) };
    });

    // Auto-select the first market matching the preselected coin
    if (this.preselectedCoin && !this.form.market) {
      const coin = this.preselectedCoin;
      const match = this.markets.find(
        (mk) => mk.base.toUpperCase() === coin
      );
      if (match) {
        this.form.market = match.market;
      }
    }

    this.loadBudgetInfo();
  }

  onMarketChange(): void {
    this.loadBudgetInfo();
  }

  get selectedMarket(): MarketInfo | null {
    if (!this.form.market) return null;
    return this.markets.find((m) => m.market === this.form.market) ?? null;
  }

  /**
   * Grid profitability analysis.
   *
   * For each completed grid cycle (buy low → sell high):
   *   gridStep     = (upper - lower) / numGrids
   *   avgPrice     = (upper + lower) / 2
   *   buyFee       = avgPrice × takerFee      (taker = market order)
   *   sellFee      = avgPrice × makerFee      (maker = limit order)
   *   grossProfit  = gridStep
   *   feeCost      = buyFee + sellFee
   *   netProfit    = grossProfit − feeCost
   *   profitPct    = (netProfit / avgPrice) × 100
   */
  get gridAnalysis(): {
    gridStep: number;
    budgetPerGrid: number;
    grossProfit: number;
    feeCost: number;
    netProfit: number;
    profitPct: number;
    profitable: boolean;
    numOrders: number;
    minOrderQuote: number;
    minOrderBase: number;
    belowMinOrder: boolean;
  } | null {
    if (this.form.strategy !== 'grid_trading') return null;
    const upper = this.params.upper_price;
    const lower = this.params.lower_price;
    const grids = this.params.num_grids;
    const budget = this.form.budget_quote;

    if (!upper || !lower || !grids || grids < 2 || upper <= lower) return null;
    if (!this.fees) return null;

    const gridStep = (upper - lower) / grids;
    const avgPrice = (upper + lower) / 2;
    const numOrders = grids + 1; // orders placed at each grid level
    const budgetPerGrid = budget / numOrders;

    const buyFee = avgPrice * this.fees.taker;
    const sellFee = avgPrice * this.fees.maker;
    const feeCost = buyFee + sellFee;
    const grossProfit = gridStep;
    const netProfit = grossProfit - feeCost;
    const profitPct = (netProfit / avgPrice) * 100;

    const mk = this.selectedMarket;
    const minOrderQuote = mk ? parseFloat(mk.min_order_quote) : 0;
    const minOrderBase = mk ? parseFloat(mk.min_order_base) : 0;
    const belowMinOrder = minOrderQuote > 0 && budgetPerGrid < minOrderQuote;

    return {
      gridStep: +gridStep.toFixed(6),
      budgetPerGrid: +budgetPerGrid.toFixed(2),
      grossProfit: +grossProfit.toFixed(6),
      feeCost: +feeCost.toFixed(6),
      netProfit: +netProfit.toFixed(6),
      profitPct: +profitPct.toFixed(4),
      profitable: netProfit > 0,
      numOrders,
      minOrderQuote,
      minOrderBase,
      belowMinOrder,
    };
  }

  private loadBudgetInfo(): void {
    const exId = this.form.exchange_id as number;
    const market = this.form.market as string;
    if (!exId || !market) {
      this.budgetInfo = null;
      return;
    }
    const mk = this.markets.find((m) => m.market === market);
    if (!mk) {
      this.budgetInfo = null;
      return;
    }
    this.budgetLoading = true;
    this.exchangeService.getBudgetAvailable(exId, mk.quote).subscribe({
      next: (info) => {
        this.budgetInfo = info;
        this.budgetLoading = false;
      },
      error: () => {
        this.budgetInfo = null;
        this.budgetLoading = false;
      },
    });
  }

  onCreate(): void {
    this.error = '';
    if (!this.form.name || !this.form.market || this.form.exchange_id === 0) {
      this.error = 'Please fill in all required fields.';
      return;
    }
    if (this.budgetInfo && this.form.budget_quote > this.budgetInfo.free) {
      this.error = `Budget exceeds available: ${this.budgetInfo.free} ${this.budgetInfo.quote} free.`;
      return;
    }
    const g = this.gridAnalysis;
    if (g && !g.profitable) {
      this.error = 'Grid is not profitable: fee cost per trade exceeds grid step profit. Widen price range or reduce grids.';
      return;
    }
    if (g && g.belowMinOrder) {
      this.error = `Budget per grid (${g.budgetPerGrid.toFixed(2)}) is below the exchange minimum order of ${g.minOrderQuote} quote. Increase budget or reduce grids.`;
      return;
    }
    this.botService
      .create({
        name: this.form.name,
        exchange_id: this.form.exchange_id as number,
        market: this.form.market as string,
        strategy: this.form.strategy as string,
        budget_quote: this.form.budget_quote,
        profit_mode: this.form.profit_mode as string,
        profit_skim_pct: this.form.profit_skim_pct,
        strategy_params: this.params,
      })
      .subscribe({
        next: () => this.close(),
        error: (err) =>
          (this.error = err.error?.detail || 'Failed to create bot.'),
      });
  }

  onCancel(): void {
    this.close();
  }

  onBackdropClick(event: MouseEvent): void {
    if (event.target === event.currentTarget) {
      this.close();
    }
  }

  private close(): void {
    if (globalThis.history.length > 1) {
      this.location.back();
    } else {
      this.router.navigate(['/']);
    }
  }
}
