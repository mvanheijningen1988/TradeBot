import { Component, OnInit, OnDestroy, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Subscription } from 'rxjs';
import { Toast, ToastService } from './toast.service';

@Component({
  selector: 'app-toast-container',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './toast.component.html',
  styleUrl: './toast.component.scss',
})
export class ToastContainerComponent implements OnInit, OnDestroy {
  private toastService = inject(ToastService);
  private sub?: Subscription;
  activeToasts: Toast[] = [];

  ngOnInit(): void {
    this.sub = this.toastService.toasts.subscribe((toast) => {
      this.activeToasts.push(toast);
      setTimeout(() => this.dismiss(toast.id), toast.duration);
    });
  }

  ngOnDestroy(): void {
    this.sub?.unsubscribe();
  }

  dismiss(id: number): void {
    this.activeToasts = this.activeToasts.filter((t) => t.id !== id);
  }
}
