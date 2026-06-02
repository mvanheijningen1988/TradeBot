import { Component, OnInit, OnDestroy, inject, ElementRef, ViewChild } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Subscription } from 'rxjs';
import { WorkerService, Worker } from '../../services/worker.service';
import { BotService, Bot } from '../../services/bot.service';
import { WebSocketService } from '../../services/websocket.service';
import { DiagnosticsService, LogEntry } from '../../services/diagnostics.service';

@Component({
  selector: 'app-workers',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './workers.component.html',
  styleUrl: './workers.component.scss',
})
export class WorkersComponent implements OnInit, OnDestroy {
  private workerService = inject(WorkerService);
  private botService = inject(BotService);
  private wsService = inject(WebSocketService);
  private diagService = inject(DiagnosticsService);
  private wsSub?: Subscription;

  @ViewChild('logContainer') logContainer?: ElementRef<HTMLDivElement>;

  workers: Worker[] = [];
  workerBots: Bot[] = [];
  expandedWorker: number | null = null;
  logWorkerId: number | null = null;
  logWorkerName = '';
  workerLogs: LogEntry[] = [];

  ngOnInit(): void {
    this.load();
    this.wsSub = this.wsService.messages.subscribe((msg) => {
      if (msg['type'] === 'worker_registered' || msg['type'] === 'worker_status') {
        this.load();
      }
      if (msg['type'] === 'bot_log' && this.logWorkerId !== null) {
        const wid = msg['worker_id'] as number | undefined;
        if (wid === this.logWorkerId) {
          this.workerLogs.push({
            id: 0,
            category: (msg['category'] as string) || 'bot',
            subcategory: (msg['subcategory'] as string) || '',
            level: (msg['level'] as string) || 'INFO',
            message: (msg['message'] as string) || '',
            correlation_id: (msg['correlation_id'] as string) || null,
            bot_id: (msg['bot_id'] as number) || null,
            worker_id: wid ?? null,
            timestamp: new Date().toISOString().replace('T', ' ').substring(0, 19),
          });
          this.scrollLogsToBottom();
        }
      }
    });
  }

  ngOnDestroy(): void {
    this.wsSub?.unsubscribe();
  }

  load(): void {
    this.workerService.list().subscribe((w) => (this.workers = w));
  }

  approve(w: Worker): void {
    this.workerService.approve(w.id).subscribe(() => this.load());
  }

  reject(w: Worker): void {
    this.workerService.reject(w.id).subscribe(() => this.load());
  }

  remove(w: Worker): void {
    if (confirm(`Remove worker "${w.agent_id}"?`)) {
      this.workerService.remove(w.id).subscribe(() => this.load());
    }
  }

  toggleLogs(w: Worker): void {
    if (this.logWorkerId === w.id) {
      this.closeLogs();
      return;
    }
    this.logWorkerId = w.id;
    this.logWorkerName = w.agent_id;
    this.workerLogs = [];
    this.diagService
      .getLogs({ worker_id: w.id, limit: 200 })
      .subscribe((logs) => {
        this.workerLogs = logs.reverse();
        this.scrollLogsToBottom();
      });
  }

  closeLogs(): void {
    this.logWorkerId = null;
    this.logWorkerName = '';
    this.workerLogs = [];
  }

  private scrollLogsToBottom(): void {
    setTimeout(() => {
      const el = this.logContainer?.nativeElement;
      if (el) {
        el.scrollTop = el.scrollHeight;
      }
    });
  }
}
