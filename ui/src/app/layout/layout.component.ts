import { Component, inject, OnInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { Subscription } from 'rxjs';
import { AuthService, User } from '../services/auth.service';
import { WebSocketService } from '../services/websocket.service';
import { WorkerService } from '../services/worker.service';
import { ToastService } from '../shared/toast/toast.service';

@Component({
  selector: 'app-layout',
  standalone: true,
  imports: [CommonModule, RouterModule],
  templateUrl: './layout.component.html',
  styleUrl: './layout.component.scss',
})
export class LayoutComponent implements OnInit, OnDestroy {
  auth: AuthService = inject(AuthService);
  private wsService = inject(WebSocketService);
  private workerService = inject(WorkerService);
  private toastService = inject(ToastService);
  private wsSub?: Subscription;

  currentUser: User | null = null;
  pendingWorkers = 0;
  private knownPendingIds = new Set<number>();

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

    this.wsService.connect();
    this.wsSub = this.wsService.messages.subscribe((msg) => {
      if (msg['type'] === 'worker_registered') {
        const worker = msg['worker'] as Record<string, unknown> | undefined;
        const workerId = worker?.['id'] as number | undefined;
        const agentId = worker?.['agent_id'] ?? 'unknown';
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
        const agentId = worker?.['agent_id'] ?? 'unknown';
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
  }

  logout(): void {
    this.auth.logout();
    this.wsService.disconnect();
    window.location.href = '/login';
  }
}
