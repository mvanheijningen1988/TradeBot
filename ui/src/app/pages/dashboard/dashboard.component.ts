import { Component, OnInit, OnDestroy, inject, ElementRef, ViewChild } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { Subscription, forkJoin } from 'rxjs';
import { BotService, Bot } from '../../services/bot.service';
import { ExchangeService, Exchange, Balance } from '../../services/exchange.service';
import { WebSocketService } from '../../services/websocket.service';
import { DropdownComponent, DropdownOption } from '../../shared/dropdown/dropdown.component';

interface BudgetPoint {
  timestamp: string;
  balance: number;
}

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [CommonModule, RouterModule, FormsModule, DropdownComponent],
  templateUrl: './dashboard.component.html',
  styleUrl: './dashboard.component.scss',
})
export class DashboardComponent implements OnInit, OnDestroy {
  private botService = inject(BotService);
  private exchangeService = inject(ExchangeService);
  private wsService = inject(WebSocketService);
  private wsSub?: Subscription;

  @ViewChild('budgetChart') budgetChartRef!: ElementRef<HTMLCanvasElement>;

  bots: Bot[] = [];
  exchanges: Exchange[] = [];
  exchangeBalances: { [key: number]: Balance[] } = {};

  openOrders: Record<string, unknown>[] = [];
  orderHistory: Record<string, unknown>[] = [];
  tradeHistory: Record<string, unknown>[] = [];

  // Budget trend
  budgetData: BudgetPoint[] = [];
  filteredBudgetData: BudgetPoint[] = [];
  selectedBudgetBot: string | number = 'overall';
  selectedTimeFilter = '30m';
  budgetBotOptions: DropdownOption[] = [{ value: 'overall', label: 'Overall' }];
  timeFilters = [
    { value: '1m', label: '1m' },
    { value: '5m', label: '5m' },
    { value: '10m', label: '10m' },
    { value: '15m', label: '15m' },
    { value: '30m', label: '30m' },
    { value: '1h', label: '1h' },
    { value: '2h', label: '2h' },
  ];

  get faultBots(): Bot[] {
    return this.bots.filter((b) => b.status === 'fault');
  }

  ngOnInit(): void {
    this.loadBots();
    this.loadExchanges();
    this.loadAllOrders();

    this.wsService.connect();
    this.wsSub = this.wsService.messages.subscribe((msg) => {
      if (msg['type'] === 'status') {
        const bot = this.bots.find((b) => b.id === msg['bot_id']);
        if (bot) bot.status = msg['status'] as string;
      }
    });
  }

  ngOnDestroy(): void {
    this.wsSub?.unsubscribe();
  }

  loadBots(): void {
    this.botService.list().subscribe((bots) => {
      this.bots = bots;
      this.budgetBotOptions = [
        { value: 'overall', label: 'Overall' },
        ...bots.map((b) => ({ value: b.id, label: b.name })),
      ];
      this.loadBudgetHistory();
    });
  }

  loadExchanges(): void {
    this.exchangeService.list().subscribe((exs) => {
      this.exchanges = exs;
      for (const ex of exs) {
        this.exchangeService.getBalances(ex.id).subscribe((bals) => {
          this.exchangeBalances[ex.id] = bals;
        });
      }
    });
  }

  loadAllOrders(): void {
    this.botService.list().subscribe((bots) => {
      for (const bot of bots) {
        this.botService.getOrders(bot.id).subscribe((orders) => {
          for (const o of orders) {
            const order = o as Record<string, unknown>;
            order['bot_id'] = bot.id;
            if (order['status'] === 'new' || order['status'] === 'partiallyFilled') {
              this.openOrders.push(order);
            } else {
              this.orderHistory.push(order);
            }
          }
        });
        this.botService.getTrades(bot.id).subscribe((trades) => {
          for (const t of trades) {
            const trade = t as Record<string, unknown>;
            trade['bot_id'] = bot.id;
            this.tradeHistory.push(trade);
          }
        });
      }
    });
  }

  loadBudgetHistory(): void {
    if (this.selectedBudgetBot === 'overall') {
      this.botService.getOverallBudgetHistory().subscribe((data) => {
        this.budgetData = (data as BudgetPoint[]);
        this.filterBudgetData();
      });
    } else {
      const botId = this.selectedBudgetBot as number;
      this.botService.getBudgetHistory(botId).subscribe((data) => {
        this.budgetData = (data as BudgetPoint[]);
        this.filterBudgetData();
      });
    }
  }

  filterBudgetData(): void {
    const now = Date.now();
    const minutes: Record<string, number> = {
      '1m': 1, '5m': 5, '10m': 10, '15m': 15, '30m': 30, '1h': 60, '2h': 120,
    };
    const mins = minutes[this.selectedTimeFilter] || 30;
    const cutoff = now - mins * 60 * 1000;

    this.filteredBudgetData = this.budgetData.filter(
      (p) => new Date(p.timestamp).getTime() >= cutoff
    );
    this.drawChart();
  }

  drawChart(): void {
    if (!this.budgetChartRef) return;
    const canvas = this.budgetChartRef.nativeElement;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const rect = canvas.parentElement?.getBoundingClientRect();
    canvas.width = rect?.width || 800;
    canvas.height = rect?.height || 250;

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    const data = [...this.filteredBudgetData].reverse();
    if (data.length < 2) return;

    const values = data.map((d) => d.balance);
    const minVal = Math.min(...values);
    const maxVal = Math.max(...values);
    const range = maxVal - minVal || 1;

    const padding = { top: 20, right: 20, bottom: 30, left: 60 };
    const w = canvas.width - padding.left - padding.right;
    const h = canvas.height - padding.top - padding.bottom;

    // Grid lines
    ctx.strokeStyle = 'rgba(42, 42, 68, 0.5)';
    ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i++) {
      const y = padding.top + (h / 4) * i;
      ctx.beginPath();
      ctx.moveTo(padding.left, y);
      ctx.lineTo(canvas.width - padding.right, y);
      ctx.stroke();

      const val = maxVal - (range / 4) * i;
      ctx.fillStyle = '#666';
      ctx.font = '10px monospace';
      ctx.textAlign = 'right';
      ctx.fillText(val.toFixed(2), padding.left - 8, y + 4);
    }

    // Line
    ctx.beginPath();
    ctx.strokeStyle = '#00aaff';
    ctx.lineWidth = 2;
    ctx.shadowColor = 'rgba(0, 170, 255, 0.5)';
    ctx.shadowBlur = 6;

    for (let i = 0; i < data.length; i++) {
      const x = padding.left + (i / (data.length - 1)) * w;
      const y = padding.top + h - ((data[i].balance - minVal) / range) * h;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();

    // Gradient fill
    ctx.shadowBlur = 0;
    const lastX = padding.left + w;
    ctx.lineTo(lastX, padding.top + h);
    ctx.lineTo(padding.left, padding.top + h);
    ctx.closePath();
    const gradient = ctx.createLinearGradient(0, padding.top, 0, padding.top + h);
    gradient.addColorStop(0, 'rgba(0, 170, 255, 0.15)');
    gradient.addColorStop(1, 'rgba(0, 170, 255, 0)');
    ctx.fillStyle = gradient;
    ctx.fill();
  }

  getBotName(botId: unknown): string {
    const id = botId as number;
    return this.bots.find((b) => b.id === id)?.name || `Bot #${id}`;
  }

  getBalances(exchangeId: number): Balance[] {
    return this.exchangeBalances[exchangeId] || [];
  }

  startBot(bot: Bot): void {
    this.botService.start(bot.id).subscribe((b) => {
      const idx = this.bots.findIndex((x) => x.id === b.id);
      if (idx >= 0) this.bots[idx] = b;
    });
  }

  stopBot(bot: Bot): void {
    this.botService.stop(bot.id).subscribe((b) => {
      const idx = this.bots.findIndex((x) => x.id === b.id);
      if (idx >= 0) this.bots[idx] = b;
    });
  }

  deleteBot(bot: Bot): void {
    if (confirm(`Delete bot "${bot.name}"?`)) {
      this.botService.delete(bot.id).subscribe(() => this.loadBots());
    }
  }
}
