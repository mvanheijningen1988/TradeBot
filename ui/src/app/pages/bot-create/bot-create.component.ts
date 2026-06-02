import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router, RouterModule } from '@angular/router';
import { BotService } from '../../services/bot.service';
import { ExchangeService, Exchange, MarketInfo } from '../../services/exchange.service';
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

  exchanges: Exchange[] = [];
  markets: MarketInfo[] = [];
  error = '';

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
    this.exchangeService.list().subscribe((exs) => {
      this.exchanges = exs;
      this.exchangeOptions = exs.map((e) => ({ value: e.id, label: e.name }));
    });
  }

  onExchangeChange(): void {
    const exId = this.form.exchange_id as number;
    if (exId > 0) {
      this.exchangeService
        .getMarkets(exId)
        .subscribe((m) => {
          this.markets = m;
          this.marketOptions = m.map((mk) => ({ value: mk.market, label: mk.market }));
        });
    }
  }

  onCreate(): void {
    this.error = '';
    if (!this.form.name || !this.form.market || this.form.exchange_id === 0) {
      this.error = 'Please fill in all required fields.';
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
        next: () => this.router.navigate(['/']),
        error: (err) =>
          (this.error = err.error?.detail || 'Failed to create bot.'),
      });
  }
}
