import { Component, inject, OnInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router, RouterModule } from '@angular/router';
import { Subscription } from 'rxjs';
import { AuthService, User } from '../services/auth.service';
import { SignalsService, SignalRecommendation } from '../services/signals.service';
import { WebSocketService } from '../services/websocket.service';
import { WorkerService } from '../services/worker.service';
import { ToastService } from '../shared/toast/toast.service';
import { SignalTooltipComponent } from '../shared/signal-tooltip/signal-tooltip.component';

@Component({
  selector: 'app-layout',
  standalone: true,
  imports: [CommonModule, RouterModule, SignalTooltipComponent],
  templateUrl: './layout.component.html',
  styleUrl: './layout.component.scss',
})
export class LayoutComponent implements OnInit, OnDestroy {
  auth: AuthService = inject(AuthService);
  private readonly wsService = inject(WebSocketService);
  private readonly workerService = inject(WorkerService);
  private readonly toastService = inject(ToastService);
  private readonly signalsService = inject(SignalsService);
  private readonly router = inject(Router);
  private wsSub?: Subscription;
  private signalsRefreshSub?: Subscription;
  private signalsRefreshTimer?: ReturnType<typeof setInterval>;

  currentUser: User | null = null;
  pendingWorkers = 0;
  private readonly knownPendingIds = new Set<number>();

  sidebarCollapsed = false;
  signalsPanelOpen = false;

  investSignals: SignalRecommendation[] = [];
  removeSignals: SignalRecommendation[] = [];
  signalsLoading = false;
  hoveredSignal: SignalRecommendation | null = null;
  hoveredIsBuy = true;
  tooltipTop = 0;
  tooltipLeft = 0;
  private tooltipHideTimer: ReturnType<typeof setTimeout> | null = null;

  get signalCount(): number {
    return this.investSignals.length + this.removeSignals.length;
  }

  ngOnInit(): void {
    this.auth.loadUser();
    this.auth.currentUser$.subscribe((u: User | null) => this.currentUser = u);

    // Load initial pending worker count from REST API (badge only, no toast).
    this.workerService.list().subscribe((workers) => {
      const pending = workers.filter((w) => w.status === 'pending');
      this.pendingWorkers = pending.length;
      for (const w of pending) {
        this.knownPendingIds.add(w.id);
      }
    });

    this.loadSignals();
    this.signalsRefreshTimer = setInterval(() => {
      this.loadSignals();
    }, 30_000);

    this.signalsRefreshSub = this.signalsService.refresh$.subscribe(() => {
      this.investSignals = [];
      this.removeSignals = [];
      this.signalsLoading = true;
      this.loadSignals(true);
    });

    this.wsService.connect();
    this.wsSub = this.wsService.messages.subscribe((msg) => {
      if (msg['type'] === 'worker_registered') {
        const worker = msg['worker'] as Record<string, unknown> | undefined;
        const workerId = worker?.['id'] as number | undefined;
        const agentId = (worker?.['agent_id'] as string) ?? 'unknown';
        // Only show toast once per worker to avoid duplicates from re-registration.
        if (workerId && !this.knownPendingIds.has(workerId)) {
          this.knownPendingIds.add(workerId);
          this.pendingWorkers++;
          this.toastService.warning(
            'New Worker Pending',
            `Worker "${agentId}" is waiting for approval.`
          );
        }
      }
      if (msg['type'] === 'worker_status') {
        const worker = msg['worker'] as Record<string, unknown> | undefined;
        const workerId = worker?.['id'] as number | undefined;
        const agentId = (worker?.['agent_id'] as string) ?? 'unknown';
        if (msg['status'] === 'approved' || msg['status'] === 'rejected') {
          this.pendingWorkers = Math.max(0, this.pendingWorkers - 1);
          if (workerId) this.knownPendingIds.delete(workerId);
        }
        if (msg['status'] === 'online' || msg['status'] === 'approved') {
          this.toastService.success(
            'Worker Online',
            `Worker "${agentId}" is connected.`
          );
        }
      }
    });
  }

  ngOnDestroy(): void {
    this.wsSub?.unsubscribe();
    this.signalsRefreshSub?.unsubscribe();
    if (this.signalsRefreshTimer) {
      clearInterval(this.signalsRefreshTimer);
      this.signalsRefreshTimer = undefined;
    }
  }

  logout(): void {
    this.auth.logout();
    this.wsService.disconnect();
    globalThis.location.href = '/login';
  }

  toggleSidebar(): void {
    this.sidebarCollapsed = !this.sidebarCollapsed;
  }

  toggleSignalsPanel(): void {
    this.signalsPanelOpen = !this.signalsPanelOpen;
  }

  loadSignals(notifyRefreshComplete = false): void {
    this.signalsService.getRecommendations().subscribe({
      next: (data) => {
        this.investSignals = data.invest;
        this.removeSignals = data.remove;
        this.signalsLoading = false;
        if (notifyRefreshComplete) {
          this.signalsService.refreshCompleted$.next();
        }
      },
      error: () => {
        this.investSignals = [];
        this.removeSignals = [];
        this.signalsLoading = false;
        if (notifyRefreshComplete) {
          this.signalsService.refreshCompleted$.next();
        }
      },
    });
  }

  showTooltip(event: MouseEvent, signal: SignalRecommendation, isBuy: boolean): void {
    if (this.tooltipHideTimer) {
      clearTimeout(this.tooltipHideTimer);
      this.tooltipHideTimer = null;
    }
    const target = event.currentTarget as HTMLElement;
    const rect = target.getBoundingClientRect();
    this.tooltipTop = rect.bottom + 8;
    this.tooltipLeft = rect.left - 300;
    this.hoveredSignal = signal;
    this.hoveredIsBuy = isBuy;
  }

  keepTooltip(): void {
    if (this.tooltipHideTimer) {
      clearTimeout(this.tooltipHideTimer);
      this.tooltipHideTimer = null;
    }
  }

  hideTooltip(): void {
    this.tooltipHideTimer = setTimeout(() => {
      this.hoveredSignal = null;
      this.tooltipHideTimer = null;
    }, 150);
  }

  formatReasons(reason: string): string[] {
    return (reason || 'sentiment_only')
      .split(',')
      .map(r => r.trim().replaceAll('_', ' '))
      .filter(r => r.length > 0);
  }

  navigateToCreateBot(coin: string): void {
    this.router.navigate(['/bots/new'], { queryParams: { coin } });
  }
}
